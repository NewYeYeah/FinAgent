from __future__ import annotations

import os
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

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _venue_for_symbol(symbol: str, override: str = "") -> str:
    if override:
        return override.upper()
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    mapping = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
    try:
        return mapping[suffix]
    except KeyError as exc:
        raise ValueError(
            f"cannot infer A-share venue from {symbol!r}; provide venue_overrides"
        ) from exc


def _internal_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0].upper()


def _session_times(trade_date: str) -> tuple[datetime, datetime]:
    day = date.fromisoformat(
        f"{str(trade_date)[:4]}-{str(trade_date)[4:6]}-{str(trade_date)[6:8]}"
    )
    event_time = datetime.combine(day, time(9, 30), tzinfo=SHANGHAI).astimezone(UTC)
    # Tushare documents daily/fund_daily as post-close data. 16:00 local is a
    # conservative M1 availability convention and is recorded in the manifest.
    available_at = datetime.combine(day, time(16, 0), tzinfo=SHANGHAI).astimezone(UTC)
    return event_time, available_at


class TushareMarketDataIngestor:
    """Tushare daily ETF/equity ingestor with deterministic normalized output.

    Provider imports and credentials remain optional. Tests can inject a client with
    ``daily`` and/or ``fund_daily`` methods returning DataFrame-like values.
    """

    PROVIDER = "tushare"

    def __init__(self, client) -> None:
        self.client = client

    @classmethod
    def from_environment(cls) -> TushareMarketDataIngestor:
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            raise RuntimeError("TUSHARE_TOKEN is required")
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError(
                "Tushare support is optional; install the a-share extra"
            ) from exc
        return cls(ts.pro_api(token))

    @staticmethod
    def _endpoint(asset_type: AssetType) -> str:
        if asset_type is AssetType.ETF:
            return "fund_daily"
        if asset_type is AssetType.EQUITY:
            return "daily"
        raise ValueError("Tushare M1 supports only A-share equity/ETF daily bars")

    def fetch(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        if request.market.value != "a_share":
            raise ValueError("TushareMarketDataIngestor requires market='a_share'")
        endpoint_name = self._endpoint(request.asset_type)
        endpoint = getattr(self.client, endpoint_name, None)
        if not callable(endpoint):
            raise TypeError(f"Tushare client does not expose {endpoint_name}()")
        output: list[dict[str, object]] = []
        for symbol in request.symbols:
            response = endpoint(
                ts_code=symbol,
                start_date=request.start.strftime("%Y%m%d"),
                end_date=request.end.strftime("%Y%m%d"),
            )
            for row in frame_records(response):
                enriched = dict(row)
                enriched["_requested_symbol"] = symbol
                enriched["_endpoint"] = endpoint_name
                output.append(enriched)
        return output

    @staticmethod
    def normalize(
        request: MarketDataPullRequest,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[NormalizedBarRecord, ...]:
        output: list[NormalizedBarRecord] = []
        requested = set(request.symbols)
        for row in rows:
            source_symbol = str(row.get("ts_code") or row.get("_requested_symbol") or "").upper()
            if source_symbol not in requested:
                raise ValueError(f"Tushare returned unexpected symbol {source_symbol!r}")
            venue = _venue_for_symbol(
                source_symbol,
                request.venue_overrides.get(source_symbol, ""),
            )
            event_time, available_at = _session_times(str(row["trade_date"]))
            asset = AssetId(
                _internal_symbol(source_symbol),
                request.asset_type,
                venue=venue,
                currency="CNY",
            )
            output.append(
                NormalizedBarRecord(
                    asset=asset,
                    bar=PriceBar(
                        event_time=event_time,
                        available_at=available_at,
                        open=numeric(row["open"], "open"),
                        high=numeric(row["high"], "high"),
                        low=numeric(row["low"], "low"),
                        close=numeric(row["close"], "close"),
                        # Tushare daily/fund_daily reports volume in lots (手).
                        volume=numeric(row.get("vol") or 0.0, "vol") * 100.0,
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
            dataset=self._endpoint(request.asset_type),
            request=request,
            raw_records=rows,
            normalized_records=normalized,
            output_dir=output_dir,
            pulled_at=pulled_at,
            require_common_calendar=True,
        )
