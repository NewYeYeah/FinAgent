from datetime import timedelta
from types import MappingProxyType

import pytest

from finagent.domain.assets import AssetId
from finagent.domain.market import MarketSnapshot, PriceBar


def test_asset_id_normalizes_and_is_stable():
    asset = AssetId(" aapl ", venue="xnas", currency="usd")
    assert asset.symbol == "AAPL"
    assert asset.venue == "XNAS"
    assert asset.currency == "USD"
    assert asset.key == "equity:XNAS:AAPL:USD"


def test_asset_id_rejects_blank_symbol():
    with pytest.raises(ValueError, match="symbol"):
        AssetId("   ")


def test_price_bar_rejects_invalid_ohlc(now):
    with pytest.raises(ValueError, match="high"):
        PriceBar(now, now, open=100, high=99, low=98, close=100)


def test_price_bar_rejects_naive_datetime(now):
    with pytest.raises(ValueError, match="timezone-aware"):
        PriceBar(now.replace(tzinfo=None), now, open=100, high=101, low=99, close=100)


def test_market_snapshot_rejects_lookahead(now, assets):
    asset = assets[0]
    future = now + timedelta(seconds=1)
    bar = PriceBar(now, future, open=100, high=101, low=99, close=100)
    with pytest.raises(ValueError, match="look-ahead"):
        MarketSnapshot(now, {asset: bar}, data_version="v1")


def test_market_snapshot_defensively_freezes_mapping(snapshot, assets):
    assert isinstance(snapshot.bars, MappingProxyType)
    with pytest.raises(TypeError):
        snapshot.bars[assets[0]] = snapshot.bars[assets[0]]  # type: ignore[index]


def test_market_snapshot_price_requires_asset(snapshot):
    with pytest.raises(KeyError, match="no price available"):
        snapshot.price(AssetId("MISSING"))
