from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from finagent.domain.research import TimeRange
from finagent.research.adaptive_portfolio_evaluation import (
    conditional_nav_metrics,
    materialize_session_signals,
)
from finagent.research.factor_allocators import AllocatorType, DeterministicFactorAllocator
from finagent.research.factor_performance import (
    FactorDecisionIC,
    FactorPerformanceHistory,
    FactorPerformanceObservation,
    QualityConfig,
    combine_factor_signals,
    fixed_exposure_targets,
    normalize_factor_signal,
)
from finagent.research.market_state import MarketStateRow
from finagent.research.ridge_meta_allocator import RidgeConfig, fit_ridge_meta
from finagent.research.us_a1_factor_graph import (
    FactorGraphSpec,
    FactorInputField,
    FactorNode,
    FactorOperator,
)
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_r3_economics import EconomicPolicy
from tests.test_market_state import market_fixture

START = datetime(2025, 1, 2, tzinfo=UTC)
IDS = ("factor-a", "factor-b")


def session_observations(day, *, ic=((0.8, 0.1), (0.2, 0.9)), net=(0.001, 0.003)):
    date = START + timedelta(days=day)
    result = []
    for factor, values, value in zip(IDS, ic, net, strict=True):
        decisions = tuple(
            FactorDecisionIC(
                date + timedelta(hours=15 + k),
                date + timedelta(hours=16 + k),
                rank_ic,
                p,
                "gmm-fixture",
            )
            for k, (rank_ic, p) in enumerate(zip(values, ((1.0, 0.0), (0.0, 1.0)), strict=True))
        )
        result.append(
            FactorPerformanceObservation(
                factor,
                decisions[0].decision_time,
                date + timedelta(hours=21),
                date.date().isoformat(),
                sum(values) / 2,
                value,
                decisions,
                "source-fixture",
                "session-" + str(day),
            )
        )
    return tuple(result)


def history(days=5):
    return FactorPerformanceHistory(
        tuple(row for day in range(days) for row in session_observations(day))
    )


def allocate(kind, observations, *, day=6, probabilities=None, ridge=None):
    date = START + timedelta(days=day)
    at = date + timedelta(hours=15)
    state = (
        MarketStateRow(
            "gmm-fixture", at - timedelta(minutes=15), at, date.date().isoformat(), probabilities
        )
        if probabilities
        else None
    )
    return DeterministicFactorAllocator(kind, QualityConfig(), ridge).allocate(
        IDS,
        observations,
        as_of=at,
        session_id=date.date().isoformat(),
        session_open=date + timedelta(hours=14, minutes=30),
        market_state=state,
    )


def test_performance_release_rejects_unmatured_and_future_snapshots_are_identical():
    past = history()
    future = session_observations(8)
    cutoff = START + timedelta(days=5)
    with pytest.raises(ValueError, match="before session outcome"):
        past.append(future, as_of=cutoff)
    full = FactorPerformanceHistory(past.observations + future)
    changed = FactorPerformanceHistory(
        past.observations + session_observations(8, ic=((-0.9, -0.9), (0.9, 0.9)), net=(0.9, -0.9))
    )
    assert full.available(as_of=cutoff) == changed.available(as_of=cutoff) == past
    assert full.available(as_of=cutoff).identity == past.identity
    assert past.append(future, as_of=future[0].outcome_available_at) == full
    with pytest.raises(ValueError, match="ordered and unique"):
        full.append(future, as_of=future[0].outcome_available_at)
    with pytest.raises(ValueError, match="precedes covered"):
        replace(future[0], outcome_available_at=future[0].decision_time + timedelta(minutes=1))


def test_normalization_scaling_ties_missing_and_fixed_exposure():
    raw = {"c": 4.0, "b": 1.0, "a": 1.0, "missing": None}
    normalized = normalize_factor_signal(raw)
    assert normalized == {"a": -0.5, "b": -0.5, "c": 1.0}
    assert normalized == normalize_factor_signal(
        {a: x * 1000 if x is not None else None for a, x in raw.items()}
    )
    signals = {
        "factor-a": normalized,
        "factor-b": normalize_factor_signal({"a": 9, "b": 5, "c": 0}),
    }
    combined = combine_factor_signals(signals, {"factor-a": 0.6, "factor-b": 0.4})
    scaled = {
        **signals,
        "factor-a": normalize_factor_signal(
            {a: x * 1000 if x is not None else None for a, x in raw.items()}
        ),
    }
    assert combined == combine_factor_signals(scaled, {"factor-a": 0.6, "factor-b": 0.4})
    policy = EconomicPolicy(minimum_breadth=3, selection_count=2)
    assert fixed_exposure_targets(combined, policy) == fixed_exposure_targets(
        combine_factor_signals(scaled, {"factor-a": 0.6, "factor-b": 0.4}), policy
    )
    assert fixed_exposure_targets({"c": 0.0, "b": 0.0, "a": 0.0}, policy) == {"a": 0.5, "b": 0.5}
    assert normalize_factor_signal({"a": 1.0}) == {}
    with pytest.raises(ValueError, match="finite"):
        normalize_factor_signal({"a": float("nan"), "b": 1})
    with pytest.raises(ValueError, match="sum to one"):
        combine_factor_signals(signals, {"factor-a": 0.0, "factor-b": 0.0})


def test_equal_weight_exactly_ignores_all_history():
    empty = allocate(AllocatorType.EQUAL_WEIGHT, FactorPerformanceHistory())
    assert empty == allocate(AllocatorType.EQUAL_WEIGHT, history(10))
    assert dict(empty.weights) == dict.fromkeys(IDS, 0.5)
    assert empty.history_cutoff is None and empty.fallback_reason is None


def test_graph_missingness_uses_one_common_cross_section_before_ranking():
    assets, *_ = market_fixture()
    damaged = list(assets)
    bars = list(damaged[0].bars)
    bars[10] = replace(bars[10], is_complete=False)
    damaged[0] = replace(damaged[0], bars=tuple(bars))
    node = FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE)
    graphs = (
        FactorGraphSpec(
            (node, FactorNode("rank", FactorOperator.CROSS_SECTION_RANK, ("close",))), "rank"
        ),
        FactorGraphSpec(
            (
                node,
                FactorNode("lag", FactorOperator.LAG, ("close",), lag_bars=1),
                FactorNode("rank", FactorOperator.CROSS_SECTION_RANK, ("lag",)),
            ),
            "rank",
        ),
    )
    compiled = compile_factor_graph_batch(graphs, admit_panel_operators=True)
    frames = materialize_session_signals(
        compiled, tuple(damaged), EconomicPolicy(minimum_breadth=3, selection_count=1)
    )
    for values in frames[11].values():
        assert set(values) == {"A1", "A2", "A3"}
        assert sorted(values.values()) == [-1.0, 0.0, 1.0]


@pytest.mark.parametrize(
    "kind,expected",
    [(AllocatorType.ROLLING_IC, (0.45, 0.55)), (AllocatorType.ROLLING_NET_RETURN, (0.25, 0.75))],
)
def test_rolling_quality_uses_only_previous_completed_sessions(kind, expected):
    past = history()
    first = allocate(kind, past)
    assert tuple(dict(first.weights).values()) == pytest.approx(expected)
    future = session_observations(6, ic=((-1.0, -1.0), (1.0, 1.0)), net=(0.9, -0.9))
    full = FactorPerformanceHistory(past.observations + future)
    assert first == allocate(kind, full)
    # Even at today's closing decision, only sessions completed before open enter.
    allocator = DeterministicFactorAllocator(kind, QualityConfig())
    close = future[0].outcome_available_at
    snapshot = allocator.allocate(
        IDS,
        full,
        as_of=close,
        session_id=future[0].session_id,
        session_open=START + timedelta(days=6, hours=14, minutes=30),
    )
    assert snapshot.history_id == first.history_id
    assert snapshot.weights == first.weights
    assert snapshot.history_cutoff <= snapshot.session_open < snapshot.as_of
    fallback = allocate(kind, history(2))
    assert dict(fallback.weights) == dict.fromkeys(IDS, 0.5)
    assert fallback.fallback_reason == "INSUFFICIENT_OR_NONPOSITIVE_QUALITY"
    negative = FactorPerformanceHistory(
        tuple(
            r
            for d in range(5)
            for r in session_observations(d, ic=((-0.1, -0.1), (-0.2, -0.2)), net=(-0.01, -0.02))
        )
    )
    assert dict(allocate(kind, negative).weights) == dict.fromkeys(IDS, 0.5)


def test_lookback_is_twenty_calendar_sessions_without_extending_for_missing_quality():
    rows = tuple(
        r
        for d in range(25)
        for r in session_observations(
            d, ic=((0.9, 0.9), (0.1, 0.1)) if d < 5 else ((0.1, 0.1), (0.9, 0.9))
        )
    )
    snapshot = allocate(AllocatorType.ROLLING_IC, FactorPerformanceHistory(rows), day=26)
    assert tuple(dict(snapshot.weights).values()) == pytest.approx((0.1, 0.9))
    damaged = tuple(
        replace(r, rank_ic=None, decisions=tuple(replace(d, rank_ic=None) for d in r.decisions))
        if r.factor_id == IDS[0] and r.decision_time >= START + timedelta(days=8)
        else r
        for r in rows
    )
    # Only three valid sessions remain inside the lookback for A. Old valid rows
    # are not pulled back into the window to satisfy minimum_observations.
    snapshot = allocate(AllocatorType.ROLLING_IC, FactorPerformanceHistory(damaged), day=26)
    assert dict(snapshot.weights) == {IDS[0]: 0.0, IDS[1]: 1.0}


def test_regime_one_hot_and_soft_convex_mixture_are_exact_and_causal():
    past = history()
    left = allocate(AllocatorType.REGIME_CONDITIONAL, past, probabilities=(1.0, 0.0))
    right = allocate(AllocatorType.REGIME_CONDITIONAL, past, probabilities=(0.0, 1.0))
    soft = allocate(AllocatorType.REGIME_CONDITIONAL, past, probabilities=(0.25, 0.75))
    assert tuple(dict(left.weights).values()) == pytest.approx((0.8, 0.2))
    assert tuple(dict(right.weights).values()) == pytest.approx((0.1, 0.9))
    assert tuple(dict(soft.weights).values()) == pytest.approx((0.275, 0.725))
    assert soft.fallback_reason is None
    full = FactorPerformanceHistory(past.observations + session_observations(8))
    assert soft == allocate(AllocatorType.REGIME_CONDITIONAL, full, probabilities=(0.25, 0.75))
    changed_future = FactorPerformanceHistory(
        past.observations
        + tuple(
            replace(
                r,
                decisions=tuple(
                    replace(
                        d, state_probabilities=(0.01, 0.99), market_state_model_id="future-model"
                    )
                    for d in r.decisions
                ),
            )
            for r in session_observations(8)
        )
    )
    assert soft == allocate(
        AllocatorType.REGIME_CONDITIONAL, changed_future, probabilities=(0.25, 0.75)
    )
    absent = allocate(AllocatorType.REGIME_CONDITIONAL, past)
    assert absent.fallback_reason == "CURRENT_MARKET_STATE_UNAVAILABLE"
    assert absent.weights == (("factor-a", 0.5), ("factor-b", 0.5))
    date = START + timedelta(days=6)
    bad = MarketStateRow(
        "gmm-fixture",
        date + timedelta(hours=16),
        date + timedelta(hours=16, minutes=15),
        date.date().isoformat(),
        (0.5, 0.5),
    )
    with pytest.raises(ValueError, match="match this decision"):
        DeterministicFactorAllocator(AllocatorType.REGIME_CONDITIONAL, QualityConfig()).allocate(
            IDS,
            past,
            as_of=date + timedelta(hours=15),
            session_id=date.date().isoformat(),
            session_open=date + timedelta(hours=14, minutes=30),
            market_state=bad,
        )


def test_ridge_fits_real_train_only_model_and_never_retrains_on_evaluation():
    rows = tuple(
        row
        for d in range(18)
        for row in session_observations(
            d,
            ic=((0.1 + d * 0.01, 0.1 + d * 0.01), (0.2 + d * 0.008, 0.2 + d * 0.008)),
            net=(0.001 + d * 0.0001, 0.0008 + d * 0.00005),
        )
    )
    full = FactorPerformanceHistory(rows)
    train = TimeRange(START, START + timedelta(days=14))
    model = fit_ridge_meta(IDS, full, train, QualityConfig(), RidgeConfig())
    assert model.fallback_reason is None and model.sample_count >= 8
    assert all(c >= 0 for c in model.coefficients) and max(model.coefficients) > 0
    changed = FactorPerformanceHistory(
        rows[:28]
        + tuple(r for d in range(14, 18) for r in session_observations(d, net=(0.99, -0.99)))
    )
    assert model == fit_ridge_meta(IDS, changed, train, QualityConfig(), RidgeConfig())
    assert model == fit_ridge_meta(
        IDS, full.available(as_of=train.end), train, QualityConfig(), RidgeConfig()
    )
    before = allocate(AllocatorType.RIDGE_META, full, day=14, ridge=model)
    assert before == allocate(AllocatorType.RIDGE_META, changed, day=14, ridge=model)
    assert sum(dict(before.weights).values()) == pytest.approx(1)
    assert before.fallback_reason is None
    negative_model = replace(model, coefficients=(0.0, 0.0), intercept=-1.0)
    negative = allocate(AllocatorType.RIDGE_META, full, day=14, ridge=negative_model)
    assert dict(negative.weights) == dict.fromkeys(IDS, 0.5)
    assert negative.fallback_reason == "INSUFFICIENT_OR_NONPOSITIVE_RIDGE_PREDICTION"
    delayed = FactorPerformanceHistory(
        rows[:26]
        + tuple(
            replace(r, outcome_available_at=r.outcome_available_at + timedelta(days=2))
            for r in rows[26:28]
        )
    )
    assert fit_ridge_meta(IDS, delayed, train, QualityConfig(), RidgeConfig()) == fit_ridge_meta(
        IDS, FactorPerformanceHistory(rows[:26]), train, QualityConfig(), RidgeConfig()
    )
    sparse = fit_ridge_meta(IDS, history(2), train, QualityConfig(), RidgeConfig())
    assert sparse.fallback_reason == "INSUFFICIENT_RIDGE_TRAIN_SAMPLES"
    assert (
        allocate(AllocatorType.RIDGE_META, full, day=14, ridge=sparse).fallback_reason
        == sparse.fallback_reason
    )


def test_conditional_strategy_metrics_use_state_known_at_interval_start():
    states = tuple(
        MarketStateRow(
            "model",
            START + timedelta(minutes=15 * i),
            START + timedelta(minutes=15 * (i + 1)),
            "session",
            p,
        )
        for i, p in enumerate(((1.0, 0.0), (0.0, 1.0), (0.5, 0.5)))
    )
    economics = [{"resolved": True, "ledger": [{"equity": 1.0}, {"equity": 1.1}, {"equity": 0.99}]}]
    result = conditional_nav_metrics(economics, [states], 2)
    assert result["states"]["0"]["mean_nav_change_bps"] == pytest.approx(1000)
    assert result["states"]["1"]["mean_nav_change_bps"] == pytest.approx(-1000)
    changed = states[:2] + (replace(states[2], probabilities=(1.0, 0.0)),)
    assert result == conditional_nav_metrics(economics, [changed], 2)
