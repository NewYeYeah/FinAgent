from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from finagent.data import (
    AlpacaMarketDataIngestor,
    CSVPriceDataAdapter,
    MarketDataPullRequest,
    MarketRegion,
    TushareMarketDataIngestor,
    read_normalized_csv,
)
from finagent.domain.assets import AssetType


class _TushareClient:
    def __init__(self, *, omit_last_for: str = "") -> None:
        self.omit_last_for = omit_last_for

    def fund_daily(self, *, ts_code: str, start_date: str, end_date: str):
        assert start_date == "20240102"
        assert end_date == "20240103"
        dates = ["20240103", "20240102"]
        if ts_code == self.omit_last_for:
            dates = dates[1:]
        return [
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "open": 4.0,
                "high": 4.2,
                "low": 3.9,
                "close": 4.1,
                "vol": 123.0,
            }
            for trade_date in dates
        ]


def _a_share_request() -> MarketDataPullRequest:
    return MarketDataPullRequest(
        market=MarketRegion.A_SHARE,
        symbols=("510300.SH", "159915.SZ"),
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        asset_type=AssetType.ETF,
    )


def test_tushare_materialization_is_pit_normalized_and_deterministic(tmp_path) -> None:
    ingestor = TushareMarketDataIngestor(_TushareClient())
    first = ingestor.materialize(
        _a_share_request(),
        tmp_path / "first",
        pulled_at=datetime(2024, 1, 4, tzinfo=UTC),
    )
    second = ingestor.materialize(
        _a_share_request(),
        tmp_path / "second",
        pulled_at=datetime(2024, 1, 5, tzinfo=UTC),
    )

    assert first.quality.passed
    assert first.manifest.rows == 4
    assert first.manifest.assets == 2
    assert first.manifest.data_version == second.manifest.data_version
    records = read_normalized_csv(first.normalized_path)
    assert {record.asset.currency for record in records} == {"CNY"}
    assert {record.asset.venue for record in records} == {"SSE", "SZSE"}
    assert {record.bar.volume for record in records} == {12_300.0}
    assert all(record.bar.event_time < record.bar.available_at for record in records)
    assert CSVPriceDataAdapter(
        first.normalized_path, data_version=first.manifest.data_version
    ).data_version == first.manifest.data_version
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["request"]["adjustment"] == "raw"
    assert manifest["quality_passed"] is True


def test_fixed_universe_ingestion_fails_closed_on_calendar_gap(tmp_path) -> None:
    ingestor = TushareMarketDataIngestor(_TushareClient(omit_last_for="159915.SZ"))
    with pytest.raises(ValueError, match="DQ-10"):
        ingestor.materialize(_a_share_request(), tmp_path / "bad")
    report = json.loads((tmp_path / "bad" / "quality_report.json").read_text())
    assert report["passed"] is False
    assert {issue["code"] for issue in report["issues"]} == {"DQ-10"}


class _AlpacaClient:
    def get_stock_bars(self, request):
        assert request == "request-sentinel"
        data = {}
        for symbol, venue_price in (("SPY", 500.0), ("QQQ", 430.0)):
            data[symbol] = [
                SimpleNamespace(
                    timestamp=datetime(2024, 1, day, 5, tzinfo=UTC),
                    open=venue_price,
                    high=venue_price + 2,
                    low=venue_price - 2,
                    close=venue_price + 1,
                    volume=1_000_000,
                )
                for day in (2, 3)
            ]
        return SimpleNamespace(data=data)


def test_alpaca_materialization_preserves_dst_safe_session_clocks(tmp_path) -> None:
    request = MarketDataPullRequest(
        market=MarketRegion.US_EQUITY,
        symbols=("SPY", "QQQ"),
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        asset_type=AssetType.ETF,
        feed="iex",
        venue_overrides={"SPY": "ARCX", "QQQ": "XNAS"},
    )
    ingestor = AlpacaMarketDataIngestor(
        _AlpacaClient(), request_builder=lambda _: "request-sentinel"
    )
    result = ingestor.materialize(request, tmp_path / "us")
    records = read_normalized_csv(result.normalized_path)

    assert result.quality.passed
    assert {record.asset.venue for record in records} == {"ARCX", "XNAS"}
    assert {record.asset.currency for record in records} == {"USD"}
    assert {record.bar.volume for record in records} == {1_000_000.0}
    assert all(record.bar.available_at.hour == 21 for record in records)
    assert all(record.bar.event_time.hour == 14 for record in records)


def test_m1_rejects_adjusted_execution_prices() -> None:
    with pytest.raises(ValueError, match="only raw execution prices"):
        MarketDataPullRequest(
            market=MarketRegion.US_EQUITY,
            symbols=("SPY",),
            start=date(2024, 1, 2),
            end=date(2024, 1, 3),
            adjustment="all",
        )
