from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import MarketSnapshot, PriceBar

UTC = timezone.utc


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 24, 8, 0, tzinfo=UTC)


@pytest.fixture
def assets() -> tuple[AssetId, AssetId]:
    return (
        AssetId("AAA", AssetType.EQUITY, venue="XNAS", currency="USD"),
        AssetId("BBB", AssetType.EQUITY, venue="XNYS", currency="USD"),
    )


@pytest.fixture
def snapshot(now, assets) -> MarketSnapshot:
    a, b = assets
    return MarketSnapshot(
        asof=now,
        bars={
            a: PriceBar(now, now, open=100, high=102, low=99, close=100, volume=1_000_000),
            b: PriceBar(now, now, open=50, high=51, low=49, close=50, volume=2_000_000),
        },
        data_version="fixture-v1",
    )
