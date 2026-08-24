from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.forecasts import AlphaForecast, ModelRef, RiskForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget
from finagent.models.risk import PCAFactorRiskEstimator, PCAFactorRiskForecastBuilder
from finagent.portfolio import (
    ConstrainedMeanVarianceOptimizer,
    ConstraintCompiler,
    DriftRebalancePolicy,
    LinearExposureLimit,
    PortfolioConstraintSet,
    PortfolioScenario,
    PortfolioStressTester,
)

UTC = timezone.utc


def _assets() -> tuple[AssetId, ...]:
    return tuple(
        AssetId(f"S{idx}", AssetType.EQUITY, venue="XNAS", currency="USD")
        for idx in range(4)
    )


def _aligned_forecasts(asof, assets):
    alpha = AlphaForecast(
        asof=asof,
        horizon=timedelta(days=1),
        expected_returns={asset: 0.012 - idx * 0.003 for idx, asset in enumerate(assets)},
        source=ModelRef("alpha", "phase4-test"),
    )
    matrix = np.asarray(
        [
            [0.00010, 0.00002, 0.00001, 0.00000],
            [0.00002, 0.00008, 0.00001, 0.00000],
            [0.00001, 0.00001, 0.00006, 0.00001],
            [0.00000, 0.00000, 0.00001, 0.00005],
        ]
    )
    risk = RiskForecast(
        asof=asof,
        horizon=timedelta(days=1),
        volatilities={asset: float(np.sqrt(matrix[i, i])) for i, asset in enumerate(assets)},
        covariance={
            (left, right): float(matrix[i, j])
            for i, left in enumerate(assets)
            for j, right in enumerate(assets)
        },
        source=ModelRef("risk", "phase4-test"),
    )
    return alpha, risk


def test_pca_factor_risk_produces_low_rank_plus_idiosyncratic_psd_covariance():
    rng = np.random.default_rng(77)
    f1 = rng.normal(0.0, 0.012, 180)
    f2 = rng.normal(0.0, 0.007, 180)
    returns = np.column_stack(
        [
            0.9 * f1 + 0.2 * f2 + rng.normal(0.0, 0.003, 180),
            0.7 * f1 - 0.3 * f2 + rng.normal(0.0, 0.004, 180),
            -0.2 * f1 + 0.8 * f2 + rng.normal(0.0, 0.004, 180),
            0.1 * f1 + 0.5 * f2 + rng.normal(0.0, 0.005, 180),
        ]
    )
    result = PCAFactorRiskEstimator(n_factors=2).estimate(returns)
    assert result.loadings.shape == (4, 2)
    assert result.factor_variances.shape == (2,)
    assert np.all(result.idiosyncratic_variances >= 0)
    assert np.min(np.linalg.eigvalsh(result.covariance)) >= -1e-12
    assert 0.5 < result.explained_variance_ratio <= 1.0


def test_pca_factor_risk_builder_emits_canonical_risk_forecast():
    assets = _assets()
    rng = np.random.default_rng(12)
    returns = rng.normal(0.0, 0.01, size=(100, 4))
    forecast = PCAFactorRiskForecastBuilder(PCAFactorRiskEstimator(n_factors=2)).build(
        asof=datetime(2026, 5, 1, 16, tzinfo=UTC),
        horizon=timedelta(days=1),
        assets=assets,
        returns=returns,
    )
    assert set(forecast.volatilities) == set(assets)
    assert forecast.metadata["n_factors"] == "2"
    assert 0.0 <= float(forecast.metadata["explained_variance_ratio"]) <= 1.0


def test_constraint_compiler_supports_benchmark_active_factor_and_trade_limits():
    assets = _assets()
    benchmark = {asset: 0.25 for asset in assets}
    style = LinearExposureLimit(
        "style",
        {assets[0]: 1.0, assets[1]: 1.0, assets[2]: -1.0, assets[3]: -1.0},
        -0.05,
        0.05,
        relative_to_benchmark=True,
    )
    policy = PortfolioConstraintSet(
        benchmark_weights=benchmark,
        active_weight_bounds={asset: (-0.05, 0.05) for asset in assets},
        trade_weight_limits={asset: 0.05 for asset in assets},
        linear_exposure_limits={"style": style},
    )
    current = np.full(4, 0.25)
    compiled = ConstraintCompiler().compile(assets, current_weights=current, policy=policy)
    candidate = np.asarray([0.28, 0.22, 0.25, 0.25])
    assert compiled.check(candidate) == ()
    assert "asset_bound:equity:XNAS:S0:USD" in compiled.check(np.asarray([0.35, 0.15, 0.25, 0.25]))


def test_constrained_optimizer_respects_liquidity_like_trade_caps_and_active_bounds():
    assets = _assets()
    asof = datetime(2026, 5, 2, 16, tzinfo=UTC)
    alpha, risk = _aligned_forecasts(asof, assets)
    state = PortfolioState(
        asof=asof,
        base_currency="USD",
        cash=0.0,
        positions={asset: 2.5 for asset in assets},
        marks={asset: 100.0 for asset in assets},
    )
    policy = PortfolioConstraintSet(
        benchmark_weights={asset: 0.25 for asset in assets},
        active_weight_bounds={asset: (-0.05, 0.05) for asset in assets},
        trade_weight_limits={asset: 0.05 for asset in assets},
    )
    target = ConstrainedMeanVarianceOptimizer(policy).optimize(alpha, risk, state)
    for asset in assets:
        assert 0.20 - 2e-6 <= target.weights[asset] <= 0.30 + 2e-6
        assert abs(target.weights[asset] - 0.25) <= 0.05 + 2e-6


def test_stress_tester_reports_worst_scenario():
    assets = _assets()
    asof = datetime(2026, 5, 3, 16, tzinfo=UTC)
    target = PortfolioTarget(
        asof=asof,
        weights={asset: 0.25 for asset in assets},
        cash_weight=0.0,
        source=ModelRef("target", "test"),
    )
    report = PortfolioStressTester().evaluate(
        target,
        (
            PortfolioScenario("mild", {asset: -0.01 for asset in assets}),
            PortfolioScenario("crash", {asset: -0.08 - idx * 0.01 for idx, asset in enumerate(assets)}),
        ),
    )
    assert report.worst.name == "crash"
    assert report.worst.portfolio_return < -0.08


def test_drift_rebalance_policy_is_deterministic_and_does_not_rewrite_target():
    assets = _assets()
    asof = datetime(2026, 5, 4, 16, tzinfo=UTC)
    target = PortfolioTarget(
        asof=asof,
        weights={asset: 0.25 for asset in assets},
        cash_weight=0.0,
        source=ModelRef("target", "test"),
    )
    cash_state = PortfolioState(asof=asof, base_currency="USD", cash=1000.0)
    decision = DriftRebalancePolicy(force_turnover=0.25).decide(target, cash_state)
    assert decision.rebalance is True
    assert decision.turnover == pytest.approx(0.5)
    assert decision.reasons == ("force_turnover",)

    invested_state = PortfolioState(
        asof=asof,
        base_currency="USD",
        cash=0.0,
        positions={asset: 2.5 for asset in assets},
        marks={asset: 100.0 for asset in assets},
    )
    stable = DriftRebalancePolicy().decide(target, invested_state)
    assert stable.rebalance is False
    assert stable.turnover == pytest.approx(0.0)
