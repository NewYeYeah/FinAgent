from datetime import timedelta

from finagent.data import SQLitePriceDataAdapter, SQLitePriceStore
from tests.synthetic import bars_from_returns, generate_ar_returns, make_assets


def test_sqlite_price_store_roundtrip_and_adapter(tmp_path, now):
    asset = make_assets(1)[0]
    bars = bars_from_returns(asset, generate_ar_returns(12, phi=0.2, seed=3), start=now)
    store = SQLitePriceStore(tmp_path / "prices.db")
    assert store.upsert(asset, bars) == 12
    loaded = store.load((asset,))
    assert loaded[asset][5].close == bars[5].close
    assert store.content_digest
    assert store.list_assets() == (asset,)

    adapter = SQLitePriceDataAdapter(store, (asset,))
    snapshot = adapter.market_snapshot(now + timedelta(days=5), (asset,))
    assert snapshot.price(asset) == bars[5].close
    assert adapter.data_version.startswith("sqlite-")
