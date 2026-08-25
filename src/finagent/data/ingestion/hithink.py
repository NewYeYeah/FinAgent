from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar

from .base import (
    MarketDataPullRequest,
    MaterializedMarketData,
    NormalizedBarRecord,
    finalize_materialization,
    numeric,
)
from .provider import HITHINK_CAPABILITIES

SHANGHAI = ZoneInfo("Asia/Shanghai")
Transport = Callable[[str, Mapping[str, str]], Mapping[str, object]]


def _venue(symbol: str) -> str:
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    mapping = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
    try:
        return mapping[suffix]
    except KeyError as exc:
        raise ValueError(f"cannot infer HiThink venue from {symbol!r}") from exc


def _day_from_ms(value: object) -> date:
    milliseconds = int(numeric(value, "date_ms"))
    return datetime.fromtimestamp(milliseconds / 1000.0, tz=UTC).astimezone(SHANGHAI).date()


def _default_transport(url: str, headers: Mapping[str, str]) -> Mapping[str, object]:
    request = Request(url, headers=dict(headers), method="GET")
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS base URL
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("HiThink response must be a JSON object")
    return payload


class HiThinkMarketDataIngestor:
    """Official HiThink A-share daily-bar adapter.

    The public Financial-API surface currently exposes daily historical bars and
    latest snapshots. This adapter intentionally does not claim minute/tick/Level-2
    or survivorship-bias-free delisted-history support.
    """

    PROVIDER = "hithink"
    CAPABILITIES = HITHINK_CAPABILITIES
    BASE_URL = "https://fuyao.aicubes.cn"

    def __init__(self, api_key: str, *, transport: Transport | None = None) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("HiThink API key must be non-empty")
        self.api_key = key
        self.transport = transport or _default_transport

    @classmethod
    def from_environment(cls) -> HiThinkMarketDataIngestor:
        key = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
        if not key:
            raise RuntimeError("HITHINK_FINANCE_API_KEY is required")
        return cls(key)

    def _request(self, path: str, params: Mapping[str, object]) -> Mapping[str, object]:
        url = f"{self.BASE_URL}{path}?{urlencode(params)}"
        payload = self.transport(url, {"X-api-key": self.api_key})
        code = int(payload.get("code", 0))
        if code != 0:
            raise RuntimeError(
                f"HiThink request failed code={code}: {payload.get('message', 'unknown error')}"
            )
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TypeError("HiThink response data must be an object")
        return data

    def fetch(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        if request.market.value != "a_share":
            raise ValueError("HiThinkMarketDataIngestor requires market='a_share'")
        if request.asset_type not in {AssetType.EQUITY, AssetType.ETF}:
            raise ValueError("HiThink daily ingestion supports only A-share equity/ETF")
        output: list[dict[str, object]] = []
        start_ms = int(datetime.combine(request.start, time.min, tzinfo=SHANGHAI).timestamp() * 1000)
        end_ms = int(datetime.combine(request.end, time.max, tzinfo=SHANGHAI).timestamp() * 1000)
        for symbol in request.symbols:
            data = self._request(
                "/api/a-share/prices/historical",
                {
                    "thscode": symbol,
                    "interval": "1d",
                    "start": start_ms,
                    "end": end_ms,
                    "adjust": "none",
                    "offset": 0,
                },
            )
            items = data.get("item")
            if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
                raise TypeError("HiThink historical data.item must be an array")
            for row in items:
                if not isinstance(row, Mapping):
                    raise TypeError("HiThink historical item must be an object")
                item = dict(row)
                item["_requested_symbol"] = symbol
                output.append(item)
        return output

    @staticmethod
    def normalize(
        request: MarketDataPullRequest,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[NormalizedBarRecord, ...]:
        requested = set(request.symbols)
        output: list[NormalizedBarRecord] = []
        for row in rows:
            source_symbol = str(row["_requested_symbol"]).upper()
            if source_symbol not in requested:
                raise ValueError(f"HiThink returned unexpected symbol {source_symbol!r}")
            day = _day_from_ms(row["date_ms"])
            event_time = datetime.combine(day, time(9, 30), tzinfo=SHANGHAI).astimezone(UTC)
            available_at = datetime.combine(day, time(16, 0), tzinfo=SHANGHAI).astimezone(UTC)
            asset = AssetId(
                source_symbol.split(".", 1)[0],
                request.asset_type,
                venue=request.venue_overrides.get(source_symbol, _venue(source_symbol)),
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
                    source_symbol=source_symbol,
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
            dataset="a_share_prices_historical_1d",
            request=request,
            raw_records=rows,
            normalized_records=normalized,
            output_dir=output_dir,
            pulled_at=pulled_at,
            require_common_calendar=True,
        )
