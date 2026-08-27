from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping

from .local_ashare import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    _duckdb,
    _normalize_ts_code,
    _parquet_columns,
    _sql_path,
)


@dataclass(frozen=True, slots=True)
class LocalAshareCertificationIssue:
    code: str
    message: str
    severity: str = "error"

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("certification issue code/message must be non-empty")
        if self.severity not in {"error", "warning"}:
            raise ValueError("severity must be error or warning")


@dataclass(frozen=True, slots=True)
class LocalAshareCertificationReport:
    data_version: str
    root: str
    basic: Mapping[str, object]
    daily: Mapping[str, object]
    intraday: Mapping[str, object] = field(default_factory=dict)
    reconciliation: Mapping[str, object] = field(default_factory=dict)
    issues: tuple[LocalAshareCertificationIssue, ...] = ()
    schema_version: str = "finagent.local-ashare-certification.v1"

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "data_version": self.data_version,
            "root": self.root,
            "basic": dict(self.basic),
            "daily": dict(self.daily),
            "intraday": dict(self.intraday),
            "reconciliation": dict(self.reconciliation),
            "issues": [
                {"code": issue.code, "message": issue.message, "severity": issue.severity}
                for issue in self.issues
            ],
        }

    def write_json(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output


class LocalAshareDatasetInspector:
    BASIC_REQUIRED = {"ts_code", "name", "market", "list_date"}
    DAILY_REQUIRED = {
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "vol",
        "amount",
        "adj_factor",
    }
    INTRADAY_REQUIRED = {
        "ts_code",
        "trade_date",
        "trade_time",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "adj_factor",
    }

    def __init__(self, layout: LocalAshareDatasetLayout) -> None:
        self.layout = layout
        layout.require(AshareBarFrequency.DAILY)

    def inspect(
        self,
        *,
        intraday_symbol: str | None = None,
        intraday_date: date | None = None,
        frequency: AshareBarFrequency = AshareBarFrequency.MINUTE_1,
    ) -> LocalAshareCertificationReport:
        issues: list[LocalAshareCertificationIssue] = []
        basic = self._inspect_basic(issues)
        daily = self._inspect_daily(issues)
        intraday: dict[str, object] = {}
        reconciliation: dict[str, object] = {}
        if intraday_symbol is not None:
            ts_code = _normalize_ts_code(intraday_symbol)
            intraday, selected_date = self._inspect_intraday(
                ts_code, intraday_date, frequency, issues
            )
            if selected_date is not None:
                reconciliation = self._reconcile(ts_code, selected_date, frequency, issues)
        version = (
            "local-ashare-cert-fast-"
            f"{self.layout.fast_fingerprint(AshareBarFrequency.DAILY)[:16]}"
        )
        return LocalAshareCertificationReport(
            data_version=version,
            root=str(self.layout.root.resolve()),
            basic=basic,
            daily=daily,
            intraday=intraday,
            reconciliation=reconciliation,
            issues=tuple(issues),
        )

    def _inspect_basic(
        self, issues: list[LocalAshareCertificationIssue]
    ) -> dict[str, object]:
        path = self.layout.basic_path
        columns = _parquet_columns(path)
        missing = self.BASIC_REQUIRED - columns
        if missing:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-BASIC-01", f"basic parquet missing columns: {sorted(missing)}"
                )
            )
            return {"path": str(path.resolve()), "columns": sorted(columns)}
        con = _duckdb().connect()
        sql = f"""
        SELECT
            count(*) AS rows,
            count(DISTINCT ts_code) AS instruments,
            count(*) - count(DISTINCT ts_code) AS duplicate_codes,
            sum(CASE WHEN CAST(list_date AS DATE) = DATE '1970-01-01' THEN 1 ELSE 0 END)
                AS epoch_list_dates,
            sum(CASE WHEN list_date IS NULL THEN 1 ELSE 0 END) AS null_list_dates,
            {self._nonnull_expr(columns, 'delist_date')} AS nonnull_delist_dates,
            {self._nonnull_expr(columns, 'list_status')} AS nonnull_list_status
        FROM read_parquet('{_sql_path(path)}')
        """
        row = con.execute(sql).fetchone()
        assert row is not None
        result = {
            "path": str(path.resolve()),
            "columns": sorted(columns),
            "rows": int(row[0]),
            "instruments": int(row[1]),
            "duplicate_codes": int(row[2]),
            "epoch_list_dates": int(row[3] or 0),
            "null_list_dates": int(row[4] or 0),
            "nonnull_delist_dates": int(row[5] or 0),
            "nonnull_list_status": int(row[6] or 0),
            "survivorship_certified": False,
        }
        if result["duplicate_codes"]:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-BASIC-02",
                    f"basic parquet contains {result['duplicate_codes']} duplicate ts_code rows",
                )
            )
        if result["epoch_list_dates"]:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-BASIC-03",
                    f"basic parquet contains {result['epoch_list_dates']} "
                    "1970-01-01 list-date placeholders",
                    "warning",
                )
            )
        if result["nonnull_delist_dates"] == 0 or result["nonnull_list_status"] == 0:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-BASIC-04",
                    "basic parquet cannot certify survivorship-free history because "
                    "delist/list-status coverage is absent",
                    "warning",
                )
            )
        return result

    def _inspect_daily(
        self, issues: list[LocalAshareCertificationIssue]
    ) -> dict[str, object]:
        path = self.layout.daily_path
        columns = _parquet_columns(path)
        missing = self.DAILY_REQUIRED - columns
        if missing:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-DAILY-01", f"daily parquet missing columns: {sorted(missing)}"
                )
            )
            return {"path": str(path.resolve()), "columns": sorted(columns)}
        con = _duckdb().connect()
        sql = f"""
        SELECT
            count(*) AS rows,
            count(DISTINCT ts_code) AS instruments,
            min(CAST(trade_date AS DATE)) AS start_date,
            max(CAST(trade_date AS DATE)) AS end_date,
            count(*) - count(
                DISTINCT ts_code || '|' || CAST(CAST(trade_date AS DATE) AS VARCHAR)
            ) AS duplicate_keys,
            sum(CASE WHEN open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                THEN 1 ELSE 0 END) AS nonpositive_prices,
            sum(CASE WHEN high < greatest(open, close, low)
                OR low > least(open, close, high) THEN 1 ELSE 0 END) AS invalid_ohlc,
            sum(CASE WHEN vol < 0 OR amount < 0 THEN 1 ELSE 0 END) AS negative_flow,
            sum(CASE WHEN adj_factor IS NULL OR adj_factor <= 0
                THEN 1 ELSE 0 END) AS invalid_adj_factor
        FROM read_parquet('{_sql_path(path)}')
        """
        row = con.execute(sql).fetchone()
        assert row is not None
        result = {
            "path": str(path.resolve()),
            "columns": sorted(columns),
            "rows": int(row[0]),
            "instruments": int(row[1]),
            "start_date": _iso(row[2]),
            "end_date": _iso(row[3]),
            "duplicate_keys": int(row[4]),
            "nonpositive_prices": int(row[5] or 0),
            "invalid_ohlc": int(row[6] or 0),
            "negative_flow": int(row[7] or 0),
            "invalid_adj_factor": int(row[8] or 0),
            "vendor_volume_unit": "lots (100 shares)",
            "canonical_volume_unit": "shares",
            "vendor_amount_unit": "thousand CNY",
            "canonical_amount_unit": "CNY",
            "return_price": "raw close * adj_factor",
        }
        for key, code in (
            ("duplicate_keys", "LA-DAILY-02"),
            ("nonpositive_prices", "LA-DAILY-03"),
            ("invalid_ohlc", "LA-DAILY-04"),
            ("negative_flow", "LA-DAILY-05"),
            ("invalid_adj_factor", "LA-DAILY-06"),
        ):
            if result[key]:
                issues.append(
                    LocalAshareCertificationIssue(code, f"daily parquet {key}={result[key]}")
                )
        return result

    def _inspect_intraday(
        self,
        ts_code: str,
        selected_date: date | None,
        frequency: AshareBarFrequency,
        issues: list[LocalAshareCertificationIssue],
    ) -> tuple[dict[str, object], date | None]:
        path = self.layout.intraday_path(frequency, ts_code)
        if not path.is_file():
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-INTRA-01", f"intraday sample file does not exist: {path}"
                )
            )
            return {}, None
        columns = _parquet_columns(path)
        missing = self.INTRADAY_REQUIRED - columns
        if missing:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-INTRA-02", f"intraday parquet missing columns: {sorted(missing)}"
                )
            )
            return {"path": str(path.resolve()), "columns": sorted(columns)}, None
        con = _duckdb().connect()
        if selected_date is None:
            selected_date = con.execute(
                f"SELECT min(CAST(trade_date AS DATE)) "
                f"FROM read_parquet('{_sql_path(path)}')"
            ).fetchone()[0]
        rows = con.execute(
            f"""
            SELECT CAST(trade_time AS TIMESTAMP), open, high, low, close,
                   vol, amount, adj_factor
            FROM read_parquet('{_sql_path(path)}')
            WHERE CAST(trade_date AS DATE) = ?
            ORDER BY CAST(trade_time AS TIMESTAMP)
            """,
            (selected_date,),
        ).fetchall()
        times = [row[0].strftime("%H:%M") for row in rows]
        zero_volume = sum(1 for row in rows if float(row[5]) == 0.0)
        result = {
            "path": str(path.resolve()),
            "ts_code": ts_code,
            "frequency": frequency.value,
            "date": selected_date.isoformat() if selected_date else None,
            "rows": len(rows),
            "first_time": times[0] if times else None,
            "last_time": times[-1] if times else None,
            "zero_volume_rows": zero_volume,
            "opening_auction_row": bool(times and times[0] == "09:30"),
            "timestamp_convention": (
                "bar-end; 09:30 is a separate opening-auction observation"
            ),
            "canonical_continuous_rows": max(
                len(rows) - (1 if times and times[0] == "09:30" else 0), 0
            ),
        }
        if frequency is AshareBarFrequency.MINUTE_1:
            expected = _expected_1min_times()
            if times != expected:
                issues.append(
                    LocalAshareCertificationIssue(
                        "LA-INTRA-03",
                        "1-minute sample does not match audited 241-row sequence: "
                        "09:30 auction, 09:31-11:30, 13:01-15:00",
                    )
                )
            if len(rows) == 241 and result["canonical_continuous_rows"] == 240:
                issues.append(
                    LocalAshareCertificationIssue(
                        "LA-INTRA-04",
                        "09:30 opening-auction row is excluded from continuous-minute "
                        "research by default",
                        "warning",
                    )
                )
        return result, selected_date

    def _reconcile(
        self,
        ts_code: str,
        selected_date: date,
        frequency: AshareBarFrequency,
        issues: list[LocalAshareCertificationIssue],
    ) -> dict[str, object]:
        path = self.layout.intraday_path(frequency, ts_code)
        con = _duckdb().connect()
        minute = con.execute(
            f"""
            SELECT
                first(open ORDER BY CAST(trade_time AS TIMESTAMP)),
                max(high),
                min(low),
                first(close ORDER BY CAST(trade_time AS TIMESTAMP) DESC),
                sum(vol),
                sum(amount),
                min(adj_factor),
                max(adj_factor)
            FROM read_parquet('{_sql_path(path)}')
            WHERE CAST(trade_date AS DATE) = ?
            """,
            (selected_date,),
        ).fetchone()
        daily = con.execute(
            f"""
            SELECT open, high, low, close, vol, amount, adj_factor
            FROM read_parquet('{_sql_path(self.layout.daily_path)}')
            WHERE ts_code = ? AND CAST(trade_date AS DATE) = ?
            """,
            (ts_code, selected_date),
        ).fetchone()
        if minute is None or daily is None:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-REC-01", "daily/intraday reconciliation row is unavailable"
                )
            )
            return {}
        expected = {
            "open": float(daily[0]),
            "high": float(daily[1]),
            "low": float(daily[2]),
            "close": float(daily[3]),
            "volume_shares": float(daily[4]) * 100.0,
            "amount_cny": float(daily[5]) * 1000.0,
            "adj_factor": float(daily[6]),
        }
        observed = {
            "open": float(minute[0]),
            "high": float(minute[1]),
            "low": float(minute[2]),
            "close": float(minute[3]),
            "volume_shares": float(minute[4]),
            "amount_cny": float(minute[5]),
            "adj_factor_min": float(minute[6]),
            "adj_factor_max": float(minute[7]),
        }
        tolerances = {
            "price": 1e-9,
            "volume_shares": 100.0,
            "amount_cny": 1000.0,
            "adj_factor": 1e-9,
        }
        passed = (
            all(
                math.isclose(observed[name], expected[name], abs_tol=tolerances["price"])
                for name in ("open", "high", "low", "close")
            )
            and abs(observed["volume_shares"] - expected["volume_shares"])
            <= tolerances["volume_shares"]
            and abs(observed["amount_cny"] - expected["amount_cny"])
            <= tolerances["amount_cny"]
            and math.isclose(
                observed["adj_factor_min"],
                expected["adj_factor"],
                abs_tol=tolerances["adj_factor"],
            )
            and math.isclose(
                observed["adj_factor_max"],
                expected["adj_factor"],
                abs_tol=tolerances["adj_factor"],
            )
        )
        if not passed:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-REC-02",
                    f"daily/minute OHLCV reconciliation failed for {ts_code} "
                    f"{selected_date}",
                )
            )
        return {
            "passed": passed,
            "ts_code": ts_code,
            "date": selected_date.isoformat(),
            "observed_intraday": observed,
            "expected_daily_normalized": expected,
            "tolerances": tolerances,
        }

    @staticmethod
    def _nonnull_expr(columns: set[str], name: str) -> str:
        if name not in columns:
            return "0"
        return f"sum(CASE WHEN {name} IS NOT NULL THEN 1 ELSE 0 END)"


def _expected_1min_times() -> list[str]:
    values = ["09:30"]
    cursor = datetime(2000, 1, 1, 9, 31)
    end = datetime(2000, 1, 1, 11, 30)
    while cursor <= end:
        values.append(cursor.strftime("%H:%M"))
        cursor += timedelta(minutes=1)
    cursor = datetime(2000, 1, 1, 13, 1)
    end = datetime(2000, 1, 1, 15, 0)
    while cursor <= end:
        values.append(cursor.strftime("%H:%M"))
        cursor += timedelta(minutes=1)
    return values


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
