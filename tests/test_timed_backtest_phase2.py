import math

import pytest

from finagent.backtest import TimedBacktestConfig, TimedEventDrivenBacktestEngine
from finagent.models.alpha import ARAlphaModel
from finagent.models.risk import GARCH11RiskModel
from finagent.portfolio import MeanVarianceConfig, MeanVarianceOptimizer
from finagent.services.execution import TimedSimulatedExchange
from finagent.services.portfolio import StaticRiskGate
from tests.synthetic import make_phase1_adapter


def test_phase2_timed_backtest_never_executes_at_signal_instant():
    adapter, dataset, _, _ = make_phase1_adapter(n=220, seed=41)
    engine = TimedEventDrivenBacktestEngine(
        adapter,
        adapter,
        config=TimedBacktestConfig(
            initial_cash=100_000.0,
            lookback=60,
            rebalance_every=5,
            execution_lag_events=1,
            execution_price_field="open",
        ),
        exchange=TimedSimulatedExchange(slippage_bps=1.0, commission_bps=0.5),
    )
    alpha = ARAlphaModel(order=1, min_observations=50)
    risk = GARCH11RiskModel(min_observations=30, correlation_lookback=50)
    optimizer = MeanVarianceOptimizer(
        MeanVarianceConfig(
            risk_aversion=30.0,
            cash_weight=0.02,
            max_abs_weight=0.8,
            turnover_penalty=0.0005,
        )
    )
    gate = StaticRiskGate(max_gross_exposure=1.0, max_abs_weight=0.8)
    result = engine.run(dataset, alpha, risk, optimizer, gate)
    executed = [point for point in result.points if point.execution is not None]
    assert executed
    assert all(point.execution_at > point.information_at for point in executed)
    assert all(
        fill.executed_at == point.execution_at
        for point in executed
        for fill in point.execution.fills
    )
    assert all(math.isfinite(point.nav) and point.nav > 0 for point in result.points)
    assert result.total_transaction_cost > 0
    assert result.total_return == pytest.approx(result.points[-1].nav / 100_000.0 - 1.0)
    assert result.points[-1].target is None
    assert result.points[-1].execution is None
