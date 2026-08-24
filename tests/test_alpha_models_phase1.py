from datetime import timedelta

import numpy as np
import pytest

from finagent.analysis import RandomWalkDiagnostics
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.models.alpha import ARAlphaModel, RandomWalkAlphaModel
from tests.synthetic import bars_from_returns, generate_ar_returns, make_assets


def test_ar_model_recovers_positive_autoregression(now):
    asset = make_assets(1)[0]
    returns = generate_ar_returns(180, phi=0.55, seed=13)
    adapter = InMemoryPriceDataAdapter(
        {asset: bars_from_returns(asset, returns, start=now)}, data_version="ar-v1"
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=(asset,),
            features=("log_return_1",),
            labels=("forward_log_return_1",),
            splits={
                "train": TimeRange(now, now + timedelta(days=150)),
                "test": TimeRange(now + timedelta(days=150), now + timedelta(days=180)),
            },
        )
    )
    model = ARAlphaModel(order=1, min_observations=50)
    artifact = model.fit(dataset)
    fit = model.fits[asset]
    assert artifact.digest
    assert fit.coefficients[0] == pytest.approx(0.55, abs=0.12)

    asof = now + timedelta(days=170)
    window = adapter.feature_window(asof, (asset,), model.required_features, lookback=10)
    forecast = model.predict(window)
    last_return = window.asset_feature(asset, "log_return_1")
    last_return = last_return[np.isfinite(last_return)][-1]
    expected = fit.intercept + fit.coefficients[0] * last_return
    assert forecast.expected_returns[asset] == pytest.approx(expected)


def test_random_walk_model_is_zero_drift_benchmark(now):
    asset = make_assets(1)[0]
    returns = generate_ar_returns(80, phi=0.0, seed=2)
    adapter = InMemoryPriceDataAdapter(
        {asset: bars_from_returns(asset, returns, start=now)}, data_version="rw-v1"
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=(asset,),
            features=("log_return_1",),
            labels=("forward_log_return_1",),
            splits={"train": TimeRange(now, now + timedelta(days=70))},
        )
    )
    model = RandomWalkAlphaModel()
    model.fit(dataset)
    window = adapter.feature_window(
        now + timedelta(days=69), (asset,), model.required_features, lookback=20
    )
    forecast = model.predict(window)
    assert forecast.expected_returns[asset] == 0.0
    assert forecast.uncertainty[asset] > 0


def test_random_walk_diagnostics_reports_ljung_box(now):
    asset = make_assets(1)[0]
    returns = generate_ar_returns(120, phi=0.6, seed=9)
    adapter = InMemoryPriceDataAdapter(
        {asset: bars_from_returns(asset, returns, start=now)}, data_version="diag-v1"
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=(asset,),
            features=("log_return_1",),
            labels=("forward_log_return_1",),
            splits={"train": TimeRange(now, now + timedelta(days=110))},
        )
    )
    report = RandomWalkDiagnostics(lags=5).run(dataset)
    stats = report.assets[asset]
    assert len(stats.autocorrelation) == 5
    assert stats.autocorrelation[0] > 0.2
    assert 0.0 <= stats.ljung_box_pvalue <= 1.0
