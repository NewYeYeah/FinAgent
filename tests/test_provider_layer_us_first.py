from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from finagent.data import (
    AKSHARE_CAPABILITIES,
    ALPACA_CAPABILITIES,
    HITHINK_CAPABILITIES,
    TUSHARE_15000_CAPABILITIES,
    AKShareMarketDataIngestor,
    DataFrequency,
    HiThinkMarketDataIngestor,
    MarketDataPullRequest,
    MarketRegion,
    ProviderSymbolMap,
    ResearchDataRequirement,
    compare_provider_records,
)
from finagent.domain.assets import AssetType


def _us_request(*symbols: str) -> MarketDataPullRequest:
    return MarketDataPullRequest(
        market=MarketRegion.US_EQUITY,
        symbols=tuple(symbols),
        start=date(2026, 8, 20),
        end=date(2026, 8, 21),
        asset_type=AssetType.ETF,
    )


def _cn_request(*symbols: str) -> MarketDataPullRequest:
    return MarketDataPullRequest(
        market=MarketRegion.A_SHARE,
        symbols=tuple(symbols),
        start=date(2026, 8, 20),
        end=date(2026, 8, 21),
        asset_type=AssetType.ETF,
    )


def test_provider_capabilities_keep_us_research_centered_on_alpaca_and_akshare() -> None:
    requirement = ResearchDataRequirement(MarketRegion.US_EQUITY, DataFrequency.DAILY)
    assert requirement.gaps(ALPACA_CAPABILITIES) == ()
    assert requirement.gaps(AKSHARE_CAPABILITIES) == ()
    assert "market:us_equity" in requirement.gaps(HITHINK_CAPABILITIES)
    assert "market:us_equity" in requirement.gaps(TUSHARE_15000_CAPABILITIES)


def test_tushare_15000_does_not_claim_separately_paid_market_entitlements() -> None:
    assert TUSHARE_15000_CAPABILITIES.historical_daily
    assert TUSHARE_15000_CAPABILITIES.fundamentals
    assert TUSHARE_15000_CAPABILITIES.macro
    assert not TUSHARE_15000_CAPABILITIES.historical_minute
    assert not TUSHARE_15000_CAPABILITIES.realtime_snapshot
    assert MarketRegion.US_EQUITY not in TUSHARE_15000_CAPABILITIES.markets


def test_research_requirement_blocks_hithink_survivorship_sensitive_study() -> None:
    requirement = ResearchDataRequirement(
        MarketRegion.A_SHARE,
        require_pit_universe=True,
        require_delisted_history=True,
    )
    with pytest.raises(ValueError, match="pit_universe.*delisted_history"):
        requirement.require(HITHINK_CAPABILITIES)


class _FakeAKShare:
    @staticmethod
    def stock_us_hist(**kwargs):
        assert kwargs["symbol"] == "105.SPY"
        assert kwargs["adjust"] == ""
        return [
            {
                "日期": "2026-08-20",
                "开盘": 640.0,
                "最高": 646.0,
                "最低": 639.0,
                "收盘": 645.0,
                "成交量": 10_000_000,
            },
            {
                "日期": "2026-08-21",
                "开盘": 645.5,
                "最高": 648.0,
                "最低": 643.0,
                "收盘": 647.0,
                "成交量": 11_000_000,
            },
        ]

    @staticmethod
    def fund_etf_hist_em(**kwargs):
        assert kwargs["symbol"] == "510300"
        return [
            {
                "日期": "2026-08-20",
                "开盘": 4.10,
                "最高": 4.15,
                "最低": 4.09,
                "收盘": 4.14,
                "成交量": 12345,
            }
        ]


def test_akshare_us_daily_normalizes_provider_symbol_without_polluting_asset_identity() -> None:
    ingestor = AKShareMarketDataIngestor(
        _FakeAKShare(),
        symbol_map=ProviderSymbolMap("akshare", {"SPY": "105.SPY"}, strict=True),
    )
    request = _us_request("SPY")
    rows = ingestor.fetch(request)
    normalized = ingestor.normalize(request, rows)
    assert len(normalized) == 2
    assert normalized[0].source_symbol == "105.SPY"
    assert normalized[0].asset.symbol == "SPY"
    assert normalized[0].asset.currency == "USD"
    assert normalized[0].asset.venue == "XNAS"
    assert normalized[0].bar.volume == 10_000_000
    assert normalized[0].bar.available_at.tzinfo is not None


def test_akshare_cn_etf_volume_is_normalized_from_lots_to_shares() -> None:
    ingestor = AKShareMarketDataIngestor(_FakeAKShare())
    request = _cn_request("510300.SH")
    normalized = ingestor.normalize(request, ingestor.fetch(request))
    assert normalized[0].asset.symbol == "510300"
    assert normalized[0].asset.venue == "SSE"
    assert normalized[0].bar.volume == 1_234_500


def test_hithink_daily_adapter_uses_raw_daily_endpoint_and_normalizes() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers):
        calls.append((url, dict(headers)))
        query = parse_qs(urlparse(url).query)
        assert query["thscode"] == ["510300.SH"]
        assert query["interval"] == ["1d"]
        assert query["adjust"] == ["none"]
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "item": [
                    {
                        "date_ms": 1787155200000,
                        "open_price": 4.10,
                        "high_price": 4.15,
                        "low_price": 4.09,
                        "close_price": 4.14,
                        "volume": 1_234_500,
                    }
                ]
            },
        }

    ingestor = HiThinkMarketDataIngestor("test-key", transport=transport)
    request = _cn_request("510300.SH")
    normalized = ingestor.normalize(request, ingestor.fetch(request))
    assert len(calls) == 1
    assert calls[0][1]["X-api-key"] == "test-key"
    assert normalized[0].asset.symbol == "510300"
    assert normalized[0].bar.close == pytest.approx(4.14)


def test_provider_diff_report_preserves_disagreement_as_evidence() -> None:
    ingestor = AKShareMarketDataIngestor(
        _FakeAKShare(),
        symbol_map=ProviderSymbolMap("akshare", {"SPY": "105.SPY"}, strict=True),
    )
    request = _us_request("SPY")
    left = list(ingestor.normalize(request, ingestor.fetch(request)))
    right = list(left)
    bar = right[1].bar
    from finagent.data import NormalizedBarRecord
    from finagent.domain.market import PriceBar

    right[1] = NormalizedBarRecord(
        asset=right[1].asset,
        source_symbol="SPY",
        bar=PriceBar(
            event_time=bar.event_time,
            available_at=bar.available_at,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close + 0.5,
            volume=bar.volume,
        ),
    )
    report = compare_provider_records("akshare", left, "alpaca", right)
    assert report.exact_calendar_match
    assert report.common_rows == 2
    assert report.max_close_abs_error == pytest.approx(0.5)
    assert report.max_close_rel_error > 0


def test_provider_symbol_map_strict_mode_prevents_implicit_us_code_guessing() -> None:
    mapping = ProviderSymbolMap("akshare", {}, strict=True)
    with pytest.raises(KeyError, match="AAPL"):
        mapping.resolve("AAPL")


def test_capability_contract_is_data_not_provider_name_branching() -> None:
    assert ALPACA_CAPABILITIES.realtime_stream
    assert not AKSHARE_CAPABILITIES.realtime_stream
    assert HITHINK_CAPABILITIES.corporate_actions
    assert not HITHINK_CAPABILITIES.historical_minute
    assert datetime.now(UTC).tzinfo is not None
