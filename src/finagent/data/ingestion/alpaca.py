from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, time
from pathlib import Path
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

NEW_YORK = ZoneInfo("America/New_York")


def _value(bar: object, name: str) -> object:
    if isinstance(bar, Mapping):
        return bar[name]
    return getattr(bar, name)


def _bar_payload(symbol: str, bar: object) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": _value(bar, "timestamp"),
        "open": _value(bar, "open"),
        "high": _value(bar, "high"),
        "low": _value(bar, "low"),
        "close": _value(bar, "close"),
        "volume": _value(bar, "volume"),
    }


def _aware_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Alpaca bar timestamp must be timezone-aware")
    return parsed


class AlpacaMarketDataIngestor:
    """Alpaca daily-bar ingestor for US equity/ETF M1 studies."""

    PROVIDER = "alpaca"

    def __init__(self, client, *, request_builder: Callable | None = None) -> None:
        self.client = client
        self.request_builder = request_builder

    @classmethod
    def from_environment(cls) -> AlpacaMarketDataIngestor:
        key = os.environ.get("ALPACA_API_KEY", "").strip()
        secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key or not secret:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        try:
            from alpaca.data.historical import StockHistoricalDataClient
        except ImportError as exc:
            raise RuntimeError(
                "Alpaca support is optional; install the us-market extra"
            ) from exc
        return cls(StockHistoricalDataClient(key, secret))

    @staticmethod
    def _sdk_request(request: MarketDataPullRequest):
        try:
            from alpaca.data.enums import Adjustment, DataFeed
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
        except ImportError as exc:
            raise RuntimeError(
                "Alpaca support is optional; install the us-market extra"
            ) from exc
        feed_name = (request.feed or "iex").upper()
        try:
            feed = DataFeed[feed_name]
        except KeyError as exc:
            raise ValueError(f"unsupported Alpaca feed {request.feed!r}") from exc
        return StockBarsRequest(
            symbol_or_symbols=list(request.symbols),
            timeframe=TimeFrame.Day,
            start=datetime.combine(request.start, time.min, tzinfo=UTC),
            end=datetime.combine(request.end, time.max, tzinfo=UTC),
            adjustment=Adjustment.RAW,
            feed=feed,
        )

    def fetch(self, request: MarketDataPullRequest) -> list[dict[str, object]]:
        if request.market.value != "us_equity":
            raise ValueError("AlpacaMarketDataIngestor requires market='us_equity'")
        if request.asset_type not in {AssetType.EQUITY, AssetType.ETF}:
            raise ValueError("Alpaca M1 supports only US equity/ETF daily bars")
        builder = self.request_builder or self._sdk_request
        response = self.client.get_stock_bars(builder(request))
        data = getattr(response, "data", response)
        if not isinstance(data, Mapping):
            raise TypeError("Alpaca response must expose a symbol -> bars mapping")
        output: list[dict[str, object]] = []
        for symbol, bars in data.items():
            for bar in bars:
                output.append(_bar_payload(str(symbol).upper(), bar))
        return output

    @staticmethod
    def normalize(
        request: MarketDataPullRequest,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[NormalizedBarRecord, ...]:
        output: list[NormalizedBarRecord] = []
        requested = set(request.symbols)
        for row in rows:
            symbol = str(row["symbol"]).upper()
            if symbol not in requested:
                raise ValueError(f"Alpaca returned unexpected symbol {symbol!r}")
            timestamp = _aware_datetime(row["timestamp"])
            session_date = timestamp.astimezone(NEW_YORK).date()
            event_time = datetime.combine(
                session_date, time(9, 30), tzinfo=NEW_YORK
            ).astimezone(UTC)
            # A conservative daily-bar completion timestamp for regular-session M1.
            available_at = datetime.combine(
                session_date, time(16, 15), tzinfo=NEW_YORK
            ).astimezone(UTC)
            venue = request.venue_overrides.get(symbol, "XNAS")
            asset = AssetId(
                symbol,
                request.asset_type,
                venue=venue,
                currency="USD",
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
                        volume=numeric(row.get("volume") or 0.0, "volume"),
                    ),
                    source_symbol=symbol,
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
            dataset="stock_bars_1day",
            request=request,
            raw_records=rows,
            normalized_records=normalized,
            output_dir=output_dir,
            pulled_at=pulled_at,
            require_common_calendar=True,
        )
