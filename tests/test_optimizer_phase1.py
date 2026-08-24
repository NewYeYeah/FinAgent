from datetime import timedelta

import pytest

from finagent.domain.forecasts import AlphaForecast, ModelRef, RiskForecast
from finagent.domain.portfolio import PortfolioState
from finagent.portfolio import MeanVarianceConfig, MeanVarianceOptimizer


def test_mean_variance_optimizer_respects_weights(now, assets):
    a, b = assets
    alpha = AlphaForecast(
        asof=now,
        horizon=timedelta(days=1),
        expected_returns={a: 0.01, b: 0.002},
        source=ModelRef("alpha", "1"),
    )
    risk = RiskForecast(
        asof=now,
        horizon=timedelta(days=1),
        volatilities={a: 0.02, b: 0.01},
        covariance={(a, a): 0.0004, (b, b): 0.0001, (a, b): 0.00005, (b, a): 0.00005},
        source=ModelRef("risk", "1"),
    )
    state = PortfolioState(now, "USD", cash=1000.0)
    optimizer = MeanVarianceOptimizer(
        MeanVarianceConfig(risk_aversion=10.0, cash_weight=0.05, max_abs_weight=0.8)
    )
    target = optimizer.optimize(alpha, risk, state)
    assert sum(target.weights.values()) + target.cash_weight == pytest.approx(1.0)
    assert all(0 <= w <= 0.8 for w in target.weights.values())
    assert target.cash_weight == pytest.approx(0.05)
    assert target.weights[a] > target.weights[b]


def test_mean_variance_rejects_mismatched_asof(now, assets):
    a, b = assets
    later = now + timedelta(days=1)
    alpha = AlphaForecast(now, timedelta(days=1), {a: 0.01, b: 0.0}, ModelRef("a", "1"))
    risk = RiskForecast(
        later,
        timedelta(days=1),
        {a: 0.02, b: 0.02},
        {(a, a): 0.0004, (b, b): 0.0004, (a, b): 0.0, (b, a): 0.0},
        ModelRef("r", "1"),
    )
    with pytest.raises(ValueError, match="same asof"):
        MeanVarianceOptimizer().optimize(alpha, risk, PortfolioState(now, "USD", 1000.0))
