from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar


class SQLitePriceStore:
    """Small PIT OHLCV store used by Phase 1 local research workflows."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS price_bars (
                    asset_key TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (asset_key, available_at)
                );
                CREATE INDEX IF NOT EXISTS idx_price_bars_available
                ON price_bars(available_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def upsert(self, asset: AssetId, bars: Iterable[PriceBar]) -> int:
        rows = [
            (
                asset.key,
                asset.symbol,
                asset.asset_type.value,
                asset.venue,
                asset.currency,
                bar.event_time.astimezone(timezone.utc).isoformat(),
                bar.available_at.astimezone(timezone.utc).isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
            )
            for bar in bars
        ]
        with self._connect() as con:
            con.executemany(
                """
                INSERT OR REPLACE INTO price_bars
                (asset_key, symbol, asset_type, venue, currency, event_time,
                 available_at, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def load(
        self,
        universe: tuple[AssetId, ...],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[AssetId, tuple[PriceBar, ...]]:
        result: dict[AssetId, tuple[PriceBar, ...]] = {}
        with self._connect() as con:
            for asset in universe:
                query = """
                    SELECT event_time, available_at, open, high, low, close, volume
                    FROM price_bars WHERE asset_key=?
                """
                params: list[object] = [asset.key]
                if start is not None:
                    query += " AND available_at >= ?"
                    params.append(start.astimezone(timezone.utc).isoformat())
                if end is not None:
                    query += " AND available_at < ?"
                    params.append(end.astimezone(timezone.utc).isoformat())
                query += " ORDER BY available_at"
                rows = con.execute(query, params).fetchall()
                if not rows:
                    raise KeyError(f"no stored bars for {asset.key}")
                result[asset] = tuple(
                    PriceBar(
                        event_time=datetime.fromisoformat(row[0]),
                        available_at=datetime.fromisoformat(row[1]),
                        open=float(row[2]),
                        high=float(row[3]),
                        low=float(row[4]),
                        close=float(row[5]),
                        volume=float(row[6]),
                    )
                    for row in rows
                )
        return result

    @property
    def content_digest(self) -> str:
        digest = hashlib.sha256()
        with self._connect() as con:
            rows = con.execute(
                """SELECT asset_key, event_time, available_at, open, high, low, close, volume
                   FROM price_bars ORDER BY asset_key, available_at"""
            )
            for row in rows:
                digest.update(repr(tuple(row)).encode("utf-8"))
        return digest.hexdigest()

    def list_assets(self) -> tuple[AssetId, ...]:
        with self._connect() as con:
            rows = con.execute(
                """SELECT DISTINCT symbol, asset_type, venue, currency
                   FROM price_bars ORDER BY asset_type, venue, symbol, currency"""
            ).fetchall()
        return tuple(
            AssetId(symbol, AssetType(asset_type), venue=venue, currency=currency)
            for symbol, asset_type, venue, currency in rows
        )
