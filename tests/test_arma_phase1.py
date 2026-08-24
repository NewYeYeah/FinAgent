from datetime import timedelta

import math
import numpy as np

from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.models.alpha import ARMA11AlphaModel
from tests.synthetic import bars_from_returns, make_assets


def test_arma11_fit_and_predict(now):
    rng = np.random.default_rng(17)
    n = 180
    phi = 0.35
    theta = 0.25
    eps = rng.normal(0.0, 0.004, size=n)
    returns = np.zeros(n)
    for t in range(1, n):
        returns[t] = phi * returns[t - 1] + theta * eps[t - 1] + eps[t]

    asset = make_assets(1)[0]
    adapter = InMemoryPriceDataAdapter(
        {asset: bars_from_returns(asset, returns, start=now)}, data_version="arma-v1"
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
    model = ARMA11AlphaModel(min_observations=50)
    model.fit(dataset)
    fit = model.fits[asset]
    assert abs(fit.phi) < 1
    assert abs(fit.theta) < 1
    window = adapter.feature_window(
        now + timedelta(days=170), (asset,), model.required_features, lookback=50
    )
    forecast = model.predict(window)
    assert math.isfinite(forecast.expected_returns[asset])
    assert forecast.uncertainty[asset] > 0
