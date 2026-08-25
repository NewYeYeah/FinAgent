from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar

from .base import (
    MarketDataPullRequest,
    MarketRegion,
    MaterializedMarketData,
    NormalizedBarRecord,
    finalize_materialization,
    numeric,
)
from .providers import DataCapability, ProviderCapabilities, ProviderTier

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _internal_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0].upper()


def _venue(symbol: str, override: str = "") -> str:
    if override:
        return override.upper()
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    mapping = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
    try:
        return mapping[suffix]
    except KeyError as exc:
        raise ValueError(f"cannot infer HiThink venue from {symbol!r}") from exc


def _milliseconds(day: date, *, end: bool = False) -> int:
    local_time = time.max if end else time.min
    value = datetime.combine(day, local_time, tzinfo=SHANGHAI).astimezone(UTC)
    return int(value.timestamp() * 1000)


def _shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(month=2, day=28, year=day.year + years)


def _windows(start: date, end: date, years: int) -> tuple[tuple[date, date], ...]:
    output: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        next_boundary = _shift_year(cursor, years)
        chunk_end = min(end, date.fromordinal(next_boundary.toordinal() - 1))
        output.append((cursor, chunk_end))
        cursor = date.fromordinal(chunk_end.toordinal() + 1)
    return tuple(output)


class HiThinkRESTClient:
    def __init__(self, api_key: str, *, base_url: str = "https://fuyao.aicubes.cn") -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("api_key must be non-empty")
        self.api_key = key
        self.base_url = base_url.rstrip("/")

    def get(self, path: str, params: Mapping[str, object]) -> Mapping[str, object]:
        query = urlencode({key: str(value) for key, value in params.items()})
        request = Request(
            f"{self.base_url}{path}?{query}",
            headers={"X-api-key": self.api_key, "Accept": "application/json"},
        )
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise TypeError("HiThink response must be a JSON object")
        return payload


class HiThinkMarketDataIngestor:
    """Official HiThink A-share daily adapter.

    The public service currently exposes daily history and snapshots but not minute/tick
    feeds. This adapter intentionally implements the historical raw-price surface only.
    """

    PROVIDER = "hithink"
    CAPABILITIES = ProviderCapabilities(
        provider=PROVIDER,
        markets=frozenset({MarketRegion.A_SHARE}),
        asset_types=frozenset({AssetType.EQUITY, AssetType.ETF}),
        available=frozenset(
            {
                DataCapability.HISTORICAL_DAILY,
                DataCapability.REALTIME_SNAPSHOT,
                DataCapability.FUNDAMENTALS,
                DataCapability.CORPORATE_ACTIONS,
                DataCapability.ALTERNATIVE_DATA,
            }
        ),
        implemented=frozenset({DataCapability.HISTORICAL_DAILY}),
        tier=ProviderTier.RESEARCH,
        notes=(
            "official HiThink service",
            "public historical service omits delisted-history guarantee; wide-universe backtests must fail closed",
        ),
    )

    def __init__(self, client: object) -> None:
        self.client = client

    @classmethod
    def from_environment(cls) -> HiThinkMarketDataIngestor:
        key = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
        if not key:
            raise RuntimeError("HITHINK_FINANCE_API_KEY is required")
        return cls(HiThinkRESTClient(key))

    @staticmethod
    def _endpoint(asset_type: AssetType) -> tuple[str, int]:
        if asset_type is AssetType.EQUITY:
            return "/api/a-share/prices/historical", 10
        if asset_type is AssetType.ETF:
            return "/api/fund/market/historical", 5
        raise ValueError("HiThink daily adapter supports only A-share equities and ETFs")

    def _get(self, path: str, params: Mapping[str, object]) -> Mapping[str, object]:
        getter = getattr(self.client, "get", None)
        if not callable(getter):
            raise TypeError("HiThink client must expose get(path, params)")
        payload = getter(path, params)
        if not isinstance(payload, Mapping):
            raise TypeError("HiThink client response must be a mapping")
        code = payload.get("code", 0)
        if code not in (0, "0", None):
            raise RuntimeError(
                f"HiThink API error code={code!r}: {payload.get('message', 'unknown error')}"
            )
        data = payload.get("data", payload)
        if not isinstance(data, Mapping):
            raise TypeError("HiThink response data must be a mapping")
        return data

    def fetch(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        if request.market is not MarketRegion.A_SHARE:
            raise ValueError("HiThinkMarketDataIngestor requires market='a_share'")
        path, max_years = self._endpoint(request.asset_type)
        output: list[dict[str, object]] = []
        for symbol in request.symbols:
            for start, end in _windows(request.start, request.end, max_years):
                params: dict[str, object] = {
                    "thscode": symbol,
                    "interval": "1d",
                    "start": _milliseconds(start),
                    "end": _milliseconds(end, end=True),
                }
                if request.asset_type is AssetType.EQUITY:
                    params["adjust"] = "none"
                data = self._get(path, params)
                items = data.get("item", ())
                if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
                    raise TypeError("HiThink historical data.item must be a sequence")
                for item in items:
                    if not isinstance(item, Mapping):
                        raise TypeError("HiThink historical item must be a mapping")
                    row = dict(item)
                    row["_requested_symbol"] = symbol
                    row["_endpoint"] = path
                    output.append(row)
        deduped: dict[tuple[str, int], dict[str, object]] = {}
        for row in output:
            key = (str(row["_requested_symbol"]), int(row["date_ms"]))
            deduped[key] = row
        return [deduped[key] for key in sorted(deduped)]

    @staticmethod
    def normalize(
        request: MarketDataPullRequest,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[NormalizedBarRecord, ...]:
        requested = set(request.symbols)
        output: list[NormalizedBarRecord] = []
        for row in rows:
            source = str(row.get("_requested_symbol") or "").upper()
            if source not in requested:
                raise ValueError(f"HiThink returned unexpected symbol {source!r}")
            instant = datetime.fromtimestamp(int(row["date_ms"]) / 1000, tz=UTC)
            session = instant.astimezone(SHANGHAI).date()
            event_time = datetime.combine(session, time(9, 30), tzinfo=SHANGHAI).astimezone(UTC)
            available_at = datetime.combine(session, time(15, 15), tzinfo=SHANGHAI).astimezone(UTC)
            asset = AssetId(
                _internal_symbol(source),
                request.asset_type,
                venue=_venue(source, request.venue_overrides.get(source, "")),
                currency="CNY",
            )
            output.append(
                NormalizedBarRecord(
                    asset=asset,
                    bar=PriceBar(
                        event_time=event_time,
                        available_at=available_at,
                        open=numeric(row["open_price"], "open_price"),
                        high=numeric(row["high_price"], "high_price"),
                        low=numeric(row["low_price"], "low_price"),
                        close=numeric(row["close_price"], "close_price"),
                        volume=numeric(row.get("volume") or 0.0, "volume"),
                    ),
                    source_symbol=source,
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
        path, _ = self._endpoint(request.asset_type)
        return finalize_materialization(
            provider=self.PROVIDER,
            dataset=path.rsplit("/", 1)[-1],
            request=request,
            raw_records=rows,
            normalized_records=normalized,
            output_dir=output_dir,
            pulled_at=pulled_at,
            require_common_calendar=True,
        )
