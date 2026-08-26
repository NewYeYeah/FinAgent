from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from finagent.agents import AgentTask
from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.data.ingestion.base import MarketRegion
from finagent.data.ingestion.provider import ALPACA_CAPABILITIES, DataFrequency, ResearchDataRequirement
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamilyStatus
from finagent.research import (
    AgentMarketCandidate,
    AgentMarketResearchConfig,
    AgentMarketResearchResult,
    GovernedAgentMarketResearchRunner,
    ResearchProgram,
    SQLiteResearchProgramStore,
    SQLiteResearchRegistry,
)
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


NOW = datetime(2026, 8, 26, 5, 0, tzinfo=UTC)


def _feature(feature_id: str, *, reverse: bool = False) -> GeneratedFeatureArtifact:
    spec = FeatureSpec(
        feature_id=feature_id,
        name=feature_id,
        description=f"test feature {feature_id}",
        hypothesis="reversal" if reverse else "continuation",
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
        FeatureSandboxRequest(spec, source, {"simple_return_1": [0.01, -0.02, 0.03]})
    )
    return GeneratedFeatureArtifact(
        spec=spec,
        source=source,
        validation=validation,
        generated_at=NOW,
        generator_id="unit-test",
        smoke_output_digest=smoke.output_digest,
    )


def _universe(asset_type: AssetType = AssetType.ETF) -> tuple[AssetId, ...]:
    return tuple(
        AssetId(symbol, asset_type, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ")
    )


class _AssertFrozenEngine:
    def __init__(self, registry: SQLiteResearchRegistry) -> None:
        self.registry = registry
        self.called = False

    def run(self, *, task, candidates, universe, start, end, program_id, family_id):
        self.called = True
        family = self.registry.get_family(family_id)
        assert family.status is ExperimentFamilyStatus.FROZEN
        assert len(self.registry.family_members(family_id)) == len(candidates)
        return AgentMarketResearchResult(
            study_id="study-governed",
            task_id=task.task_id,
            program_id=program_id,
            family_id=family_id,
            provider="alpaca",
            data_version="synthetic-v1",
            universe=tuple(asset.key for asset in universe),
            candidates=tuple(AgentMarketCandidate.from_artifact(item) for item in candidates),
            folds=(),
            aggregate_portfolio_metrics={"oos_periods": 1.0},
            promotion_eligible_folds=0,
        )


def _runner(tmp_path):
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-governed",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=4,
        )
    )
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    runner = GovernedAgentMarketResearchRunner(
        adapter=SimpleNamespace(data_version="synthetic-v1"),
        capabilities=ALPACA_CAPABILITIES,
        requirement=ResearchDataRequirement(
            market=MarketRegion.US_EQUITY,
            frequency=DataFrequency.DAILY,
        ),
        program_store=programs,
        research_registry=registry,
        config=AgentMarketResearchConfig(max_candidates=2),
    )
    return runner, programs, registry


def test_governed_runner_freezes_formal_family_before_numerical_engine(tmp_path):
    runner, programs, registry = _runner(tmp_path)
    spy = _AssertFrozenEngine(registry)
    runner.engine = spy
    task = AgentTask("task-governed", "bounded ETF factor family", NOW)
    candidates = (_feature("momentum"), _feature("reversal", reverse=True))

    result = runner.run(
        task=task,
        candidates=candidates,
        universe=_universe(),
        start=NOW,
        end=NOW + timedelta(days=90),
        program_id="program-governed",
        family_id="family-governed",
    )

    assert spy.called is True
    assert result.family_id == "family-governed"
    assert registry.get_family("family-governed").status is ExperimentFamilyStatus.FROZEN
    assert programs.budget_snapshot("program-governed").experiment_count == 2


def test_preflight_failure_does_not_consume_program_budget(tmp_path):
    runner, programs, registry = _runner(tmp_path)
    task = AgentTask("task-governed", "invalid equity family", NOW)
    candidates = (_feature("momentum"), _feature("reversal", reverse=True))

    with pytest.raises(ValueError, match="ETF-first"):
        runner.run(
            task=task,
            candidates=candidates,
            universe=_universe(AssetType.EQUITY),
            start=NOW,
            end=NOW + timedelta(days=90),
            program_id="program-governed",
            family_id="family-invalid",
        )

    budget = programs.budget_snapshot("program-governed")
    assert budget.family_count == 0
    with pytest.raises(KeyError):
        registry.get_family("family-invalid")


def test_replay_requires_existing_formal_family_before_engine_is_called(tmp_path):
    runner, programs, registry = _runner(tmp_path)
    spy = _AssertFrozenEngine(registry)
    runner.engine = spy
    task = AgentTask("task-governed", "replay bounded ETF factor family", NOW)
    candidates = (_feature("momentum"), _feature("reversal", reverse=True))

    with pytest.raises(KeyError, match="must already exist"):
        runner.run(
            task=task,
            candidates=candidates,
            universe=_universe(),
            start=NOW,
            end=NOW + timedelta(days=90),
            program_id="program-governed",
            family_id="missing-family",
            require_existing_family=True,
        )

    assert spy.called is False
    # Reservation occurs first by design so a failed/attempted replay remains part of
    # the program search ledger, but no formal family or numerical evidence is created.
    assert programs.budget_snapshot("program-governed").experiment_count == 2
    with pytest.raises(KeyError):
        registry.get_family("missing-family")
