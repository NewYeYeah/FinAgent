from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar

from .base import (
    MarketDataPullRequest,
    MaterializedMarketData,
    NormalizedBarRecord,
    finalize_materialization,
    frame_records,
    numeric,
)
from .provider import AKSHARE_CAPABILITIES, ProviderSymbolMap

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")


def _date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("/", "-")
    return date.fromisoformat(text[:10])


def _column(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in row:
            return row[name]
    raise KeyError(f"provider row is missing all candidate fields: {names}")


def _venue_for_cn(symbol: str) -> str:
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    if suffix == "SH":
        return "SSE"
    if suffix == "SZ":
        return "SZSE"
    if suffix == "BJ":
        return "BSE"
    code = symbol.split(".", 1)[0]
    if code.startswith(("5", "6", "9")):
        return "SSE"
    if code.startswith(("0", "1", "2", "3")):
        return "SZSE"
    raise ValueError(f"cannot infer A-share venue for {symbol!r}")


def _session_times(day: date, market: str) -> tuple[datetime, datetime]:
    if market == "cn":
        event = datetime.combine(day, time(9, 30), tzinfo=SHANGHAI)
        available = datetime.combine(day, time(16, 0), tzinfo=SHANGHAI)
    else:
        event = datetime.combine(day, time(9, 30), tzinfo=NEW_YORK)
        available = datetime.combine(day, time(16, 15), tzinfo=NEW_YORK)
    return event.astimezone(UTC), available.astimezone(UTC)


class AKShareMarketDataIngestor:
    """Free/best-effort AKShare daily-bar ingestor for CN and US smoke studies.

    The adapter deliberately keeps AKShare provider symbols outside AssetId. US users
    should supply ProviderSymbolMap when their AKShare version expects encodings such
    as ``105.AAPL``.
    """

    PROVIDER = "akshare"
    CAPABILITIES = AKSHARE_CAPABILITIES

    def __init__(self, client, *, symbol_map: ProviderSymbolMap | None = None) -> None:
        self.client = client
        self.symbol_map = symbol_map or ProviderSymbolMap("akshare")

    @classmethod
    def from_environment(
        cls, *, symbol_map: ProviderSymbolMap | None = None
    ) -> AKShareMarketDataIngestor:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AKShare support is optional; install the cn-free extra") from exc
        return cls(ak, symbol_map=symbol_map)

    def _fetch_cn(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        if request.asset_type is AssetType.ETF:
            endpoint = getattr(self.client, "fund_etf_hist_em", None)
        elif request.asset_type is AssetType.EQUITY:
            endpoint = getattr(self.client, "stock_zh_a_hist", None)
        else:
            raise ValueError("AKShare CN daily ingestion supports only equity/ETF")
        if not callable(endpoint):
            raise TypeError("AKShare client does not expose the required CN historical endpoint")
        output: list[dict[str, object]] = []
        for canonical in request.symbols:
            provider_symbol = self.symbol_map.resolve(canonical)
            kwargs = {
                "symbol": provider_symbol.split(".", 1)[0],
                "period": "daily",
                "start_date": request.start.strftime("%Y%m%d"),
                "end_date": request.end.strftime("%Y%m%d"),
                "adjust": "",
            }
            for row in frame_records(endpoint(**kwargs)):
                item = dict(row)
                item["_canonical_symbol"] = canonical
                item["_provider_symbol"] = provider_symbol
                item["_market"] = "cn"
                output.append(item)
        return output

    def _fetch_us(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        endpoint = getattr(self.client, "stock_us_hist", None)
        if not callable(endpoint):
            raise TypeError("AKShare client does not expose stock_us_hist()")
        if request.asset_type not in {AssetType.EQUITY, AssetType.ETF}:
            raise ValueError("AKShare US daily ingestion supports only equity/ETF")
        output: list[dict[str, object]] = []
        for canonical in request.symbols:
            provider_symbol = self.symbol_map.resolve(canonical)
            response = endpoint(
                symbol=provider_symbol,
                period="daily",
                start_date=request.start.strftime("%Y%m%d"),
                end_date=request.end.strftime("%Y%m%d"),
                adjust="",
            )
            for row in frame_records(response):
                item = dict(row)
                item["_canonical_symbol"] = canonical
                item["_provider_symbol"] = provider_symbol
                item["_market"] = "us"
                output.append(item)
        return output

    def fetch(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        if request.adjustment != "raw":
            raise ValueError("AKShare research ingestion requires raw prices")
        if request.market.value == "a_share":
            return self._fetch_cn(request)
        if request.market.value == "us_equity":
            return self._fetch_us(request)
        raise ValueError(f"unsupported AKShare market {request.market.value!r}")

    @staticmethod
    def normalize(
        request: MarketDataPullRequest,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[NormalizedBarRecord, ...]:
        requested = set(request.symbols)
        output: list[NormalizedBarRecord] = []
        for row in rows:
            canonical = str(row["_canonical_symbol"]).upper()
            if canonical not in requested:
                raise ValueError(f"AKShare returned unexpected canonical symbol {canonical!r}")
            market = str(row["_market"])
            day = _date_value(_column(row, "日期", "date", "Date", "trade_date"))
            event_time, available_at = _session_times(day, market)
            if market == "cn":
                venue = request.venue_overrides.get(canonical, _venue_for_cn(canonical))
                currency = "CNY"
                volume = numeric(_column(row, "成交量", "volume", "Volume"), "volume") * 100.0
                symbol = canonical.split(".", 1)[0]
            else:
                venue = request.venue_overrides.get(canonical, "XNAS")
                currency = "USD"
                volume = numeric(_column(row, "成交量", "volume", "Volume"), "volume")
                symbol = canonical
            asset = AssetId(symbol, request.asset_type, venue=venue, currency=currency)
            output.append(
                NormalizedBarRecord(
                    asset=asset,
                    bar=PriceBar(
                        event_time=event_time,
                        available_at=available_at,
                        open=numeric(_column(row, "开盘", "open", "Open"), "open"),
                        high=numeric(_column(row, "最高", "high", "High"), "high"),
                        low=numeric(_column(row, "最低", "low", "Low"), "low"),
                        close=numeric(_column(row, "收盘", "close", "Close"), "close"),
                        volume=volume,
                    ),
                    source_symbol=str(row["_provider_symbol"]),
                )
            )
        return tuple(sorted(output, key=lambda item: (item.asset.key, item.bar.event_time)))

    def materialize(
        self,
        request: MarketDataPullRequest,
        output_dir: str | Path,
        *,
        pulled_at: datetime | None = None,
    ) -> MaterializedMarketData:
        pulled_at = pulled_at or datetime.now(UTC)
        rows = self.fetch(request)
        normalized = self.normalize(request, rows)
        return finalize_materialization(
            provider=self.PROVIDER,
            dataset=f"{request.market.value}_daily",
            request=request,
            raw_records=rows,
            normalized_records=normalized,
            output_dir=output_dir,
            pulled_at=pulled_at,
            require_common_calendar=True,
        )
