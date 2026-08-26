from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.agents import AgentTask
from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamilyStatus
from finagent.domain.experiments import (
    ArtifactRef,
    ArtifactType,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
)
from finagent.research import (
    AgentMarketExperimentFamilyBridge,
    ResearchProgram,
    SQLiteResearchProgramStore,
    SQLiteResearchRegistry,
)
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


NOW = datetime(2026, 8, 26, 4, 0, tzinfo=UTC)


def _feature(feature_id: str, *, reverse: bool = False) -> GeneratedFeatureArtifact:
    spec = FeatureSpec(
        feature_id=feature_id,
        name=feature_id,
        description=f"test feature {feature_id}",
        hypothesis=(
            "short-horizon reversal survives costs"
            if reverse
            else "short-horizon continuation survives costs"
        ),
        input_fields=("simple_return_1",),
        lookback=3,
    )
    source = (
        'def compute_feature(inputs):\n    return [-x for x in inputs["simple_return_1"]]\n'
        if reverse
        else 'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n'
    )
    validator = FeatureCodeValidator()
    validation = validator.validate(source)
    smoke = LocalFeatureSandbox(validator=validator).run(
        FeatureSandboxRequest(
            spec,
            source,
            {"simple_return_1": [0.01, -0.02, 0.03]},
        )
    )
    return GeneratedFeatureArtifact(
        spec=spec,
        source=source,
        validation=validation,
        generated_at=NOW,
        generator_id="unit-test",
        smoke_output_digest=smoke.output_digest,
    )


def _universe() -> tuple[AssetId, ...]:
    return tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM", "DIA")
    )


def _experiment(
    experiment_id: str = "exp-immutable",
    *,
    dataset_digest: str = "a" * 64,
    order: int = 1,
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        hypothesis="pre-registered signal",
        dataset=ArtifactRef("dataset", ArtifactType.DATASET, "v1", dataset_digest),
        code=ArtifactRef("code", ArtifactType.CODE, "v1", "b" * 64),
        universe=_universe(),
        parameters={"order": order},
        seed=7,
    )


def test_experiment_identity_is_immutable_and_exact_reregistration_is_idempotent(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    spec = _experiment()
    registry.register_experiment(spec)
    registry.register_experiment(spec)
    assert registry.get_experiment(spec.experiment_id).fingerprint == spec.fingerprint

    with pytest.raises(ValueError, match="immutable"):
        registry.register_experiment(_experiment(dataset_digest="c" * 64))
    with pytest.raises(ValueError, match="immutable"):
        registry.register_experiment(_experiment(order=2))


def test_run_cannot_be_rebound_and_result_cannot_be_rewritten(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    first_spec = _experiment("exp-a")
    second_spec = _experiment("exp-b", dataset_digest="c" * 64)
    registry.register_experiment(first_spec)
    registry.register_experiment(second_spec)

    run = ExperimentRun(
        run_id="run-immutable",
        spec_fingerprint=first_spec.fingerprint,
        status=ExperimentRunStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW,
    )
    registry.register_run(run)
    registry.register_run(run)
    with pytest.raises(ValueError, match="cannot be rebound"):
        registry.register_run(
            ExperimentRun(
                run_id=run.run_id,
                spec_fingerprint=second_spec.fingerprint,
                status=ExperimentRunStatus.SUCCEEDED,
                started_at=NOW,
                finished_at=NOW,
            )
        )

    result = ExperimentResult(run.run_id, {"net_sharpe": 0.75}, True)
    registry.register_result(result)
    registry.register_result(result)
    with pytest.raises(ValueError, match="immutable"):
        registry.register_result(ExperimentResult(run.run_id, {"net_sharpe": 1.50}, True))
    assert registry.get_result(run.run_id).metrics["net_sharpe"] == pytest.approx(0.75)


def test_agent_candidate_family_is_budgeted_registered_and_frozen_before_evaluation(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-agent",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=4,
        )
    )
    task = AgentTask("task-agent", "test two bounded generated factors", NOW)
    candidates = (_feature("momentum"), _feature("reversal", reverse=True))
    dataset = AgentMarketExperimentFamilyBridge.market_dataset_artifact(
        provider="alpaca",
        data_version="us-etf-v1",
        normalized_digest="d" * 64,
        uri="file:///immutable/alpaca/bars.csv",
    )
    bridge = AgentMarketExperimentFamilyBridge(registry)

    prepared = bridge.prepare(
        program_store=programs,
        task=task,
        program_id="program-agent",
        family_id="family-agent",
        candidates=candidates,
        dataset=dataset,
        universe=_universe(),
        primary_metric="net_sharpe",
        alpha=0.05,
        provider="alpaca",
    )

    budget = programs.budget_snapshot("program-agent")
    assert budget.family_count == 1
    assert budget.experiment_count == 2
    assert prepared.registration.status is ExperimentFamilyStatus.FROZEN
    family = registry.get_family("family-agent")
    assert family.status is ExperimentFamilyStatus.FROZEN
    assert family.metadata["program_id"] == "program-agent"
    assert family.metadata["dataset_digest"] == "d" * 64

    members = registry.family_members("family-agent")
    assert len(members) == 2
    assert set(prepared.registration.candidate_experiments) == {
        candidate.digest for candidate in candidates
    }
    for candidate in candidates:
        experiment_id = prepared.registration.candidate_experiments[candidate.digest]
        spec = registry.get_experiment(experiment_id)
        assert spec.dataset == dataset
        assert spec.code.digest == candidate.digest
        assert spec.universe == _universe()
        assert spec.metadata["generated_feature_digest"] == candidate.digest
        assert spec.metadata["program_id"] == "program-agent"


def test_repeated_preparation_is_exactly_idempotent_and_cannot_expand_frozen_family(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-agent",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=6,
        )
    )
    task = AgentTask("task-agent", "test bounded generated factors", NOW)
    candidates = (_feature("momentum"), _feature("reversal", reverse=True))
    dataset = AgentMarketExperimentFamilyBridge.market_dataset_artifact(
        provider="alpaca",
        data_version="us-etf-v1",
        normalized_digest="d" * 64,
    )
    bridge = AgentMarketExperimentFamilyBridge(registry)
    kwargs = dict(
        program_store=programs,
        task=task,
        program_id="program-agent",
        family_id="family-agent",
        candidates=candidates,
        dataset=dataset,
        universe=_universe(),
        primary_metric="net_sharpe",
        alpha=0.05,
        provider="alpaca",
    )
    first = bridge.prepare(**kwargs)
    second = bridge.prepare(**kwargs)
    assert second.reservation == first.reservation
    assert second.registration.candidate_experiments == first.registration.candidate_experiments
    assert programs.budget_snapshot("program-agent").experiment_count == 2
    assert len(registry.family_members("family-agent")) == 2

    changed = (*candidates, _feature("third"))
    with pytest.raises(ValueError, match="different plan"):
        bridge.prepare(**{**kwargs, "candidates": changed})
    assert len(registry.family_members("family-agent")) == 2


def test_cross_provider_verification_preserves_primary_experiment_dataset(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-agent",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=4,
        )
    )
    task = AgentTask("task-agent", "cross-provider validation of frozen family", NOW)
    candidates = (_feature("momentum"), _feature("reversal", reverse=True))
    bridge = AgentMarketExperimentFamilyBridge(registry)
    primary = bridge.market_dataset_artifact(
        provider="alpaca",
        data_version="alpaca-v1",
        normalized_digest="a" * 64,
    )
    secondary = bridge.market_dataset_artifact(
        provider="akshare",
        data_version="akshare-v1",
        normalized_digest="b" * 64,
    )
    bridge.prepare(
        program_store=programs,
        task=task,
        program_id="program-agent",
        family_id="family-agent",
        candidates=candidates,
        dataset=primary,
        universe=_universe(),
        primary_metric="net_sharpe",
        alpha=0.05,
        provider="alpaca",
    )

    verified = bridge.ensure_frozen_family(
        task=task,
        program_id="program-agent",
        family_id="family-agent",
        candidates=candidates,
        dataset=secondary,
        universe=_universe(),
        primary_metric="net_sharpe",
        alpha=0.05,
        provider="akshare",
        require_existing=True,
    )
    assert verified.dataset == primary
    for experiment_id in verified.candidate_experiments.values():
        assert registry.get_experiment(experiment_id).dataset == primary


def test_replay_requires_existing_formal_family_and_candidate_identity_must_match(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    bridge = AgentMarketExperimentFamilyBridge(registry)
    task = AgentTask("task-agent", "replay formal family", NOW)
    candidates = (_feature("momentum"), _feature("reversal", reverse=True))
    dataset = bridge.market_dataset_artifact(
        provider="alpaca",
        data_version="alpaca-v1",
        normalized_digest="a" * 64,
    )
    with pytest.raises(KeyError, match="must already exist"):
        bridge.ensure_frozen_family(
            task=task,
            program_id="program-agent",
            family_id="missing-family",
            candidates=candidates,
            dataset=dataset,
            universe=_universe(),
            primary_metric="net_sharpe",
            alpha=0.05,
            provider="alpaca",
            require_existing=True,
        )

    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-agent",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=4,
        )
    )
    bridge.prepare(
        program_store=programs,
        task=task,
        program_id="program-agent",
        family_id="family-agent",
        candidates=candidates,
        dataset=dataset,
        universe=_universe(),
        primary_metric="net_sharpe",
        alpha=0.05,
        provider="alpaca",
    )
    with pytest.raises(ValueError, match="membership does not match"):
        bridge.ensure_frozen_family(
            task=task,
            program_id="program-agent",
            family_id="family-agent",
            candidates=(candidates[0], _feature("different")),
            dataset=dataset,
            universe=_universe(),
            primary_metric="net_sharpe",
            alpha=0.05,
            provider="alpaca",
            require_existing=True,
        )
