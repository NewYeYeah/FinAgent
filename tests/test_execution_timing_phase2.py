from datetime import datetime, timedelta, timezone

import pytest

from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar

UTC = timezone.utc


def test_execution_open_is_visible_without_exposing_same_bar_close():
    asset = AssetId("AAA", AssetType.EQUITY, venue="XNAS", currency="USD")
    day1_open = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
    day1_close = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)
    day2_open = datetime(2026, 1, 6, 9, 30, tzinfo=UTC)
    day2_close = datetime(2026, 1, 6, 16, 0, tzinfo=UTC)
    bars = [
        PriceBar(day1_open, day1_close, 100.0, 103.0, 99.0, 102.0, 1_000_000),
        PriceBar(day2_open, day2_close, 103.0, 106.0, 102.0, 105.0, 1_100_000),
    ]
    adapter = InMemoryPriceDataAdapter({asset: bars}, data_version="timing-v1")

    execution = adapter.execution_snapshot(day2_open, (asset,), price_field="open")
    assert execution.price(asset) == 103.0
    assert execution.quotes[asset].available_at == day2_open

    # The day-2 close is not yet available through the research snapshot at day-2 open.
    research = adapter.market_snapshot(day2_open, (asset,))
    assert research.bars[asset].event_time == day1_open
    assert research.price(asset) == 102.0


def test_execution_snapshot_rejects_unsupported_ambiguous_bar_fields():
    asset = AssetId("AAA", AssetType.EQUITY, venue="XNAS", currency="USD")
    ts = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)
    bar = PriceBar(ts, ts, 100.0, 101.0, 99.0, 100.5, 1000)
    adapter = InMemoryPriceDataAdapter({asset: [bar]})
    with pytest.raises(ValueError, match="open.*close"):
        adapter.execution_snapshot(ts, (asset,), price_field="high")
