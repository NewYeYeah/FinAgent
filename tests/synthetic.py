from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar
from finagent.domain.research import DatasetRequest, TimeRange

UTC = timezone.utc


def make_assets(n: int = 2) -> tuple[AssetId, ...]:
    return tuple(
        AssetId(chr(ord("A") + i) * 3, AssetType.EQUITY, venue="XNAS", currency="USD")
        for i in range(n)
    )


def generate_correlated_returns(n: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    common = rng.normal(0.0003, 0.006, size=n)
    e1 = rng.normal(0.0, 0.004, size=n)
    e2 = rng.normal(0.0, 0.004, size=n)
    r1 = common + e1
    r2 = 0.7 * common + e2
    return np.column_stack([r1, r2])


def generate_ar_returns(n: int, phi: float = 0.45, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    series = np.zeros(n, dtype=float)
    noise = rng.normal(0.0, 0.004, size=n)
    for t in range(1, n):
        series[t] = phi * series[t - 1] + noise[t]
    return series


def bars_from_returns(
    asset: AssetId,
    returns: np.ndarray,
    *,
    start: datetime,
    start_price: float = 100.0,
) -> list[PriceBar]:
    price = start_price
    bars: list[PriceBar] = []
    for idx, ret in enumerate(returns):
        ts = start + timedelta(days=idx)
        previous = price
        price = price * float(np.exp(ret))
        open_ = previous
        high = max(open_, price) * 1.001
        low = min(open_, price) * 0.999
        bars.append(
            PriceBar(
                event_time=ts,
                available_at=ts,
                open=open_,
                high=high,
                low=low,
                close=price,
                volume=1_000_000.0 + idx * 1000.0,
            )
        )
    return bars


def make_phase1_adapter(n: int = 220, seed: int = 7):
    assets = make_assets(2)
    start = datetime(2025, 1, 1, 16, 0, tzinfo=UTC)
    returns = generate_correlated_returns(n, seed=seed)
    histories = {
        assets[0]: bars_from_returns(assets[0], returns[:, 0], start=start, start_price=100.0),
        assets[1]: bars_from_returns(assets[1], returns[:, 1], start=start, start_price=80.0),
    }
    adapter = InMemoryPriceDataAdapter(histories, data_version=f"synthetic-{seed}")
    request = DatasetRequest(
        universe=assets,
        features=("log_return_1", "squared_log_return_1"),
        labels=("forward_log_return_1",),
        splits={
            "train": TimeRange(start, start + timedelta(days=150)),
            "valid": TimeRange(start + timedelta(days=150), start + timedelta(days=180)),
            "test": TimeRange(start + timedelta(days=180), start + timedelta(days=n)),
        },
        dataset_id="synthetic-phase1",
    )
    return adapter, adapter.build_dataset(request), assets, start
