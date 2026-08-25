from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from finagent.data import (
    ALPACA_CAPABILITIES,
    TUSHARE_15K_CAPABILITIES,
    AKShareMarketDataIngestor,
    AlpacaMarketDataIngestor,
    DataCapability,
    HiThinkMarketDataIngestor,
    MarketDataPullRequest,
    MarketRegion,
    ProviderSymbolMap,
    ResearchDataRequirement,
    compare_provider_records,
    default_provider_registry,
)
from finagent.domain.assets import AssetType


class _AKShareUSClient:
    def __init__(self) -> None:
        self.spot_calls = 0
        self.history_calls: list[str] = []

    def stock_us_spot_em(self):
        self.spot_calls += 1
        return [{"代码": "106.SPY"}, {"代码": "105.QQQ"}]

    def stock_us_hist(
        self,
        *,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ):
        assert period == "daily"
        assert start_date == "20240102"
        assert end_date == "20240103"
        assert adjust == ""
        self.history_calls.append(symbol)
        base = 500.0 if symbol.endswith("SPY") else 430.0
        return [
            {
                "日期": f"2024-01-0{day}",
                "开盘": base,
                "最高": base + 2.0,
                "最低": base - 2.0,
                "收盘": base + 1.0,
                "成交量": 1_000_000,
            }
            for day in (2, 3)
        ]


def _us_request() -> MarketDataPullRequest:
    return MarketDataPullRequest(
        market=MarketRegion.US_EQUITY,
        symbols=("SPY", "QQQ"),
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        asset_type=AssetType.ETF,
        venue_overrides={"SPY": "ARCX", "QQQ": "XNAS"},
    )


def test_akshare_us_resolves_canonical_symbols_once_and_materializes(tmp_path) -> None:
    client = _AKShareUSClient()
    ingestor = AKShareMarketDataIngestor(client)
    result = ingestor.materialize(
        _us_request(),
        tmp_path / "akshare-us",
        pulled_at=datetime(2024, 1, 4, tzinfo=UTC),
    )

    assert result.quality.passed
    assert client.spot_calls == 1
    assert sorted(client.history_calls) == ["105.QQQ", "106.SPY"]
    assert result.manifest.provider == "akshare"
    assert result.manifest.rows == 4


def test_akshare_explicit_symbol_map_avoids_spot_lookup(tmp_path) -> None:
    client = _AKShareUSClient()
    ingestor = AKShareMarketDataIngestor(
        client,
        symbol_map=ProviderSymbolMap("akshare", {"SPY": "106.SPY", "QQQ": "105.QQQ"}),
    )
    result = ingestor.materialize(_us_request(), tmp_path / "mapped")
    assert result.quality.passed
    assert client.spot_calls == 0


def test_us_cross_provider_diff_operates_on_canonical_symbol_and_session() -> None:
    request = _us_request()
    ak_rows = []
    for canonical, base in (("SPY", 500.0), ("QQQ", 430.0)):
        for day in (2, 3):
            ak_rows.append(
                {
                    "_canonical_symbol": canonical,
                    "_provider_symbol": f"provider.{canonical}",
                    "日期": f"2024-01-0{day}",
                    "开盘": base,
                    "最高": base + 2.0,
                    "最低": base - 2.0,
                    "收盘": base + 1.0,
                    "成交量": 1_000_000,
                }
            )
    alpaca_rows = []
    for canonical, base in (("SPY", 500.0), ("QQQ", 430.0)):
        for day in (2, 3):
            alpaca_rows.append(
                {
                    "symbol": canonical,
                    "timestamp": datetime(2024, 1, day, 5, tzinfo=UTC),
                    "open": base,
                    "high": base + 2.0,
                    "low": base - 2.0,
                    "close": base + 1.0,
                    "volume": 1_000_000,
                }
            )

    report = compare_provider_records(
        "akshare",
        AKShareMarketDataIngestor.normalize(request, ak_rows),
        "alpaca",
        AlpacaMarketDataIngestor.normalize(request, alpaca_rows),
    )
    assert report.passed
    assert report.common_rows == 4
    assert report.max_close_abs_error == 0.0


def test_provider_registry_prefers_explicit_capabilities_not_name_guessing() -> None:
    registry = default_provider_registry()
    requirement = ResearchDataRequirement(
        market=MarketRegion.US_EQUITY,
        asset_types=frozenset({AssetType.ETF}),
        capabilities=frozenset({DataCapability.HISTORICAL_DAILY}),
    )
    providers = {item.provider for item in registry.candidates(requirement)}
    assert providers == {"akshare", "alpaca"}

    realtime = ResearchDataRequirement(
        market=MarketRegion.US_EQUITY,
        asset_types=frozenset({AssetType.ETF}),
        capabilities=frozenset({DataCapability.REALTIME_STREAM}),
    )
    assert registry.candidates(realtime) == ()
    assert {item.provider for item in registry.candidates(realtime, implemented_only=False)} == {
        "alpaca"
    }


def test_tushare_15k_contract_does_not_claim_us_or_minute_access() -> None:
    us = ResearchDataRequirement(
        market=MarketRegion.US_EQUITY,
        asset_types=frozenset({AssetType.EQUITY}),
        capabilities=frozenset({DataCapability.HISTORICAL_DAILY}),
    )
    minute = ResearchDataRequirement(
        market=MarketRegion.A_SHARE,
        asset_types=frozenset({AssetType.EQUITY}),
        capabilities=frozenset({DataCapability.HISTORICAL_MINUTE}),
    )
    assert not TUSHARE_15K_CAPABILITIES.supports(us, implemented_only=False)
    assert not TUSHARE_15K_CAPABILITIES.supports(minute, implemented_only=False)
    assert DataCapability.FUNDAMENTALS in TUSHARE_15K_CAPABILITIES.available


def test_alpaca_vendor_capability_is_distinct_from_current_adapter_surface() -> None:
    assert DataCapability.REALTIME_STREAM in ALPACA_CAPABILITIES.available
    assert DataCapability.REALTIME_STREAM not in ALPACA_CAPABILITIES.implemented


class _HiThinkClient:
    def get(self, path, params):
        assert path == "/api/fund/market/historical"
        assert params["interval"] == "1d"
        day = datetime(2024, 1, 2, tzinfo=UTC)
        return {
            "code": 0,
            "data": {
                "item": [
                    {
                        "date_ms": int(day.timestamp() * 1000),
                        "open_price": 4.0,
                        "high_price": 4.2,
                        "low_price": 3.9,
                        "close_price": 4.1,
                        "volume": 100_000,
                    }
                ]
            },
        }


def test_hithink_interface_lands_for_later_a_share_work(tmp_path) -> None:
    request = MarketDataPullRequest(
        market=MarketRegion.A_SHARE,
        symbols=("510300.SH",),
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
        asset_type=AssetType.ETF,
    )
    result = HiThinkMarketDataIngestor(_HiThinkClient()).materialize(
        request,
        tmp_path / "hithink",
    )
    assert result.quality.passed
    assert result.manifest.provider == "hithink"


def test_provider_registry_never_silently_falls_back() -> None:
    registry = default_provider_registry()
    with pytest.raises(KeyError, match="unknown market-data provider"):
        registry.create("not-a-provider")
