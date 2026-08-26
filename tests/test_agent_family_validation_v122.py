from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.research import (
    AgentFamilyDevelopmentEvidence,
    FormalAgentExperimentFamilyValidator,
    SQLiteAgentFamilyValidationStore,
    SQLiteResearchRegistry,
)


NOW = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)


def _universe() -> tuple[AssetId, ...]:
    return tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ")
    )


def _registry(tmp_path, *, frozen: bool = True) -> tuple[SQLiteResearchRegistry, tuple[str, ...]]:
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    dataset = ArtifactRef("dataset", ArtifactType.DATASET, "v1", "d" * 64)
    experiment_ids: list[str] = []
    for index in range(3):
        experiment_id = f"exp-{index + 1}"
        spec = ExperimentSpec(
            experiment_id=experiment_id,
            hypothesis=f"candidate {index + 1}",
            dataset=dataset,
            code=ArtifactRef(
                f"code-{index + 1}",
                ArtifactType.CODE,
                "v1",
                chr(ord("a") + index) * 64,
            ),
            universe=_universe(),
            parameters={"candidate": index + 1},
            seed=0,
        )
        registry.register_experiment(spec)
        experiment_ids.append(experiment_id)
    registry.register_family(
        ExperimentFamily(
            family_id="formal-agent-family",
            research_question="which pre-registered candidate survives development evidence?",
            primary_metric="net_sharpe",
            created_at=NOW,
            alpha=0.20,
            metadata={"dataset_digest": "d" * 64},
        )
    )
    for experiment_id in experiment_ids:
        registry.add_experiment_to_family(
            "formal-agent-family",
            experiment_id,
            added_at=NOW,
        )
    if frozen:
        registry.transition_family("formal-agent-family", ExperimentFamilyStatus.FROZEN)
    return registry, tuple(sorted(experiment_ids))


def _evidence(experiment_order: tuple[str, ...]) -> AgentFamilyDevelopmentEvidence:
    timestamps = tuple((NOW + timedelta(days=index)).isoformat() for index in range(80))
    index = np.arange(80, dtype=float)
    strong = 0.018 + 0.0020 * np.sin(index / 3.0)
    medium = 0.006 + 0.0040 * np.cos(index / 5.0)
    noise = 0.0002 * np.sin(index * 1.7) - 0.0003 * np.cos(index / 2.0)
    returns = {
        experiment_order[0]: tuple(float(value) for value in strong),
        experiment_order[1]: tuple(float(value) for value in medium),
        experiment_order[2]: tuple(float(value) for value in noise),
    }
    return AgentFamilyDevelopmentEvidence(
        family_id="formal-agent-family",
        experiment_order=experiment_order,
        timestamps=timestamps,
        trial_returns=returns,
        pvalues={
            experiment_order[0]: 0.001,
            experiment_order[1]: 0.010,
            experiment_order[2]: 0.80,
        },
        dataset_digest="d" * 64,
    )


def test_formal_family_validation_uses_every_registered_member_without_selecting_winner(tmp_path):
    registry, experiment_order = _registry(tmp_path)
    evidence = _evidence(experiment_order)

    report = FormalAgentExperimentFamilyValidator(registry).validate(
        evidence,
        dsr_probability_threshold=0.50,
        pbo_threshold=1.0,
        pbo_blocks=8,
        bootstrap_samples=100,
        seed=7,
    )

    assert report.experiment_order == experiment_order
    assert tuple(item.experiment_id for item in report.candidates) == experiment_order
    assert report.observation_count == 80
    assert report.multiple_testing.raw_pvalues == pytest.approx((0.001, 0.010, 0.80))
    assert report.pbo.blocks == 8
    assert report.reality_check.bootstrap_samples == 100
    assert all(item.deflated_sharpe.n_trials == 3 for item in report.candidates)
    assert experiment_order[0] in report.eligible_experiment_ids
    assert experiment_order[2] not in report.eligible_experiment_ids
    assert not hasattr(report, "selected_experiment_id")


def test_formal_family_validation_rejects_unfrozen_or_changed_denominator(tmp_path):
    registry, experiment_order = _registry(tmp_path, frozen=False)
    evidence = _evidence(experiment_order)
    validator = FormalAgentExperimentFamilyValidator(registry)
    with pytest.raises(ValueError, match="FROZEN"):
        validator.validate(evidence, pbo_blocks=8, bootstrap_samples=20)

    registry.transition_family("formal-agent-family", ExperimentFamilyStatus.FROZEN)
    reordered = (experiment_order[1], experiment_order[0], experiment_order[2])
    changed = AgentFamilyDevelopmentEvidence(
        family_id=evidence.family_id,
        experiment_order=reordered,
        timestamps=evidence.timestamps,
        trial_returns={key: evidence.trial_returns[key] for key in reordered},
        pvalues={key: evidence.pvalues[key] for key in reordered},
        dataset_digest=evidence.dataset_digest,
    )
    with pytest.raises(ValueError, match="order does not match"):
        validator.validate(changed, pbo_blocks=8, bootstrap_samples=20)


def test_development_evidence_rejects_overlapping_outer_timestamps():
    with pytest.raises(ValueError, match="non-overlapping"):
        AgentFamilyDevelopmentEvidence(
            family_id="family",
            experiment_order=("exp-1", "exp-2"),
            timestamps=(NOW.isoformat(), NOW.isoformat()),
            trial_returns={"exp-1": (0.01, 0.02), "exp-2": (0.00, 0.01)},
            pvalues={"exp-1": 0.01, "exp-2": 0.20},
            dataset_digest="d" * 64,
        )


def test_formal_family_validation_store_is_append_only(tmp_path):
    registry, experiment_order = _registry(tmp_path)
    report = FormalAgentExperimentFamilyValidator(registry).validate(
        _evidence(experiment_order),
        dsr_probability_threshold=0.50,
        pbo_threshold=1.0,
        pbo_blocks=8,
        bootstrap_samples=30,
        seed=3,
    )
    store = SQLiteAgentFamilyValidationStore(tmp_path / "family-validation.sqlite")
    store.register(report)
    store.register(report)
    stored = store.get(report.report_id)
    assert stored["family_id"] == "formal-agent-family"
    assert stored["experiment_order"] == list(experiment_order)
    assert stored["eligible_experiment_ids"] == list(report.eligible_experiment_ids)
