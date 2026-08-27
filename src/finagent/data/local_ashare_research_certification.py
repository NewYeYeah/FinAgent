from __future__ import annotations

from typing import Any

from .local_ashare import LocalAshareDatasetLayout, _duckdb, _parquet_columns, _sql_path
from .local_ashare_certification import LocalAshareCertificationIssue
from .local_ashare_compat import LocalAshareDatasetInspector as _BaseLocalAshareDatasetInspector


class LocalAshareDatasetInspector(_BaseLocalAshareDatasetInspector):
    """Certification semantics for the audited local A-share vendor dataset.

    A daily row with zero open/high/low and zero flow while carrying ``pre_close``
    forward in ``close`` is treated as a no-trade/suspension placeholder. It remains
    visible in the certification report but is not counted as invalid OHLC. Any other
    non-positive or inconsistent price row remains an error.
    """

    def __init__(self, layout: LocalAshareDatasetLayout) -> None:
        super().__init__(layout)

    @staticmethod
    def _placeholder_predicate() -> str:
        return (
            "open = 0 AND high = 0 AND low = 0 AND close > 0 AND pre_close > 0 "
            "AND abs(close - pre_close) <= 0.000000001 AND vol = 0 AND amount = 0"
        )

    @staticmethod
    def _sample_rows(
        con,
        path,
        predicate: str,
        columns: set[str],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        names = [
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
        ]
        for optional in ("suspend_timing", "suspend_type", "is_st"):
            if optional in columns:
                names.append(optional)
        rows = con.execute(
            f"""
            SELECT {', '.join(names)}
            FROM read_parquet('{_sql_path(path)}')
            WHERE {predicate}
            ORDER BY CAST(trade_date AS DATE), ts_code
            LIMIT {int(limit)}
            """
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            values = dict(zip(names, row, strict=True))
            values["trade_date"] = str(values["trade_date"])
            for name in (
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "vol",
                "amount",
                "adj_factor",
            ):
                if values.get(name) is not None:
                    values[name] = float(values[name])
            output.append(values)
        return output

    def _inspect_daily(
        self,
        issues: list[LocalAshareCertificationIssue],
    ) -> dict[str, object]:
        path = self.layout.daily_path
        columns = _parquet_columns(path)
        missing = self.DAILY_REQUIRED - columns
        if missing:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-DAILY-01",
                    f"daily parquet missing columns: {sorted(missing)}",
                )
            )
            return {"path": str(path.resolve()), "columns": sorted(columns)}

        placeholder = self._placeholder_predicate()
        bad_nonpositive = (
            f"(open <= 0 OR high <= 0 OR low <= 0 OR close <= 0) AND NOT ({placeholder})"
        )
        bad_ohlc = (
            f"(high < greatest(open, close, low) OR low > least(open, close, high)) "
            f"AND NOT ({placeholder})"
        )
        bad_any = (
            f"({bad_nonpositive}) OR ({bad_ohlc}) OR vol < 0 OR amount < 0 "
            "OR adj_factor IS NULL OR adj_factor <= 0"
        )

        con = _duckdb().connect()
        row = con.execute(
            f"""
            SELECT
                count(*) AS rows,
                count(DISTINCT ts_code) AS instruments,
                min(CAST(trade_date AS DATE)) AS start_date,
                max(CAST(trade_date AS DATE)) AS end_date,
                count(*) - count(
                    DISTINCT ts_code || '|' || CAST(CAST(trade_date AS DATE) AS VARCHAR)
                ) AS duplicate_keys,
                sum(CASE WHEN {placeholder} THEN 1 ELSE 0 END) AS suspension_placeholders,
                sum(CASE WHEN {bad_nonpositive} THEN 1 ELSE 0 END) AS nonpositive_prices,
                sum(CASE WHEN {bad_ohlc} THEN 1 ELSE 0 END) AS invalid_ohlc,
                sum(CASE WHEN vol < 0 OR amount < 0 THEN 1 ELSE 0 END) AS negative_flow,
                sum(CASE WHEN adj_factor IS NULL OR adj_factor <= 0 THEN 1 ELSE 0 END)
                    AS invalid_adj_factor
            FROM read_parquet('{_sql_path(path)}')
            """
        ).fetchone()
        assert row is not None
        result: dict[str, object] = {
            "path": str(path.resolve()),
            "columns": sorted(columns),
            "rows": int(row[0]),
            "instruments": int(row[1]),
            "start_date": str(row[2]),
            "end_date": str(row[3]),
            "duplicate_keys": int(row[4]),
            "suspension_placeholders": int(row[5] or 0),
            "nonpositive_prices": int(row[6] or 0),
            "invalid_ohlc": int(row[7] or 0),
            "negative_flow": int(row[8] or 0),
            "invalid_adj_factor": int(row[9] or 0),
            "vendor_volume_unit": "lots (100 shares)",
            "canonical_volume_unit": "shares",
            "vendor_amount_unit": "thousand CNY",
            "canonical_amount_unit": "CNY",
            "return_price": "raw close * adj_factor",
            "suspension_placeholder_rule": (
                "open=high=low=0, close=pre_close>0, vol=amount=0; non-tradable/no PriceBar"
            ),
        }
        result["suspension_placeholder_samples"] = self._sample_rows(
            con,
            path,
            placeholder,
            columns,
        )
        result["anomaly_samples"] = self._sample_rows(
            con,
            path,
            bad_any,
            columns,
        )

        if result["duplicate_keys"]:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-DAILY-02",
                    f"daily parquet duplicate_keys={result['duplicate_keys']}",
                )
            )
        if result["suspension_placeholders"]:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-DAILY-07",
                    f"daily parquet contains {result['suspension_placeholders']} audited "
                    "no-trade/suspension placeholder rows; the research adapter excludes "
                    "them from PriceBar construction",
                    "warning",
                )
            )
        for key, code in (
            ("nonpositive_prices", "LA-DAILY-03"),
            ("invalid_ohlc", "LA-DAILY-04"),
            ("negative_flow", "LA-DAILY-05"),
            ("invalid_adj_factor", "LA-DAILY-06"),
        ):
            if result[key]:
                issues.append(
                    LocalAshareCertificationIssue(
                        code,
                        f"daily parquet {key}={result[key]}",
                    )
                )
        return result
