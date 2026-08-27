from __future__ import annotations

from datetime import date
from pathlib import Path

from .local_ashare import (
    AshareInstrumentRecord,
    LocalAshareSecurityMaster as _StrictLocalAshareSecurityMaster,
    _asset_from_ts_code,
    _coerce_date,
    _duckdb,
    _file_fast_digest,
    _normalize_ts_code,
    _parquet_columns,
    _sql_path,
)
from .local_ashare_certification import (
    LocalAshareCertificationIssue,
    LocalAshareDatasetInspector as _BaseLocalAshareDatasetInspector,
)


class LocalAshareSecurityMaster(_StrictLocalAshareSecurityMaster):
    """Public local A-share master that quarantines legacy vendor identifiers.

    Modern FinAgent A-share identity remains six numeric digits plus ``.SH/.SZ/.BJ``.
    Historical vendor identifiers such as ``T00018.SH`` are not silently remapped to a
    modern security. They are excluded from the canonical candidate universe and
    reported through ``excluded_vendor_codes`` / ``limitations`` instead of aborting
    the complete local research dataset.
    """

    @classmethod
    def from_parquet(
        cls, path: str | Path, *, data_version: str | None = None
    ) -> LocalAshareSecurityMaster:
        path = Path(path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(path)
        columns = _parquet_columns(path)
        required = {"ts_code", "name", "list_date"}
        missing = required - columns
        if missing:
            raise ValueError(f"stock basic parquet is missing columns: {sorted(missing)}")

        optional = (
            "area",
            "industry",
            "market",
            "delist_date",
            "act_name",
            "act_ent_type",
            "list_status",
        )
        select = ["ts_code", "name", "list_date"]
        select.extend(name if name in columns else f"NULL AS {name}" for name in optional)
        sql = (
            f"SELECT {', '.join(select)} "
            f"FROM read_parquet('{_sql_path(path)}') ORDER BY ts_code"
        )
        rows = _duckdb().connect().execute(sql).fetchall()

        records: list[AshareInstrumentRecord] = []
        excluded: list[str] = []
        epoch_placeholders = 0
        delist_non_null = 0
        list_status_non_null = 0
        names = ("ts_code", "name", "list_date", *optional)

        for row in rows:
            values = dict(zip(names, row, strict=True))
            raw_code = str(values["ts_code"] or "").strip().upper()
            try:
                ts_code = _normalize_ts_code(raw_code)
            except ValueError:
                excluded.append(raw_code or repr(values["ts_code"]))
                continue

            list_day = _coerce_date(values["list_date"])
            if list_day == date(1970, 1, 1):
                epoch_placeholders += 1
                list_day = None
            delist_day = _coerce_date(values["delist_date"])
            if delist_day is not None:
                delist_non_null += 1
            if values["list_status"] not in {None, ""}:
                list_status_non_null += 1

            records.append(
                AshareInstrumentRecord(
                    asset=_asset_from_ts_code(ts_code),
                    ts_code=ts_code,
                    name=str(values["name"] or ""),
                    area=str(values["area"] or ""),
                    industry=str(values["industry"] or ""),
                    market=str(values["market"] or ""),
                    list_date=list_day,
                    delist_date=delist_day,
                    actual_controller=str(values["act_name"] or ""),
                    controller_type=str(values["act_ent_type"] or ""),
                )
            )

        limitations = [
            "candidate-only universe: vendor basic data is not certified as a complete PIT security master"
        ]
        if excluded:
            limitations.append(
                f"{len(excluded)} non-canonical vendor ts_code records were quarantined: "
                + ", ".join(excluded[:10])
            )
        if epoch_placeholders:
            limitations.append(
                f"{epoch_placeholders} list_date values used the 1970-01-01 placeholder"
            )
        if delist_non_null == 0:
            limitations.append("delist_date contains no observed values")
        if list_status_non_null == 0:
            limitations.append("list_status contains no observed values")

        version = data_version or f"local-basic-fast-{_file_fast_digest(path)[:16]}"
        master = cls(
            records,
            data_version=version,
            source_path=path,
            limitations=limitations,
        )
        master._excluded_vendor_codes = tuple(excluded)
        return master

    @property
    def excluded_vendor_codes(self) -> tuple[str, ...]:
        return getattr(self, "_excluded_vendor_codes", ())


class LocalAshareDatasetInspector(_BaseLocalAshareDatasetInspector):
    """Certification inspector with actionable legacy/anomaly diagnostics."""

    _CANONICAL_CODE_PATTERN = r"^[0-9]{6}\.(SH|SZ|BJ)$"

    def _inspect_basic(
        self, issues: list[LocalAshareCertificationIssue]
    ) -> dict[str, object]:
        result = super()._inspect_basic(issues)
        columns = set(result.get("columns", ()))
        if "ts_code" not in columns:
            return result

        con = _duckdb().connect()
        path = self.layout.basic_path
        count = con.execute(
            f"SELECT count(*) FROM read_parquet('{_sql_path(path)}') "
            "WHERE NOT regexp_matches(CAST(ts_code AS VARCHAR), ?)",
            (self._CANONICAL_CODE_PATTERN,),
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT CAST(ts_code AS VARCHAR), CAST(name AS VARCHAR), "
            f"CAST(list_date AS VARCHAR) FROM read_parquet('{_sql_path(path)}') "
            "WHERE NOT regexp_matches(CAST(ts_code AS VARCHAR), ?) "
            "ORDER BY CAST(ts_code AS VARCHAR) LIMIT 20",
            (self._CANONICAL_CODE_PATTERN,),
        ).fetchall()
        samples = [
            {"ts_code": str(code), "name": str(name or ""), "list_date": str(list_date or "")}
            for code, name, list_date in rows
        ]
        result["noncanonical_ts_codes"] = int(count or 0)
        result["noncanonical_samples"] = samples
        if count:
            issues.append(
                LocalAshareCertificationIssue(
                    "LA-BASIC-05",
                    f"basic parquet contains {count} non-canonical/legacy ts_code records; "
                    "they are quarantined from the canonical research universe",
                    "warning",
                )
            )
        return result

    def _inspect_daily(
        self, issues: list[LocalAshareCertificationIssue]
    ) -> dict[str, object]:
        result = super()._inspect_daily(issues)
        if not result.get("nonpositive_prices") and not result.get("invalid_ohlc"):
            result["anomaly_samples"] = []
            return result

        path = self.layout.daily_path
        rows = _duckdb().connect().execute(
            f"""
            SELECT CAST(ts_code AS VARCHAR), CAST(trade_date AS DATE),
                   open, high, low, close, pre_close, vol, amount, adj_factor
            FROM read_parquet('{_sql_path(path)}')
            WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR high < greatest(open, close, low)
               OR low > least(open, close, high)
            ORDER BY CAST(trade_date AS DATE), CAST(ts_code AS VARCHAR)
            LIMIT 20
            """
        ).fetchall()
        result["anomaly_samples"] = [
            {
                "ts_code": str(code),
                "trade_date": day.isoformat() if day is not None else None,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "pre_close": float(pre_close),
                "vol": float(vol),
                "amount": float(amount),
                "adj_factor": float(adj_factor),
            }
            for code, day, open_, high, low, close, pre_close, vol, amount, adj_factor in rows
        ]
        return result
