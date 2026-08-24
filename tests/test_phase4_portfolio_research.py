from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.forecasts import AlphaForecast, ModelRef, RiskForecast
from finagent.domain.portfolio import PortfolioState
from finagent.domain.research import ResearchSplit
from finagent.models.alpha import AlphaForecastEnsembler, CrossSectionalLinearAlphaCalibrator
from finagent.models.risk import HistoricalRiskForecastBuilder, OASCovarianceEstimator
from finagent.portfolio import (
    ConstrainedMeanVarianceConfig,
    ConstrainedMeanVarianceOptimizer,
    ConstraintCompiler,
    GroupExposureLimit,
    PortfolioBenchmarkSuite,
    PortfolioConstraintSet,
    evaluate_portfolio_target,
)

UTC = timezone.utc


def _assets(n: int = 4) -> tuple[AssetId, ...]:
    return tuple(
        AssetId(
            symbol=f"A{idx}",
            asset_type=AssetType.EQUITY,
            venue="XNAS",
            currency="USD",
        )
        for idx in range(n)
    )


def _calibration_split(n_periods: int = 24) -> ResearchSplit:
    assets = _assets()
    start = datetime(2026, 1, 1, 16, tzinfo=UTC)
    timestamps = tuple(start + timedelta(days=idx) for idx in range(n_periods))
    feature = np.zeros((n_periods, len(assets), 1), dtype=float)
    labels = np.zeros((n_periods, len(assets), 1), dtype=float)
    base = np.asarray([-1.5, -0.4, 0.6, 1.8], dtype=float)
    for row in range(n_periods):
        values = base + 0.05 * np.sin(row + np.arange(len(assets)))
        z = (values - values.mean()) / values.std(ddof=0)
        feature[row, :, 0] = values
        labels[row, :, 0] = 0.001 + 0.006 * z
    return ResearchSplit(
        timestamps=timestamps,
        assets=assets,
        feature_names=("generated:quality",),
        label_names=("forward_simple_return_1",),
        feature_values=feature,
        label_values=labels,
    )


def _forecast_inputs():
    assets = _assets()
    asof = datetime(2026, 3, 1, 16, tzinfo=UTC)
    horizon = timedelta(days=1)
    alpha = AlphaForecast(
        asof=asof,
        horizon=horizon,
        expected_returns={
            assets[0]: 0.010,
            assets[1]: 0.006,
            assets[2]: 0.003,
            assets[3]: 0.001,
        },
        source=ModelRef("alpha", "test"),
    )
    covariance_matrix = np.asarray(
        [
            [0.00016, 0.00003, 0.00001, 0.00001],
            [0.00003, 0.00009, 0.00002, 0.00001],
            [0.00001, 0.00002, 0.00004, 0.00001],
            [0.00001, 0.00001, 0.00001, 0.000025],
        ],
        dtype=float,
    )
    risk = RiskForecast(
        asof=asof,
        horizon=horizon,
        volatilities={
            asset: float(np.sqrt(covariance_matrix[idx, idx]))
            for idx, asset in enumerate(assets)
        },
        covariance={
            (left, right): float(covariance_matrix[i, j])
            for i, left in enumerate(assets)
            for j, right in enumerate(assets)
        },
        source=ModelRef("risk", "test"),
    )
    state = PortfolioState(asof=asof, base_currency="USD", cash=1000.0)
    return assets, alpha, risk, state


def test_cross_sectional_calibrator_recovers_positive_return_mapping():
    split = _calibration_split()
    calibrator = CrossSectionalLinearAlphaCalibrator(min_periods=10)
    result = calibrator.fit(
        split,
        feature_name="generated:quality",
        label_name="forward_simple_return_1",
    )
    assert result.slope == pytest.approx(0.006, rel=0.03)
    assert result.intercept == pytest.approx(0.001, abs=1e-8)
    assert result.r_squared > 0.99
    assert result.n_periods == split.n_times


def test_cross_sectional_calibrator_emits_typed_alpha_forecast():
    split = _calibration_split()
    calibrator = CrossSectionalLinearAlphaCalibrator(min_periods=10)
    calibrator.fit(
        split,
        feature_name="generated:quality",
        label_name="forward_simple_return_1",
    )
    scores = {asset: float(idx) for idx, asset in enumerate(split.assets)}
    forecast = calibrator.forecast(
        asof=datetime(2026, 2, 1, 16, tzinfo=UTC),
        horizon=timedelta(days=1),
        scores=scores,
    )
    ordered = [forecast.expected_returns[asset] for asset in split.assets]
    assert ordered == sorted(ordered)
    assert set(forecast.uncertainty) == set(split.assets)


def test_alpha_ensemble_normalizes_research_weights_and_combines_uncertainty():
    assets, alpha, _, _ = _forecast_inputs()
    second = AlphaForecast(
        asof=alpha.asof,
        horizon=alpha.horizon,
        expected_returns={asset: 0.5 * alpha.expected_returns[asset] for asset in assets},
        uncertainty={asset: 0.02 for asset in assets},
        source=ModelRef("second", "test"),
    )
    first = AlphaForecast(
        asof=alpha.asof,
        horizon=alpha.horizon,
        expected_returns=alpha.expected_returns,
        uncertainty={asset: 0.01 for asset in assets},
        source=alpha.source,
    )
    result = AlphaForecastEnsembler().combine((first, second), (2.0, 1.0))
    assert result.normalized_weights == pytest.approx((2 / 3, 1 / 3))
    assert result.forecast.expected_returns[assets[0]] == pytest.approx(0.0083333333333)
    assert result.forecast.uncertainty[assets[0]] > 0


def test_quality_weights_ignore_scores_below_floor():
    weights = AlphaForecastEnsembler.quality_weights((0.2, 0.0, 0.4), floor=0.1)
    assert weights[1] == 0.0
    assert sum(weights) == pytest.approx(1.0)
    assert weights[2] > weights[0]


def test_oas_covariance_is_psd_and_reports_bounded_shrinkage():
    rng = np.random.default_rng(42)
    common = rng.normal(0.0, 0.01, size=120)
    returns = np.column_stack(
        [common + rng.normal(0.0, scale, size=120) for scale in (0.004, 0.006, 0.008, 0.010)]
    )
    result = OASCovarianceEstimator().estimate_with_diagnostics(returns)
    assert 0.0 <= result.shrinkage <= 1.0
    assert result.n_observations == 120
    assert np.min(np.linalg.eigvalsh(result.covariance)) >= -1e-12
    assert result.covariance.flags.writeable is False


def test_historical_risk_builder_emits_consistent_risk_forecast():
    assets = _assets()
    rng = np.random.default_rng(9)
    returns = rng.normal(0.0, 0.01, size=(80, len(assets)))
    forecast = HistoricalRiskForecastBuilder().build(
        asof=datetime(2026, 3, 1, 16, tzinfo=UTC),
        horizon=timedelta(days=1),
        assets=assets,
        returns=returns,
    )
    assert set(forecast.volatilities) == set(assets)
    for asset in assets:
        assert forecast.covariance[(asset, asset)] == pytest.approx(
            forecast.volatilities[asset] ** 2
        )
    assert float(forecast.metadata["shrinkage"]) >= 0.0


def test_constraint_compiler_checks_asset_group_gross_and_turnover_limits():
    assets = _assets()
    policy = PortfolioConstraintSet(
        max_weight=0.4,
        gross_limit=1.0,
        turnover_limit=0.6,
        group_membership={assets[0]: "g1", assets[1]: "g1", assets[2]: "g2", assets[3]: "g2"},
        group_limits={
            "g1": GroupExposureLimit("g1", 0.45, 0.55),
            "g2": GroupExposureLimit("g2", 0.45, 0.55),
        },
    )
    compiled = ConstraintCompiler().compile(
        assets,
        current_weights=np.zeros(len(assets)),
        policy=policy,
    )
    assert compiled.check(np.asarray([0.3, 0.2, 0.25, 0.25])) == ()
    failures = compiled.check(np.asarray([0.4, 0.3, 0.15, 0.15]))
    assert "group_max:g1" in failures
    assert "group_min:g2" in failures


def test_constrained_mean_variance_respects_group_and_asset_limits():
    assets, alpha, risk, state = _forecast_inputs()
    policy = PortfolioConstraintSet(
        max_weight=0.4,
        gross_limit=1.0,
        group_membership={assets[0]: "growth", assets[1]: "growth", assets[2]: "def", assets[3]: "def"},
        group_limits={
            "growth": GroupExposureLimit("growth", 0.4, 0.55),
            "def": GroupExposureLimit("def", 0.45, 0.6),
        },
    )
    optimizer = ConstrainedMeanVarianceOptimizer(
        policy,
        ConstrainedMeanVarianceConfig(risk_aversion=4.0, turnover_cost_bps=5.0),
    )
    target = optimizer.optimize(alpha, risk, state)
    assert sum(target.weights.values()) == pytest.approx(1.0)
    assert target.gross_exposure <= 1.0 + 1e-7
    assert max(target.weights.values()) <= 0.4 + 2e-6
    growth = target.weights[assets[0]] + target.weights[assets[1]]
    assert 0.4 - 2e-6 <= growth <= 0.55 + 2e-6


def test_portfolio_benchmark_suite_compares_four_reference_constructors():
    _, alpha, risk, state = _forecast_inputs()
    suite = PortfolioBenchmarkSuite.reference_suite(
        constraints=PortfolioConstraintSet(max_weight=0.6, gross_limit=1.0),
        transaction_cost_bps=7.5,
        risk_aversion=5.0,
    )
    results = suite.run(alpha, risk, state)
    assert {result.name for result in results} == {
        "equal_weight",
        "minimum_variance",
        "risk_parity",
        "mean_variance",
    }
    for result in results:
        assert result.target.gross_exposure == pytest.approx(1.0, abs=1e-6)
        assert result.metrics.expected_net_return <= result.metrics.expected_return + 1e-15
        assert result.metrics.volatility >= 0.0


def test_benchmark_transaction_cost_penalizes_turnover():
    _, alpha, risk, state = _forecast_inputs()
    suite = PortfolioBenchmarkSuite.reference_suite(transaction_cost_bps=10.0)
    result = next(item for item in suite.run(alpha, risk, state) if item.name == "equal_weight")
    zero_cost = evaluate_portfolio_target(result.target, alpha, risk, state, transaction_cost_bps=0.0)
    assert result.metrics.turnover > 0.0
    assert result.metrics.expected_net_return < zero_cost.expected_net_return


def test_phase4_chain_calibration_ensemble_risk_and_portfolio_suite():
    split = _calibration_split()
    calibrator = CrossSectionalLinearAlphaCalibrator(min_periods=10)
    calibrator.fit(
        split,
        feature_name="generated:quality",
        label_name="forward_simple_return_1",
    )
    asof = datetime(2026, 4, 1, 16, tzinfo=UTC)
    horizon = timedelta(days=1)
    scores = {asset: float(idx) for idx, asset in enumerate(split.assets)}
    calibrated = calibrator.forecast(asof=asof, horizon=horizon, scores=scores)
    conservative = AlphaForecast(
        asof=asof,
        horizon=horizon,
        expected_returns={asset: 0.5 * calibrated.expected_returns[asset] for asset in split.assets},
        source=ModelRef("conservative", "test"),
    )
    alpha = AlphaForecastEnsembler().combine(
        (calibrated, conservative),
        AlphaForecastEnsembler.quality_weights((0.8, 0.4)),
    ).forecast
    rng = np.random.default_rng(123)
    history = rng.normal(0.0, 0.01, size=(100, len(split.assets)))
    risk = HistoricalRiskForecastBuilder().build(
        asof=asof,
        horizon=horizon,
        assets=split.assets,
        returns=history,
    )
    state = PortfolioState(asof=asof, base_currency="USD", cash=1000.0)
    results = PortfolioBenchmarkSuite.reference_suite().run(alpha, risk, state)
    assert len(results) == 4
    assert all(result.target.asof == asof for result in results)
