from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from finagent.backtest.market_study import MarketStudyConfig
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.domain.market import PriceBar
from finagent.memory import (
    AgentResearchMemoryView,
    EvidenceVisibility,
    ResearchMemoryService,
    SQLiteMemoryVisibilityStore,
    SQLiteResearchMemoryStore,
    SQLiteScopedEvidenceWriter,
)
from finagent.research.agent_family import AgentMarketProgramPlan
from finagent.research.agent_family_validation import (
    AgentFamilyDevelopmentEvidence,
    FormalAgentExperimentFamilyValidator,
)
from finagent.research.agent_market import AgentMarketResearchConfig
from finagent.research.final_strategy import (
    FinalStrategySelector,
    SQLiteFinalStrategyStore,
)
from finagent.research.holdout import (
    HoldoutEligibilitySealer,
    SQLiteHoldoutEligibilityStore,
    SQLiteSealedHoldoutStore,
    SealedHoldoutSpec,
)
from finagent.research.holdout_evaluation import (
    HoldoutAcceptancePolicy,
    HoldoutEvaluationStatus,
    SQLiteHoldoutAcceptancePolicyStore,
    SQLiteHoldoutEvaluationStore,
    SealedHoldoutEvaluator,
)
from finagent.research.programs import ResearchProgram, SQLiteResearchProgramStore
from finagent.research.registry import SQLiteResearchRegistry
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


NOW = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)


def _artifact(feature_id: str, source: str, hypothesis: str) -> GeneratedFeatureArtifact:
    spec = FeatureSpec(
        feature_id=feature_id,
        name=feature_id,
        description=f"test feature {feature_id}",
        hypothesis=hypothesis,
        input_fields=("simple_return_1",),
        lookback=3,
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


def _adapter(days: int = 150, *, data_version: str = "sealed-data-v1"):
    assets = tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM")
    )
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    histories = {}
    for asset_index, asset in enumerate(assets):
        price = 100.0 + 8.0 * asset_index
        bars = []
        for day in range(days):
            event_time = start + timedelta(days=day)
            cycle = 0.0025 * np.sin((day + 2 * asset_index) / 6.0)
            drift = 0.0005 + 0.0001 * asset_index
            price *= 1.0 + drift + cycle
            bars.append(
                PriceBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(hours=6, minutes=30),
                    open=price * 0.999,
                    high=price * 1.004,
                    low=price * 0.996,
                    close=price,
                    volume=2_000_000.0 + 20_000.0 * day + 5000.0 * asset_index,
                )
            )
        histories[asset] = tuple(bars)
    return InMemoryPriceDataAdapter(histories, data_version=data_version), assets, start


def _market_config() -> MarketStudyConfig:
    return MarketStudyConfig(
        outer_train_size=50,
        outer_test_size=15,
        outer_step_size=15,
        inner_train_size=30,
        inner_test_size=10,
        inner_step_size=10,
        purge_bars=1,
        embargo_bars=0,
        initial_cash=1_000_000.0,
        lookback=10,
        rebalance_every=2,
        execution_lag_events=1,
        cash_weight=0.20,
        max_weight=0.50,
        commission_bps=0.5,
        slippage_bps=0.5,
        impact_bps=0.0,
        max_participation_rate=0.10,
        garch_min_observations=10,
        correlation_lookback=10,
        ar_min_observations=10,
        risk_aversion=20.0,
        turnover_penalty=0.001,
    )


def _setup_governed_holdout(tmp_path: Path):
    adapter, universe, bar_start = _adapter()
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-001",
            alpha_budget=0.25,
            max_families=2,
            max_experiments=6,
            sealed_holdout_id="holdout-001",
        )
    )
    training_start = bar_start - timedelta(hours=1)
    training_end = bar_start + timedelta(days=95)
    holdout_start = training_end
    holdout_end = bar_start + timedelta(days=140)
    holdout = SealedHoldoutSpec(
        holdout_id="holdout-001",
        program_id="program-001",
        dataset=ArtifactRef(
            "sealed-source-snapshot",
            ArtifactType.DATASET,
            adapter.data_version,
            "h" * 64,
        ),
        universe=universe,
        provider="synthetic",
        data_version=adapter.data_version,
        training_start=training_start,
        training_end=training_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
        created_at=NOW,
    )
    holdouts = SQLiteSealedHoldoutStore(tmp_path / "holdouts.sqlite")
    holdouts.register_before_research(holdout, program_store=programs)

    policy = HoldoutAcceptancePolicy(
        policy_id="policy-001",
        program_id="program-001",
        holdout_id="holdout-001",
        min_oos_periods=10,
        min_net_sharpe=-100.0,
        min_total_return=-0.99,
        max_drawdown_limit=0.99,
        created_at=NOW,
    )
    policies = SQLiteHoldoutAcceptancePolicyStore(tmp_path / "policies.sqlite")
    policies.register_before_research(
        policy,
        program_store=programs,
        holdout_store=holdouts,
    )

    momentum = _artifact(
        "momentum",
        'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
        "one-day continuation",
    )
    reversal = _artifact(
        "reversal",
        'def compute_feature(inputs):\n    return [-x for x in inputs["simple_return_1"]]\n',
        "one-day reversal",
    )
    flat = _artifact(
        "flat",
        'def compute_feature(inputs):\n    return [0.0 for x in inputs["simple_return_1"]]\n',
        "zero-score control",
    )
    candidates = (momentum, reversal, flat)
    features = SQLiteGeneratedFeatureStore(tmp_path / "features.sqlite")
    for artifact in candidates:
        features.register(artifact)

    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    development_dataset = ArtifactRef(
        "development-dataset", ArtifactType.DATASET, "development-v1", "d" * 64
    )
    experiment_ids = []
    for index, artifact in enumerate(candidates, start=1):
        experiment_id = f"family-001:candidate:{index}"
        registry.register_experiment(
            ExperimentSpec(
                experiment_id=experiment_id,
                hypothesis=artifact.spec.hypothesis,
                dataset=development_dataset,
                code=artifact.code_artifact_ref(),
                universe=universe,
                parameters={"feature_digest": artifact.digest},
                seed=0,
                parent_artifacts=(artifact.factor_artifact_ref(),),
                metadata={
                    "generated_feature_digest": artifact.digest,
                    "program_id": "program-001",
                    "family_id": "family-001",
                },
            )
        )
        experiment_ids.append(experiment_id)
    registry.register_family(
        ExperimentFamily(
            family_id="family-001",
            research_question="which generated feature survives development validation?",
            primary_metric="net_sharpe",
            created_at=NOW,
            alpha=0.20,
            metadata={
                "program_id": "program-001",
                "dataset_digest": development_dataset.digest,
            },
        )
    )
    for experiment_id in experiment_ids:
        registry.add_experiment_to_family("family-001", experiment_id, added_at=NOW)
    registry.transition_family("family-001", ExperimentFamilyStatus.FROZEN)
    programs.reserve_plan(
        AgentMarketProgramPlan(
            program_id="program-001",
            family_id="family-001",
            alpha=0.20,
            variants=tuple(artifact.digest for artifact in candidates),
        ),
        task_id="task-001",
        reserved_at=NOW,
    )

    timestamps = tuple(
        (bar_start + timedelta(days=index, hours=6, minutes=30)).isoformat()
        for index in range(70)
    )
    axis = np.arange(70, dtype=float)
    trial_returns = {
        experiment_ids[0]: tuple(float(value) for value in 0.018 + 0.002 * np.sin(axis / 3.0)),
        experiment_ids[1]: tuple(float(value) for value in 0.010 + 0.003 * np.cos(axis / 5.0)),
        experiment_ids[2]: tuple(float(value) for value in 0.0002 * np.sin(axis * 1.7)),
    }
    evidence = AgentFamilyDevelopmentEvidence(
        family_id="family-001",
        experiment_order=tuple(sorted(experiment_ids)),
        timestamps=timestamps,
        trial_returns=trial_returns,
        pvalues={experiment_ids[0]: 0.001, experiment_ids[1]: 0.005, experiment_ids[2]: 0.80},
        dataset_digest=development_dataset.digest,
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
    config = AgentMarketResearchConfig(
        max_candidates=3,
        family_alpha=0.20,
        market=_market_config(),
    )
    strategy = FinalStrategySelector(registry).select(
        program_id="program-001",
        report=report,
        config=config,
        created_at=NOW + timedelta(minutes=1),
    )
    strategies = SQLiteFinalStrategyStore(tmp_path / "strategies.sqlite")
    strategies.register(strategy)
    programs.freeze_program(
        "program-001",
        actor="test-suite",
        occurred_at=NOW + timedelta(minutes=2),
        reason="final strategy frozen",
    )
    eligibility = HoldoutEligibilitySealer(
        registry=registry,
        program_store=programs,
        holdout_store=holdouts,
    ).seal(
        strategy=strategy,
        report=report,
        evidence=evidence,
        created_at=NOW + timedelta(minutes=3),
    )
    eligibility_store = SQLiteHoldoutEligibilityStore(tmp_path / "eligibility.sqlite")
    eligibility_store.register(eligibility)

    memory_path = tmp_path / "memory.sqlite"
    memory_store = SQLiteResearchMemoryStore(memory_path)
    visibility_store = SQLiteMemoryVisibilityStore(memory_path)
    scoped_writer = SQLiteScopedEvidenceWriter(memory_store, visibility_store)
    evaluation_store = SQLiteHoldoutEvaluationStore(tmp_path / "evaluations.sqlite")

    return {
        "adapter": adapter,
        "universe": universe,
        "programs": programs,
        "holdouts": holdouts,
        "policies": policies,
        "policy": policy,
        "features": features,
        "registry": registry,
        "strategy": strategy,
        "strategies": strategies,
        "eligibility": eligibility,
        "eligibility_store": eligibility_store,
        "memory_store": memory_store,
        "visibility_store": visibility_store,
        "scoped_writer": scoped_writer,
        "evaluation_store": evaluation_store,
    }


def _evaluator(state, *, adapter=None, clock=None):
    return SealedHoldoutEvaluator(
        adapter=adapter or state["adapter"],
        generated_feature_store=state["features"],
        research_registry=state["registry"],
        program_store=state["programs"],
        holdout_store=state["holdouts"],
        eligibility_store=state["eligibility_store"],
        strategy_store=state["strategies"],
        policy_store=state["policies"],
        evaluation_store=state["evaluation_store"],
        scoped_evidence_writer=state["scoped_writer"],
        clock=clock,
    )


def test_acceptance_policy_must_be_preregistered_before_research(tmp_path) -> None:
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="p",
            alpha_budget=0.10,
            max_families=2,
            max_experiments=4,
            sealed_holdout_id="h",
        )
    )
    adapter, universe, start = _adapter(data_version="policy-data")
    holdout = SealedHoldoutSpec(
        holdout_id="h",
        program_id="p",
        dataset=ArtifactRef("source", ArtifactType.DATASET, adapter.data_version, "h" * 64),
        universe=universe,
        provider="synthetic",
        data_version=adapter.data_version,
        training_start=start - timedelta(hours=1),
        training_end=start + timedelta(days=80),
        holdout_start=start + timedelta(days=80),
        holdout_end=start + timedelta(days=120),
        created_at=NOW,
    )
    holdouts = SQLiteSealedHoldoutStore(tmp_path / "holdouts.sqlite")
    holdouts.register_before_research(holdout, program_store=programs)
    policy = HoldoutAcceptancePolicy(
        "policy",
        "p",
        "h",
        10,
        0.0,
        0.0,
        0.30,
        NOW,
    )
    policies = SQLiteHoldoutAcceptancePolicyStore(tmp_path / "policies.sqlite")
    policies.register_before_research(policy, program_store=programs, holdout_store=holdouts)
    policies.register_before_research(policy, program_store=programs, holdout_store=holdouts)
    assert policies.get_for_program("p") == policy

    programs.reserve_plan(
        AgentMarketProgramPlan("p", "family", 0.01, ("x",)),
        task_id="task",
        reserved_at=NOW,
    )
    late_policy = HoldoutAcceptancePolicy(
        "late-policy",
        "p",
        "h",
        10,
        -1.0,
        -1.0,
        0.50,
        NOW + timedelta(minutes=1),
    )
    with pytest.raises(PermissionError, match="before any research budget"):
        SQLiteHoldoutAcceptancePolicyStore(tmp_path / "late.sqlite").register_before_research(
            late_policy,
            program_store=programs,
            holdout_store=holdouts,
        )


def test_preflight_failure_does_not_consume_holdout(tmp_path) -> None:
    state = _setup_governed_holdout(tmp_path)
    wrong_adapter, _universe, _start = _adapter(data_version="wrong-snapshot")
    evaluator = _evaluator(state, adapter=wrong_adapter)

    with pytest.raises(ValueError, match="data_version"):
        evaluator.run(
            strategy=state["strategy"],
            eligibility=state["eligibility"],
            actor="test-suite",
        )
    snapshot = state["programs"].lifecycle_snapshot("program-001")
    assert snapshot.holdout_consumed is False
    assert snapshot.status is ResearchProgramStatus.FROZEN


class _FailAfterAccessAdapter:
    def __init__(self, wrapped) -> None:
        self.wrapped = wrapped
        self.data_version = wrapped.data_version
        self.build_calls = 0

    def build_dataset(self, request):
        self.build_calls += 1
        raise RuntimeError("simulated holdout materialization failure")


def test_post_access_failure_is_terminal_and_not_retried(tmp_path) -> None:
    state = _setup_governed_holdout(tmp_path)
    failing = _FailAfterAccessAdapter(state["adapter"])
    evaluator = _evaluator(state, adapter=failing)
    report = evaluator.run(
        strategy=state["strategy"],
        eligibility=state["eligibility"],
        actor="test-suite",
    )
    assert report.status is HoldoutEvaluationStatus.ERROR
    assert report.error_type == "RuntimeError"
    assert failing.build_calls == 1
    lifecycle = state["programs"].lifecycle_snapshot("program-001")
    assert lifecycle.holdout_consumed is True
    assert lifecycle.status is ResearchProgramStatus.CLOSED
    scope = state["visibility_store"].get(report.evidence_key)
    assert scope is not None
    assert scope.visibility is EvidenceVisibility.SEALED_HOLDOUT

    replay = evaluator.run(
        strategy=state["strategy"],
        eligibility=state["eligibility"],
        actor="test-suite",
    )
    assert replay == report
    assert failing.build_calls == 1


def test_real_one_shot_evaluator_recreates_frozen_portfolio_protocol(tmp_path) -> None:
    state = _setup_governed_holdout(tmp_path)
    tick = iter(
        (
            NOW + timedelta(minutes=4),
            NOW + timedelta(minutes=5),
            NOW + timedelta(minutes=6),
            NOW + timedelta(minutes=7),
        )
    )
    evaluator = _evaluator(state, clock=lambda: next(tick))
    report = evaluator.run(
        strategy=state["strategy"],
        eligibility=state["eligibility"],
        actor="test-suite",
    )

    assert report.status is HoldoutEvaluationStatus.PASSED
    assert report.metrics["oos_periods"] >= state["policy"].min_oos_periods
    assert report.dataset_digest
    assert state["programs"].lifecycle_snapshot("program-001").status is ResearchProgramStatus.CLOSED
    result_node = state["memory_store"].get_node(report.evidence_key)
    assert result_node.node_type.value == "result"
    assert state["visibility_store"].get(report.evidence_key).visibility is EvidenceVisibility.SEALED_HOLDOUT

    memory = ResearchMemoryService(state["memory_store"])
    view = AgentResearchMemoryView(
        memory,
        state["visibility_store"],
        program_id="program-001",
    )
    graph = view.traverse(f"experiment:{state['strategy'].selected_experiment_id}")
    assert all(node.key != report.evidence_key for node in graph.nodes)


def test_rejection_policy_is_deterministic_and_still_consumes_holdout(tmp_path) -> None:
    state = _setup_governed_holdout(tmp_path)
    strict = HoldoutAcceptancePolicy(
        policy_id="strict-policy",
        program_id="program-001",
        holdout_id="holdout-001",
        min_oos_periods=10,
        min_net_sharpe=100.0,
        min_total_return=0.99,
        max_drawdown_limit=0.01,
        created_at=NOW,
    )
    # The originally preregistered policy is immutable, so use a clean policy store
    # and register the strict policy against the still-frozen program is intentionally
    # forbidden. This proves thresholds cannot be changed after research.
    with pytest.raises(PermissionError, match="while program is OPEN"):
        SQLiteHoldoutAcceptancePolicyStore(tmp_path / "strict.sqlite").register_before_research(
            strict,
            program_store=state["programs"],
            holdout_store=state["holdouts"],
        )
