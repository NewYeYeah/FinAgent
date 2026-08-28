from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from types import MappingProxyType
from typing import Any, Mapping

from finagent.domain._validation import require_non_empty, require_positive
from finagent.domain.assets import AssetId

from .local_ashare import (
    SHANGHAI,
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    _duckdb,
    _sql_path,
    _ts_code_from_asset,
)


@dataclass(frozen=True, slots=True)
class AshareDailyCloseSnapshot:
    session_date: date
    asof: datetime
    marks: Mapping[AssetId, float]
    data_version: str

    def __post_init__(self) -> None:
        if self.asof.tzinfo is None or self.asof.utcoffset() is None:
            raise ValueError("A-share close snapshot asof must be timezone-aware")
        marks = {
            asset: require_positive(value, f"marks[{asset.key}]")
            for asset, value in self.marks.items()
        }
        object.__setattr__(self, "marks", MappingProxyType(marks))
        object.__setattr__(
            self,
            "data_version",
            require_non_empty(self.data_version, "data_version"),
        )

    def mark(self, asset: AssetId) -> float:
        try:
            return self.marks[asset]
        except KeyError as exc:
            raise KeyError(f"no exact-session close mark for {asset.key}") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "asof": self.asof.isoformat(),
            "data_version": self.data_version,
            "marks": {
                asset.key: value for asset, value in sorted(self.marks.items())
            },
        }


class LocalAshareDailyCloseAdapter:
    """Read exact daily close marks without stale-row or future-row fallback."""

    VERSION = "local-ashare-daily-close-v1"
    REQUIRED_COLUMNS = frozenset({"ts_code", "trade_date", "close", "pre_close"})

    def __init__(
        self,
        layout: LocalAshareDatasetLayout,
        *,
        data_version: str | None = None,
    ) -> None:
        layout.require(AshareBarFrequency.DAILY)
        self.layout = layout
        columns = frozenset(
            str(row[0])
            for row in _duckdb()
            .connect()
            .execute(
                "DESCRIBE SELECT * FROM read_parquet(?)",
                (str(layout.daily_path),),
            )
            .fetchall()
        )
        missing = self.REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(
                f"local A-share close data is missing columns: {sorted(missing)}"
            )
        fingerprint = layout.fast_fingerprint(AshareBarFrequency.DAILY)
        self._data_version = (
            data_version or f"local-ashare-close-fast-{fingerprint[:16]}"
        )

    @property
    def data_version(self) -> str:
        return self._data_version

    @staticmethod
    def _positive(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) and result > 0 else None

    def snapshot(
        self,
        session_date: date,
        universe: tuple[AssetId, ...],
    ) -> AshareDailyCloseSnapshot:
        if not universe or len(set(universe)) != len(universe):
            raise ValueError("A-share close universe must be non-empty and unique")
        codes = tuple(_ts_code_from_asset(asset) for asset in universe)
        placeholders = ", ".join("?" for _ in codes)
        rows = _duckdb().connect().execute(
            f"""
            SELECT CAST(ts_code AS VARCHAR), close, pre_close
            FROM read_parquet('{_sql_path(self.layout.daily_path)}')
            WHERE CAST(trade_date AS DATE) = ?
              AND ts_code IN ({placeholders})
            ORDER BY ts_code
            """,
            (session_date, *codes),
        ).fetchall()
        by_code: dict[str, float] = {}
        for code, close, previous in rows:
            key = str(code)
            if key in by_code:
                raise ValueError(
                    f"duplicate A-share close row for {key} on {session_date}"
                )
            mark = self._positive(close) or self._positive(previous)
            if mark is not None:
                by_code[key] = mark
        marks = {
            asset: by_code[code]
            for asset, code in zip(universe, codes, strict=True)
            if code in by_code
        }
        asof = datetime.combine(
            session_date,
            time(16, 0),
            tzinfo=SHANGHAI,
        ).astimezone(UTC)
        return AshareDailyCloseSnapshot(
            session_date=session_date,
            asof=asof,
            marks=marks,
            data_version=self.data_version,
        )
