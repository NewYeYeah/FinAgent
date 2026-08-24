from datetime import timedelta

import numpy as np
import pytest

from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.models.risk import EWMACovarianceEstimator, GARCH11Estimator, GARCH11RiskModel
from tests.synthetic import bars_from_returns, generate_correlated_returns, make_assets


def test_ewma_covariance_is_symmetric_psd():
    rng = np.random.default_rng(4)
    base = rng.normal(size=(100, 1))
    returns = np.hstack([base + rng.normal(scale=0.2, size=(100, 1)), 0.5 * base + rng.normal(scale=0.3, size=(100, 1))])
    estimator = EWMACovarianceEstimator(decay=0.94, shrinkage=0.1)
    cov = estimator.estimate(returns)
    assert np.allclose(cov, cov.T)
    assert np.min(np.linalg.eigvalsh(cov)) >= -1e-12
    corr = estimator.correlation(returns)
    assert np.allclose(np.diag(corr), 1.0)
    assert np.min(np.linalg.eigvalsh(corr)) >= -1e-10


def test_garch_estimator_returns_stationary_parameters():
    rng = np.random.default_rng(5)
    returns = rng.normal(0.0, 0.01, size=160)
    estimator = GARCH11Estimator(min_observations=30)
    params = estimator.fit(returns)
    assert params.omega > 0
    assert params.alpha >= 0
    assert params.beta >= 0
    assert params.alpha + params.beta < 1
    assert estimator.forecast_variance(returns[-60:], params) > 0


def test_garch_risk_model_emits_full_psd_covariance(now):
    assets = make_assets(2)
    returns = generate_correlated_returns(180, seed=6)
    adapter = InMemoryPriceDataAdapter(
        {
            assets[0]: bars_from_returns(assets[0], returns[:, 0], start=now),
            assets[1]: bars_from_returns(assets[1], returns[:, 1], start=now, start_price=80),
        },
        data_version="risk-v1",
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=assets,
            features=("log_return_1",),
            labels=("forward_log_return_1",),
            splits={
                "train": TimeRange(now, now + timedelta(days=150)),
                "test": TimeRange(now + timedelta(days=150), now + timedelta(days=180)),
            },
        )
    )
    model = GARCH11RiskModel(min_observations=30, correlation_lookback=40)
    model.fit(dataset)
    asof = now + timedelta(days=170)
    window = adapter.feature_window(asof, assets, model.required_features, lookback=60)
    forecast = model.predict(window)
    matrix = np.asarray(
        [[forecast.covariance[(a, b)] for b in assets] for a in assets], dtype=float
    )
    assert np.allclose(matrix, matrix.T)
    assert np.min(np.linalg.eigvalsh(matrix)) >= -1e-10
    for idx, asset in enumerate(assets):
        assert matrix[idx, idx] == pytest.approx(forecast.volatilities[asset] ** 2)
