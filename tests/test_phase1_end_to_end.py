import math

from finagent.backtest import BacktestConfig, EventDrivenBacktestEngine
from finagent.models.alpha import ARAlphaModel
from finagent.models.risk import GARCH11RiskModel
from finagent.portfolio import MeanVarianceConfig, MeanVarianceOptimizer
from finagent.services.execution import SimulatedExchange
from finagent.services.portfolio import StaticRiskGate
from tests.synthetic import make_phase1_adapter


def test_phase1_numerical_vertical_slice_runs_end_to_end():
    adapter, dataset, _, _ = make_phase1_adapter(n=220, seed=21)
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
    gate = StaticRiskGate(max_gross_exposure=1.0, max_abs_weight=0.8, min_cash_weight=0.0)
    engine = EventDrivenBacktestEngine(
        adapter,
        config=BacktestConfig(initial_cash=100_000.0, lookback=60, rebalance_every=5),
        exchange=SimulatedExchange(slippage_bps=1.0, commission_bps=0.5),
    )
    result = engine.run(dataset, alpha, risk, optimizer, gate)
    assert len(result.points) == 40
    assert all(math.isfinite(point.nav) and point.nav > 0 for point in result.points)
    assert math.isfinite(result.total_return)
    assert math.isfinite(result.sharpe)
    assert result.total_turnover > 0
    assert result.total_transaction_cost > 0
    assert all(
        point.risk_decision is None or not point.risk_decision.violations
        for point in result.points
    )
