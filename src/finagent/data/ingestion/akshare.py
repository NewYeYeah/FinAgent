from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar

from .base import (
    MarketDataPullRequest,
    MarketRegion,
    MaterializedMarketData,
    NormalizedBarRecord,
    finalize_materialization,
    frame_records,
    numeric,
)
from .providers import DataCapability, ProviderCapabilities, ProviderSymbolMap, ProviderTier

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")


def _pick(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    raise KeyError(f"none of the fields are present: {names}")


def _day(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return date.fromisoformat(text[:10])


def _cn_venue(symbol: str, override: str = "") -> str:
    if override:
        return override.upper()
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    if suffix == "SH":
        return "SSE"
    if suffix == "SZ":
        return "SZSE"
    if suffix == "BJ":
        return "BSE"
    raise ValueError(f"cannot infer A-share venue from {symbol!r}; provide venue_overrides")


def _internal_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0].upper()


class AKShareMarketDataIngestor:
    """Best-effort free daily-bar ingestor for development and cross-provider QA."""

    PROVIDER = "akshare"
    CAPABILITIES = ProviderCapabilities(
        provider=PROVIDER,
        markets=frozenset({MarketRegion.A_SHARE, MarketRegion.US_EQUITY}),
        asset_types=frozenset({AssetType.EQUITY, AssetType.ETF}),
        available=frozenset({DataCapability.HISTORICAL_DAILY}),
        implemented=frozenset({DataCapability.HISTORICAL_DAILY}),
        tier=ProviderTier.DEVELOPMENT,
        notes=("public-upstream aggregation; no SLA", "use as development/cross-check data"),
    )

    def __init__(self, client, *, symbol_map: ProviderSymbolMap | None = None) -> None:
        self.client = client
        self.symbol_map = symbol_map or ProviderSymbolMap(self.PROVIDER)

    @classmethod
    def from_environment(
        cls, *, symbol_map: ProviderSymbolMap | None = None
    ) -> AKShareMarketDataIngestor:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AKShare support is optional; install the cn-free extra") from exc
        return cls(ak, symbol_map=symbol_map)

    def _provider_symbol(self, canonical: str) -> str:
        mapped = self.symbol_map.resolve(canonical)
        if mapped.upper().endswith((".SH", ".SZ", ".BJ")):
            return mapped.split(".", 1)[0]
        return mapped

    def fetch(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        if request.market not in {MarketRegion.A_SHARE, MarketRegion.US_EQUITY}:
            raise ValueError("AKShare adapter supports A-share and US equity daily research")
        if request.asset_type not in {AssetType.EQUITY, AssetType.ETF}:
            raise ValueError("AKShare adapter supports only equity/ETF daily bars")
        output: list[dict[str, object]] = []
        for canonical in request.symbols:
            source = self._provider_symbol(canonical)
            if request.market is MarketRegion.A_SHARE:
                endpoint_name = (
                    "fund_etf_hist_em" if request.asset_type is AssetType.ETF else "stock_zh_a_hist"
                )
            else:
                endpoint_name = "stock_us_hist"
            endpoint = getattr(self.client, endpoint_name, None)
            if not callable(endpoint):
                raise TypeError(f"AKShare client does not expose {endpoint_name}()")
            response = endpoint(
                symbol=source,
                period="daily",
                start_date=request.start.strftime("%Y%m%d"),
                end_date=request.end.strftime("%Y%m%d"),
                adjust="",
            )
            for row in frame_records(response):
                enriched = dict(row)
                enriched["_canonical_symbol"] = canonical
                enriched["_provider_symbol"] = source
                enriched["_endpoint"] = endpoint_name
                output.append(enriched)
        return output

    @staticmethod
    def normalize(
        request: MarketDataPullRequest,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[NormalizedBarRecord, ...]:
        requested = set(request.symbols)
        output: list[NormalizedBarRecord] = []
        for row in rows:
            canonical = str(row.get("_canonical_symbol") or "").upper()
            if canonical not in requested:
                raise ValueError(f"AKShare returned unexpected canonical symbol {canonical!r}")
            session = _day(_pick(row, "日期", "date", "trade_date", "Date"))
            if request.market is MarketRegion.A_SHARE:
                event_time = datetime.combine(session, time(9, 30), tzinfo=SHANGHAI).astimezone(UTC)
                available_at = datetime.combine(session, time(15, 15), tzinfo=SHANGHAI).astimezone(UTC)
                venue = _cn_venue(canonical, request.venue_overrides.get(canonical, ""))
                symbol = _internal_symbol(canonical)
                currency = "CNY"
            else:
                event_time = datetime.combine(session, time(9, 30), tzinfo=NEW_YORK).astimezone(UTC)
                available_at = datetime.combine(session, time(16, 15), tzinfo=NEW_YORK).astimezone(UTC)
                venue = request.venue_overrides.get(canonical, "US")
                symbol = canonical
                currency = "USD"
            asset = AssetId(symbol, request.asset_type, venue=venue, currency=currency)
            output.append(
                NormalizedBarRecord(
                    asset=asset,
                    bar=PriceBar(
                        event_time=event_time,
                        available_at=available_at,
                        open=numeric(_pick(row, "开盘", "open", "Open"), "open"),
                        high=numeric(_pick(row, "最高", "high", "High"), "high"),
                        low=numeric(_pick(row, "最低", "low", "Low"), "low"),
                        close=numeric(_pick(row, "收盘", "close", "Close"), "close"),
                        volume=numeric(_pick(row, "成交量", "volume", "Volume"), "volume"),
                    ),
                    source_symbol=canonical,
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
        dataset = "akshare_us_daily" if request.market is MarketRegion.US_EQUITY else "akshare_cn_daily"
        return finalize_materialization(
            provider=self.PROVIDER,
            dataset=dataset,
            request=request,
            raw_records=rows,
            normalized_records=normalized,
            output_dir=output_dir,
            pulled_at=pulled_at,
            require_common_calendar=True,
        )
