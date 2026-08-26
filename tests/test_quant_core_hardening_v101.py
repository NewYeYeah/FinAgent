from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from finagent.agents import ExperimentVariant, ResearchBudget, ResearchPlan, ScriptedResearchAgent
from finagent.agents.generated_features import FeatureSpec
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.forecasts import ModelRef
from finagent.domain.market import MarketSnapshot, PriceBar
from finagent.domain.metrics import MetricObjective
from finagent.domain.portfolio import PortfolioState, PortfolioTarget, RiskDecision, RiskStatus
from finagent.domain.research import ResearchDataset, ResearchSplit, TimeRange
from finagent.domain.trading import TradeActivity
from finagent.domain.universe import ScheduledUniverseProvider
from finagent.models.alpha import (
    cross_sectional_zscore,
    momentum,
    neutralize_linear,
    short_term_reversal,
)
from finagent.research import ResearchProgram, SQLiteResearchProgramStore
from finagent.research.generated_feature_eval import (
    GeneratedFeatureEvaluationConfig,
    evaluate_generated_feature_dataset,
)
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox
from finagent.services.portfolio import OrderPlanner


def _assets() -> tuple[AssetId, ...]:
    return tuple(AssetId(symbol) for symbol in ("AAA", "BBB", "CCC"))


def _dataset(
    *,
    eligibility=None,
    missing_first_label: bool = False,
    unrealized_last_period: bool = False,
) -> ResearchDataset:
    assets = _assets()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    timestamps = tuple(start + timedelta(days=i) for i in range(3))
    features = np.asarray(
        [
            [[-1.0], [0.0], [1.0]],
            [[-0.5], [0.0], [0.5]],
            [[-0.2], [0.0], [0.2]],
        ],
        dtype=float,
    )
    labels = np.asarray(
        [
            [[-0.01], [0.0], [0.01]],
            [[-0.02], [0.0], [0.02]],
            [[-0.01], [0.0], [0.01]],
        ],
        dtype=float,
    )
    if missing_first_label:
        labels[0, 2, 0] = np.nan
    if unrealized_last_period:
        labels[-1, :, 0] = np.nan
    if eligibility is None:
        eligibility = np.ones((3, 3), dtype=bool)
    split = ResearchSplit(
        timestamps=timestamps,
        assets=assets,
        feature_names=("generated:test",),
        label_names=("forward_simple_return_1",),
        feature_values=features,
        label_values=labels,
        eligibility_mask=eligibility,
    )
    return ResearchDataset(
        artifact=ArtifactRef("ds", ArtifactType.DATASET, "v1", "abc"),
        universe=assets,
        features=("generated:test",),
        labels=("forward_simple_return_1",),
        splits={"test": TimeRange(start, start + timedelta(days=4))},
        panels={"test": split},
    )


def test_forward_label_missingness_cannot_silently_change_formation_universe():
    dataset = _dataset(missing_first_label=True)
    with pytest.raises(ValueError, match="missing realized forward return"):
        evaluate_generated_feature_dataset(
            dataset,
            feature_digest="feature",
            config=GeneratedFeatureEvaluationConfig(min_periods=2),
        )


def test_fully_unrealized_cross_section_is_skipped_as_horizon_boundary():
    dataset = _dataset(unrealized_last_period=True)
    trace = evaluate_generated_feature_dataset(
        dataset,
        feature_digest="feature",
        config=GeneratedFeatureEvaluationConfig(min_periods=2),
    )
    assert len(trace.net_returns) == 2
    assert trace.metrics["evaluated_periods"] == pytest.approx(2.0)
    assert trace.metrics["unrealized_boundary_periods"] == pytest.approx(1.0)


def test_pit_eligibility_not_future_label_controls_formation():
    eligibility = np.ones((3, 3), dtype=bool)
    eligibility[0, 2] = False
    dataset = _dataset(eligibility=eligibility, missing_first_label=True)
    trace = evaluate_generated_feature_dataset(
        dataset,
        feature_digest="feature",
        config=GeneratedFeatureEvaluationConfig(min_periods=2),
    )
    assert len(trace.net_returns) >= 2
    assert trace.metrics["coverage"] <= 1.0


def test_trade_activity_distinguishes_gross_and_one_way_turnover():
    activity = TradeActivity.from_weights([0.5, 0.5], [0.6, 0.4])
    assert activity.gross_traded_weight == pytest.approx(0.2)
    assert activity.one_way_turnover == pytest.approx(0.1)
    assert activity.linear_cost_fraction(10.0) == pytest.approx(0.0002)


def test_generic_order_planner_fails_closed_for_derivative_semantics():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    future = AssetId("ES", asset_type=AssetType.FUTURE, venue="CME", currency="USD")
    bar = PriceBar(
        event_time=now,
        available_at=now,
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
    )
    snapshot = MarketSnapshot(now, {future: bar}, "test-v1")
    state = PortfolioState(now, "USD", 10_000.0)
    target = PortfolioTarget(
        now,
        {future: 1.0},
        0.0,
        ModelRef("test", "1"),
    )
    approved = RiskDecision(RiskStatus.APPROVE, checked_at=now)

    with pytest.raises(NotImplementedError, match="supports only EQUITY/ETF"):
        OrderPlanner().plan(target, state, snapshot, approved)


def test_metric_direction_supports_minimize_primary_and_maximize_tie():
    primary = {
        "comparisons": [
            {"experiment_id": "a", "value": 0.20},
            {"experiment_id": "b", "value": 0.10},
        ]
    }
    selection = ScriptedResearchAgent._select_winner(
        primary,
        None,
        primary_objective=MetricObjective.MINIMIZE,
    )
    assert selection.experiment_id == "b"

    tied = {
        "comparisons": [
            {"experiment_id": "a", "value": 1.0},
            {"experiment_id": "b", "value": 1.0},
        ]
    }
    tie = {
        "comparisons": [
            {"experiment_id": "a", "value": 2.0},
            {"experiment_id": "b", "value": 3.0},
        ]
    }
    selection = ScriptedResearchAgent._select_winner(
        tied,
        tie,
        tie_break_objective=MetricObjective.MAXIMIZE,
    )
    assert selection.experiment_id == "b"


def _plan(family_id: str, *, alpha: float, program_id: str) -> ResearchPlan:
    variants = (
        ExperimentVariant("v1", f"{family_id}-e1", {"x": 1}, "test hypothesis"),
    )
    return ResearchPlan(
        plan_id=f"plan-{family_id}",
        planner_version="test",
        family_id=family_id,
        research_question="does this signal work?",
        primary_metric="validation_sharpe",
        template_id="template",
        variants=variants,
        budget=ResearchBudget(max_tool_calls=8, max_experiments=1, max_family_size=1),
        alpha=alpha,
        program_id=program_id,
    )


def test_research_program_controls_cross_family_alpha_spending(tmp_path):
    store = SQLiteResearchProgramStore(tmp_path / "program.db")
    store.register(
        ResearchProgram(
            "program-1",
            alpha_budget=0.05,
            max_families=3,
            max_experiments=3,
            sealed_holdout_id="holdout-1",
        )
    )
    store.reserve_plan(_plan("family-a", alpha=0.03, program_id="program-1"), task_id="task-a")
    snapshot = store.budget_snapshot("program-1")
    assert snapshot.alpha_spent == pytest.approx(0.03)
    with pytest.raises(PermissionError, match="alpha-spending"):
        store.reserve_plan(_plan("family-b", alpha=0.03, program_id="program-1"), task_id="task-b")


def test_sealed_holdout_can_be_consumed_only_once(tmp_path):
    store = SQLiteResearchProgramStore(tmp_path / "program.db")
    store.register(ResearchProgram("p", sealed_holdout_id="holdout"))
    store.freeze_program("p", actor="researcher")
    first = store.consume_sealed_holdout("p", actor="reviewer")
    assert first["holdout_id"] == "holdout"
    with pytest.raises(PermissionError, match="already been consumed"):
        store.consume_sealed_holdout("p", actor="reviewer")


def test_scheduled_universe_uses_only_state_effective_by_asof():
    assets = _assets()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    provider = ScheduledUniverseProvider(
        {
            start: assets[:2],
            start + timedelta(days=10): assets,
        }
    )
    early = provider.snapshot(start + timedelta(days=5), assets)
    late = provider.snapshot(start + timedelta(days=15), assets)
    assert early.mask(assets).tolist() == [True, True, False]
    assert late.mask(assets).tolist() == [True, True, True]


def test_canonical_alpha_primitives_are_deterministic_and_neutralizable():
    assert momentum([100, 102, 105, 110], 3) == pytest.approx(0.10)
    assert short_term_reversal([0.01, 0.02], 2) < 0
    z = cross_sectional_zscore([1.0, 2.0, 3.0])
    assert np.mean(z) == pytest.approx(0.0)
    residual = neutralize_linear([1.0, 2.0, 3.0, 4.0], [[1.0], [2.0], [3.0], [4.0]])
    assert np.nanmax(np.abs(residual)) < 1e-10


def test_local_feature_sandbox_batches_independent_pit_windows():
    spec = FeatureSpec(
        feature_id="batch-test",
        name="Batch Test",
        description="batch smoke test",
        hypothesis="identity",
        input_fields=("close",),
        lookback=2,
    )
    source = 'def compute_feature(inputs):\n    return [v for v in inputs["close"]]\n'
    sandbox = LocalFeatureSandbox()
    requests = (
        FeatureSandboxRequest(spec, source, {"close": [1.0, 2.0]}),
        FeatureSandboxRequest(spec, source, {"close": [10.0, 20.0]}),
    )
    results = sandbox.run_batch(requests)
    assert results[0].values == (1.0, 2.0)
    assert results[1].values == (10.0, 20.0)
