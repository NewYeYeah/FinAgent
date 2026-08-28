from __future__ import annotations

import math
from datetime import UTC, date, datetime, time
from typing import Any

from finagent.domain.ashare_execution import (
    AshareDailyExecutionSnapshot,
    AshareSessionStatus,
    AshareTradeability,
    infer_ashare_board,
)
from finagent.domain.assets import AssetId

from .local_ashare import (
    SHANGHAI,
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    _duckdb,
    _sql_path,
    _ts_code_from_asset,
)
from .local_ashare_research_adapter import is_daily_nontrading_placeholder


class LocalAshareDailyExecutionAdapter:
    """Read exact daily A-share execution states from immutable vendor Parquet.

    Research adapters intentionally remove suspension placeholders and can return the
    latest earlier tradable bar. Execution cannot do that: this adapter queries one
    exact market session and preserves missing/suspended states so a stale quote can
    never be interpreted as executable.
    """

    REQUIRED_COLUMNS = frozenset(
        {
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "vol",
            "amount",
        }
    )
    OPTIONAL_COLUMNS = (
        "up_limit",
        "down_limit",
        "is_st",
        "suspend_type",
        "suspend_timing",
    )

    def __init__(
        self,
        layout: LocalAshareDatasetLayout,
        *,
        data_version: str | None = None,
        require_price_limits: bool = True,
    ) -> None:
        layout.require(AshareBarFrequency.DAILY)
        self.layout = layout
        self.require_price_limits = bool(require_price_limits)
        columns = tuple(
            row[0]
            for row in _duckdb()
            .connect()
            .execute(
                "DESCRIBE SELECT * FROM read_parquet(?)",
                (str(layout.daily_path),),
            )
            .fetchall()
        )
        self._columns = frozenset(str(value) for value in columns)
        missing = self.REQUIRED_COLUMNS - self._columns
        if missing:
            raise ValueError(
                f"local A-share execution data is missing columns: {sorted(missing)}"
            )
        fingerprint = layout.fast_fingerprint(AshareBarFrequency.DAILY)
        self._data_version = (
            data_version or f"local-ashare-execution-fast-{fingerprint[:16]}"
        )

    @property
    def data_version(self) -> str:
        return self._data_version

    @staticmethod
    def _positive_or_none(value: object) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None

    @staticmethod
    def _finite(value: object, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    def _query(
        self,
        session_date: date,
        universe: tuple[AssetId, ...],
    ) -> dict[str, dict[str, Any]]:
        codes = tuple(_ts_code_from_asset(asset) for asset in universe)
        placeholders = ", ".join("?" for _ in codes)
        selected = [*sorted(self.REQUIRED_COLUMNS)]
        selected.extend(
            name for name in self.OPTIONAL_COLUMNS if name in self._columns
        )
        sql = f"""
        SELECT {', '.join(selected)}
        FROM read_parquet('{_sql_path(self.layout.daily_path)}')
        WHERE CAST(trade_date AS DATE) = ?
          AND ts_code IN ({placeholders})
        ORDER BY ts_code
        """
        rows = _duckdb().connect().execute(sql, (session_date, *codes)).fetchall()
        output: dict[str, dict[str, Any]] = {}
        for row in rows:
            values = dict(zip(selected, row, strict=True))
            code = str(values["ts_code"])
            if code in output:
                raise ValueError(
                    f"duplicate A-share execution row for {code} on {session_date}"
                )
            output[code] = values
        return output

    @staticmethod
    def _invalid_ohlc(row: dict[str, Any]) -> bool:
        values = [
            LocalAshareDailyExecutionAdapter._positive_or_none(row.get(name))
            for name in ("open", "high", "low", "close")
        ]
        if any(value is None for value in values):
            return True
        open_, high, low, close = (float(value) for value in values)
        return high < max(open_, close) or low > min(open_, close) or high < low

    def snapshot(
        self,
        session_date: date,
        universe: tuple[AssetId, ...],
    ) -> AshareDailyExecutionSnapshot:
        if not universe or len(set(universe)) != len(universe):
            raise ValueError("A-share execution universe must be non-empty and unique")
        observed_at = datetime.combine(session_date, time(9, 30), tzinfo=SHANGHAI).astimezone(UTC)
        rows = self._query(session_date, universe)
        states: dict[AssetId, AshareTradeability] = {}

        for asset in universe:
            board = infer_ashare_board(asset)
            code = _ts_code_from_asset(asset)
            row = rows.get(code)
            if row is None:
                states[asset] = AshareTradeability(
                    asset=asset,
                    board=board,
                    session_date=session_date,
                    observed_at=observed_at,
                    status=AshareSessionStatus.NO_SESSION_DATA,
                    metadata={"source": "local_ashare_parquet_exact_session"},
                )
                continue

            previous_close = self._positive_or_none(row.get("pre_close"))
            close = self._positive_or_none(row.get("close"))
            if is_daily_nontrading_placeholder(row):
                states[asset] = AshareTradeability(
                    asset=asset,
                    board=board,
                    session_date=session_date,
                    observed_at=observed_at,
                    status=AshareSessionStatus.SUSPENDED,
                    mark_price=close or previous_close,
                    previous_close=previous_close,
                    volume=0.0,
                    is_st=bool(self._finite(row.get("is_st"))),
                    metadata={
                        "source": "local_ashare_parquet_exact_session",
                        "vendor_encoding": "daily_nontrading_placeholder",
                    },
                )
                continue

            execution_price = self._positive_or_none(row.get("open"))
            mark_price = execution_price or close or previous_close
            upper_limit = self._positive_or_none(row.get("up_limit"))
            lower_limit = self._positive_or_none(row.get("down_limit"))
            if self._invalid_ohlc(row):
                status = AshareSessionStatus.INVALID_PRICE
            elif upper_limit is None or lower_limit is None:
                status = AshareSessionStatus.LIMITS_UNAVAILABLE
            else:
                status = AshareSessionStatus.TRADABLE
            volume = max(0.0, self._finite(row.get("vol")) * 100.0)
            amount = max(0.0, self._finite(row.get("amount")) * 1000.0)
            states[asset] = AshareTradeability(
                asset=asset,
                board=board,
                session_date=session_date,
                observed_at=observed_at,
                status=status,
                execution_price=execution_price,
                mark_price=mark_price,
                previous_close=previous_close,
                upper_limit=upper_limit,
                lower_limit=lower_limit,
                volume=volume,
                is_st=bool(self._finite(row.get("is_st"))),
                metadata={
                    "source": "local_ashare_parquet_exact_session",
                    "amount_cny": repr(amount),
                    "close": repr(close) if close is not None else "",
                    "require_price_limits": repr(self.require_price_limits),
                },
            )

        return AshareDailyExecutionSnapshot(
            session_date=session_date,
            asof=observed_at,
            states=states,
            data_version=self.data_version,
            metadata={
                "adapter": self.__class__.__name__,
                "frequency": AshareBarFrequency.DAILY.value,
                "execution_price_field": "open",
                "session_semantics": "exact_row_no_stale_quote_fallback",
                "price_limit_source": "vendor_up_limit_down_limit",
            },
        )
