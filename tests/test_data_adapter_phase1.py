from datetime import timedelta

import numpy as np
import pytest

from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.market import PriceBar
from finagent.domain.research import DatasetRequest, TimeRange
from tests.synthetic import bars_from_returns, generate_ar_returns, make_assets


def test_adapter_builds_pit_feature_and_label_panels(now):
    asset = make_assets(1)[0]
    returns = np.array([0.0, 0.01, -0.02, 0.03, 0.01])
    start = now
    adapter = InMemoryPriceDataAdapter(
        {asset: bars_from_returns(asset, returns, start=start)}, data_version="v1"
    )
    request = DatasetRequest(
        universe=(asset,),
        features=("log_return_1", "simple_return_1"),
        labels=("forward_log_return_1",),
        splits={"train": TimeRange(start, start + timedelta(days=5))},
    )
    dataset = adapter.build_dataset(request)
    panel = dataset.get_split("train")
    log_returns = panel.feature_panel("log_return_1")[:, 0]
    labels = panel.label_panel("forward_log_return_1")[:, 0]
    assert np.isnan(log_returns[0])
    assert log_returns[1] == pytest.approx(0.01)
    assert labels[1] == pytest.approx(-0.02)
    assert np.isnan(labels[-1])


def test_labels_do_not_cross_split_boundary(now):
    asset = make_assets(1)[0]
    returns = np.array([0.0, 0.01, 0.02, 0.03])
    adapter = InMemoryPriceDataAdapter(
        {asset: bars_from_returns(asset, returns, start=now)}, data_version="v1"
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=(asset,),
            features=("log_return_1",),
            labels=("forward_log_return_1",),
            splits={
                "train": TimeRange(now, now + timedelta(days=2)),
                "test": TimeRange(now + timedelta(days=2), now + timedelta(days=4)),
            },
        )
    )
    train_labels = dataset.get_split("train").label_panel("forward_log_return_1")[:, 0]
    assert np.isnan(train_labels[-1])


def test_feature_window_is_asof_safe(now):
    asset = make_assets(1)[0]
    bars = bars_from_returns(asset, np.array([0.0, 0.01, 0.02]), start=now)
    # Make the third bar available one day later than its event timestamp.
    third = bars[2]
    bars[2] = PriceBar(
        event_time=third.event_time,
        available_at=third.available_at + timedelta(days=1),
        open=third.open,
        high=third.high,
        low=third.low,
        close=third.close,
        volume=third.volume,
    )
    adapter = InMemoryPriceDataAdapter({asset: bars}, data_version="v1")
    window = adapter.feature_window(
        asof=now + timedelta(days=2),
        universe=(asset,),
        features=("log_return_1",),
        lookback=10,
    )
    assert window.timestamps[-1] == now + timedelta(days=1)
    assert window.lookback == 2
