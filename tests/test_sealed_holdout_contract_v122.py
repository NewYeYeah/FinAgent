from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.research.agent_family import AgentMarketProgramPlan
from finagent.research.agent_family_validation import (
    AgentFamilyDevelopmentEvidence,
    FormalAgentExperimentFamilyValidator,
)
from finagent.research.agent_market import AgentMarketResearchConfig
from finagent.research.final_strategy import FinalStrategySelector
from finagent.research.holdout import (
    HoldoutEligibilitySealer,
    SQLiteHoldoutEligibilityStore,
    SQLiteSealedHoldoutStore,
    SealedHoldoutSpec,
    development_evidence_digest,
)
from finagent.research.programs import ResearchProgram, SQLiteResearchProgramStore
from finagent.research.registry import SQLiteResearchRegistry


NOW = datetime(2026, 8, 26, 5, 0, tzinfo=UTC)


def _universe() -> tuple[AssetId, ...]:
    return tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ")
    )


def _holdout_spec() -> SealedHoldoutSpec:
    return SealedHoldoutSpec(
        holdout_id="holdout-001",
        program_id="program-001",
        dataset=ArtifactRef("holdout-dataset", ArtifactType.DATASET, "v1", "h" * 64),
        universe=_universe(),
        provider="alpaca",
        data_version="alpaca-snapshot-2026-08-01",
        training_start=datetime(2023, 1, 1, tzinfo=UTC),
        training_end=datetime(2025, 7, 1, tzinfo=UTC),
        holdout_start=datetime(2025, 7, 1, tzinfo=UTC),
        holdout_end=datetime(2026, 1, 1, tzinfo=UTC),
        created_at=NOW,
    )


def _program_store(tmp_path) -> SQLiteResearchProgramStore:
    store = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    store.register(
        ResearchProgram(
            program_id="program-001",
            alpha_budget=0.25,
            max_families=2,
            max_experiments=6,
            sealed_holdout_id="holdout-001",
        )
    )
    return store


def _formal_research(tmp_path, program_store):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    dataset = ArtifactRef("development-dataset", ArtifactType.DATASET, "v1", "d" * 64)
    digests = ("a" * 64, "b" * 64, "c" * 64)
    experiment_ids: list[str] = []
    for index, digest in enumerate(digests, start=1):
        experiment_id = f"family-001:candidate:{index}"
        registry.register_experiment(
            ExperimentSpec(
                experiment_id=experiment_id,
                hypothesis=f"candidate {index}",
                dataset=dataset,
                code=ArtifactRef(f"code-{index}", ArtifactType.CODE, "v1", digest),
                universe=_universe(),
                parameters={"feature_digest": digest},
                seed=0,
                metadata={
                    "generated_feature_digest": digest,
                    "program_id": "program-001",
                    "family_id": "family-001",
                },
            )
        )
        experiment_ids.append(experiment_id)
    registry.register_family(
        ExperimentFamily(
            family_id="family-001",
            research_question="which candidate survives development validation?",
            primary_metric="net_sharpe",
            created_at=NOW,
            alpha=0.20,
            metadata={"program_id": "program-001", "dataset_digest": dataset.digest},
        )
    )
    for experiment_id in experiment_ids:
        registry.add_experiment_to_family("family-001", experiment_id, added_at=NOW)
    registry.transition_family("family-001", ExperimentFamilyStatus.FROZEN)
    program_store.reserve_plan(
        AgentMarketProgramPlan(
            program_id="program-001",
            family_id="family-001",
            alpha=0.20,
            variants=digests,
        ),
        task_id="task-001",
        reserved_at=NOW,
    )

    timestamps = tuple(
        (datetime(2024, 1, 2, tzinfo=UTC) + timedelta(days=index)).isoformat()
        for index in range(80)
    )
    axis = np.arange(80, dtype=float)
    returns = {
        experiment_ids[0]: tuple(float(value) for value in 0.018 + 0.002 * np.sin(axis / 3.0)),
        experiment_ids[1]: tuple(float(value) for value in 0.010 + 0.003 * np.cos(axis / 5.0)),
        experiment_ids[2]: tuple(float(value) for value in 0.0002 * np.sin(axis * 1.7)),
    }
    evidence = AgentFamilyDevelopmentEvidence(
        family_id="family-001",
        experiment_order=tuple(sorted(experiment_ids)),
        timestamps=timestamps,
        trial_returns=returns,
        pvalues={
            experiment_ids[0]: 0.001,
            experiment_ids[1]: 0.005,
            experiment_ids[2]: 0.80,
        },
        dataset_digest=dataset.digest,
    )
    report = FormalAgentExperimentFamilyValidator(registry).validate(
        evidence,
        dsr_probability_threshold=0.50,
        pbo_threshold=1.0,
        pbo_blocks=8,
        bootstrap_samples=20,
        seed=0,
    )
    assert report.passed
    strategy = FinalStrategySelector(registry).select(
        program_id="program-001",
        report=report,
        config=AgentMarketResearchConfig(max_candidates=3),
        created_at=NOW + timedelta(minutes=1),
    )
    program_store.freeze_program(
        "program-001",
        actor="test-suite",
        changed_at=NOW + timedelta(minutes=2),
        reason="final strategy frozen",
    )
    return registry, evidence, report, strategy


def test_holdout_must_be_registered_before_research_budget_is_spent(tmp_path) -> None:
    programs = _program_store(tmp_path)
    store = SQLiteSealedHoldoutStore(tmp_path / "holdout.sqlite")
    spec = _holdout_spec()
    store.register_before_research(spec, program_store=programs)
    store.register_before_research(spec, program_store=programs)
    assert store.get(spec.holdout_id) == spec

    programs2 = SQLiteResearchProgramStore(tmp_path / "programs-late.sqlite")
    programs2.register(
        ResearchProgram(
            program_id="program-001",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=6,
            sealed_holdout_id="holdout-001",
        )
    )
    programs2.reserve_plan(
        AgentMarketProgramPlan(
            program_id="program-001",
            family_id="family-late",
            alpha=0.01,
            variants=("a",),
        ),
        task_id="late",
        reserved_at=NOW,
    )
    with pytest.raises(PermissionError, match="before any research budget"):
        SQLiteSealedHoldoutStore(tmp_path / "holdout-late.sqlite").register_before_research(
            spec,
            program_store=programs2,
        )


def test_holdout_identity_is_immutable(tmp_path) -> None:
    programs = _program_store(tmp_path)
    store = SQLiteSealedHoldoutStore(tmp_path / "holdout.sqlite")
    spec = _holdout_spec()
    store.register_before_research(spec, program_store=programs)
    changed = replace(spec, holdout_end=spec.holdout_end + timedelta(days=1))
    with pytest.raises(ValueError, match="immutable"):
        store.register_before_research(changed, program_store=programs)


def test_development_evidence_digest_covers_returns_and_timestamps(tmp_path) -> None:
    programs = _program_store(tmp_path)
    SQLiteSealedHoldoutStore(tmp_path / "holdout.sqlite").register_before_research(
        _holdout_spec(),
        program_store=programs,
    )
    _registry, evidence, _report, _strategy = _formal_research(tmp_path, programs)
    baseline = development_evidence_digest(evidence)
    experiment_id = evidence.experiment_order[0]
    changed_returns = dict(evidence.trial_returns)
    values = list(changed_returns[experiment_id])
    values[0] += 1e-6
    changed_returns[experiment_id] = tuple(values)
    changed = AgentFamilyDevelopmentEvidence(
        family_id=evidence.family_id,
        experiment_order=evidence.experiment_order,
        timestamps=evidence.timestamps,
        trial_returns=changed_returns,
        pvalues=evidence.pvalues,
        dataset_digest=evidence.dataset_digest,
    )
    assert development_evidence_digest(changed) != baseline


def test_holdout_eligibility_seal_binds_strategy_report_evidence_and_holdout(tmp_path) -> None:
    programs = _program_store(tmp_path)
    holdouts = SQLiteSealedHoldoutStore(tmp_path / "holdout.sqlite")
    spec = _holdout_spec()
    holdouts.register_before_research(spec, program_store=programs)
    registry, evidence, report, strategy = _formal_research(tmp_path, programs)

    seal = HoldoutEligibilitySealer(
        registry=registry,
        program_store=programs,
        holdout_store=holdouts,
    ).seal(
        strategy=strategy,
        report=report,
        evidence=evidence,
        created_at=NOW + timedelta(minutes=3),
    )

    assert seal.final_strategy_id == strategy.strategy_id
    assert seal.family_validation_report_id == report.report_id
    assert seal.holdout_spec_digest == spec.spec_digest
    assert seal.development_evidence_digest == development_evidence_digest(evidence)
    assert seal.development_end < spec.holdout_start

    store = SQLiteHoldoutEligibilityStore(tmp_path / "eligibility.sqlite")
    store.register(seal)
    store.register(seal)
    assert store.get_for_program("program-001")["final_strategy_id"] == strategy.strategy_id


def test_holdout_seal_rejects_report_or_development_identity_drift(tmp_path) -> None:
    programs = _program_store(tmp_path)
    holdouts = SQLiteSealedHoldoutStore(tmp_path / "holdout.sqlite")
    holdouts.register_before_research(_holdout_spec(), program_store=programs)
    registry, evidence, report, strategy = _formal_research(tmp_path, programs)
    sealer = HoldoutEligibilitySealer(
        registry=registry,
        program_store=programs,
        holdout_store=holdouts,
    )

    changed_pvalues = dict(evidence.pvalues)
    changed_pvalues[evidence.experiment_order[0]] = 0.002
    changed = AgentFamilyDevelopmentEvidence(
        family_id=evidence.family_id,
        experiment_order=evidence.experiment_order,
        timestamps=evidence.timestamps,
        trial_returns=evidence.trial_returns,
        pvalues=changed_pvalues,
        dataset_digest=evidence.dataset_digest,
    )
    with pytest.raises(ValueError, match="p-values"):
        sealer.seal(
            strategy=strategy,
            report=report,
            evidence=changed,
            created_at=NOW + timedelta(minutes=3),
        )


def test_holdout_seal_rejects_development_overlap(tmp_path) -> None:
    programs = _program_store(tmp_path)
    holdouts = SQLiteSealedHoldoutStore(tmp_path / "holdout.sqlite")
    spec = _holdout_spec()
    holdouts.register_before_research(spec, program_store=programs)
    registry, evidence, report, strategy = _formal_research(tmp_path, programs)
    shifted_timestamps = tuple(
        (spec.holdout_start + timedelta(days=index)).isoformat()
        for index in range(len(evidence.timestamps))
    )
    overlapping = AgentFamilyDevelopmentEvidence(
        family_id=evidence.family_id,
        experiment_order=evidence.experiment_order,
        timestamps=shifted_timestamps,
        trial_returns=evidence.trial_returns,
        pvalues=evidence.pvalues,
        dataset_digest=evidence.dataset_digest,
    )
    with pytest.raises(PermissionError, match="overlaps"):
        HoldoutEligibilitySealer(
            registry=registry,
            program_store=programs,
            holdout_store=holdouts,
        ).seal(
            strategy=strategy,
            report=report,
            evidence=overlapping,
            created_at=NOW + timedelta(minutes=3),
        )


def test_holdout_spec_rejects_invalid_time_order() -> None:
    spec = _holdout_spec()
    with pytest.raises(ValueError, match="windows must satisfy"):
        replace(spec, training_end=spec.holdout_start + timedelta(days=1))
