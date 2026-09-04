from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import median

from finagent.data.minute_store.execution import (
    DEFAULT_DUCKDB_EXECUTION_POLICY,
    DuckDBExecutionPolicy,
)
from finagent.data.minute_store.manifest import MinuteStoreManifest
from finagent.data.minute_store.materialize import fetch_plan_rows
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _membership_sha256(values: Sequence[date]) -> str:
    payload = "\n".join(item.isoformat() for item in sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be integer-like")
    try:
        rendered = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be integer-like") from exc
    return rendered


def _string_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(_text(item, f"{field_name}[]") for item in value)


def _optional_date(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _calendar_rows_sql(
    calendar: TradingCalendarEvidence,
    partition_months: frozenset[str],
) -> str:
    rows: list[str] = []
    for session in calendar.sessions:
        month = session.session_date.strftime("%Y-%m")
        if month not in partition_months:
            continue
        rows.append(
            "("
            f"DATE {_sql_string(session.session_date.isoformat())}, "
            f"TIMESTAMPTZ {_sql_string(session.open_at.isoformat())}, "
            f"TIMESTAMPTZ {_sql_string(session.close_at.isoformat())}, "
            f"{session.regular_minutes}"
            ")"
        )
    if not rows:
        raise ValueError("calendar does not intersect the minute-store partitions")
    return ",\n                ".join(rows)


@dataclass(frozen=True, slots=True)
class USRegimeCorpusInventoryPlan:
    manifest_id: str
    data_version: str
    calendar_id: str
    assets: tuple[str, ...]
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    sql: str
    output_columns: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-corpus-inventory-plan.v1"

    def __post_init__(self) -> None:
        for field_name in ("manifest_id", "data_version", "calendar_id", "sql"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        assets = tuple(sorted(dict.fromkeys(_text(item, "assets[]") for item in self.assets)))
        if not assets:
            raise ValueError("US-R2 corpus inventory requires at least one asset")
        months = tuple(sorted(dict.fromkeys(_text(item, "partition_months[]") for item in self.partition_months)))
        if not months:
            raise ValueError("US-R2 corpus inventory requires at least one partition")
        if self.selected_size_bytes < 0:
            raise ValueError("selected_size_bytes must be >= 0")
        if not self.output_columns:
            raise ValueError("output_columns cannot be empty")
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "partition_months", months)

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "manifest_id": self.manifest_id,
                "data_version": self.data_version,
                "calendar_id": self.calendar_id,
                "assets": list(self.assets),
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
                "scan_strategy": (
                    "single_read_parquet_relation_asset_pushdown_regular_session_preaggregation"
                ),
            },
            prefix="us-r2-corpus-inventory-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "manifest_id": self.manifest_id,
            "data_version": self.data_version,
            "calendar_id": self.calendar_id,
            "assets": list(self.assets),
            "asset_count": len(self.assets),
            "partition_months": list(self.partition_months),
            "partition_count": len(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "output_columns": list(self.output_columns),
            "scan_strategy": (
                "single_read_parquet_relation_asset_pushdown_regular_session_preaggregation"
            ),
            "candidate_dependent_scan": False,
            "source_rows_emitted": False,
        }


def build_us_r2_corpus_inventory_plan(
    manifest: MinuteStoreManifest,
    calendar: TradingCalendarEvidence,
    assets: Sequence[str],
) -> USRegimeCorpusInventoryPlan:
    normalized_assets = tuple(sorted(dict.fromkeys(item.strip() for item in assets if item.strip())))
    if not normalized_assets:
        raise ValueError("US-R2 corpus inventory requires non-empty assets")
    if manifest.market_id != calendar.market_id:
        raise ValueError("minute-store/calendar market identity mismatch")
    if manifest.timezone != calendar.timezone:
        raise ValueError("minute-store/calendar timezone mismatch")

    partition_months = tuple(item.month for item in manifest.partitions)
    partition_month_set = frozenset(partition_months)
    path_list = ", ".join(_sql_string(item.path.as_posix()) for item in manifest.partitions)
    asset_list = ", ".join(_sql_string(item) for item in normalized_assets)
    calendar_values = _calendar_rows_sql(calendar, partition_month_set)

    output_columns = (
        "research_asset_id",
        "partition_month",
        "first_session_date",
        "last_session_date",
        "observed_session_count",
        "complete_session_count",
        "observed_regular_minute_count",
        "conflicting_key_count",
        "invalid_key_count",
        "exact_duplicate_extra_row_count",
        "observed_session_dates",
        "complete_session_dates",
        "first_event_time",
        "last_event_time",
    )

    # This query is deliberately not built from MinuteQueryPlan. R2-0 needs coverage
    # evidence, not source rows. The target symbols are pushed into one read_parquet
    # relation, XNYS regular-session filtering happens before duplicate aggregation,
    # and Python receives only asset-month aggregates. The scan therefore does not
    # multiply by the R1 37-candidate denominator.
    sql = f"""
        WITH calendar(session_date, open_at, close_at, expected_regular_minutes) AS (
            VALUES
                {calendar_values}
        ),
        base AS (
            SELECT
                p.timestamp,
                p.open,
                p.high,
                p.low,
                p.close,
                p.volume,
                p.ticker,
                c.session_date,
                c.expected_regular_minutes
            FROM read_parquet([{path_list}]) AS p
            INNER JOIN calendar AS c
                ON CAST(timezone({_sql_string(calendar.timezone)}, p.timestamp) AS DATE)
                   = c.session_date
               AND p.timestamp >= c.open_at
               AND p.timestamp < c.close_at
            WHERE p.ticker IN ({asset_list})
        ),
        keyed AS (
            SELECT
                ticker,
                timestamp,
                session_date,
                MAX(expected_regular_minutes) AS expected_regular_minutes,
                COUNT(*) AS raw_row_count,
                COUNT(DISTINCT struct_pack(
                    open := open,
                    high := high,
                    low := low,
                    close := close,
                    volume := volume
                )) AS variant_count,
                MIN(open) AS open_value,
                MIN(high) AS high_value,
                MIN(low) AS low_value,
                MIN(close) AS close_value,
                MIN(volume) AS volume_value
            FROM base
            GROUP BY ticker, timestamp, session_date
        ),
        classified AS (
            SELECT
                *,
                variant_count = 1
                AND open_value IS NOT NULL
                AND high_value IS NOT NULL
                AND low_value IS NOT NULL
                AND close_value IS NOT NULL
                AND open_value > 0
                AND high_value > 0
                AND low_value > 0
                AND close_value > 0
                AND high_value >= GREATEST(open_value, low_value, close_value)
                AND low_value <= LEAST(open_value, high_value, close_value)
                AND volume_value IS NOT NULL
                AND volume_value >= 0 AS clean_key
            FROM keyed
        ),
        session_coverage AS (
            SELECT
                ticker,
                session_date,
                MAX(expected_regular_minutes) AS expected_regular_minutes,
                COUNT(*) FILTER (WHERE clean_key) AS observed_regular_minute_count,
                SUM(CASE WHEN variant_count > 1 THEN 1 ELSE 0 END) AS conflicting_key_count,
                SUM(CASE WHEN variant_count = 1 AND NOT clean_key THEN 1 ELSE 0 END)
                    AS invalid_key_count,
                SUM(CASE WHEN variant_count = 1 THEN raw_row_count - 1 ELSE 0 END)
                    AS exact_duplicate_extra_row_count,
                MIN(timestamp) FILTER (WHERE clean_key) AS first_event_time,
                MAX(timestamp) FILTER (WHERE clean_key) AS last_event_time
            FROM classified
            GROUP BY ticker, session_date
        )
        SELECT
            ticker AS research_asset_id,
            strftime(session_date, '%Y-%m') AS partition_month,
            CAST(MIN(session_date) FILTER (
                WHERE observed_regular_minute_count > 0
            ) AS VARCHAR) AS first_session_date,
            CAST(MAX(session_date) FILTER (
                WHERE observed_regular_minute_count > 0
            ) AS VARCHAR) AS last_session_date,
            COUNT(*) FILTER (
                WHERE observed_regular_minute_count > 0
            ) AS observed_session_count,
            COUNT(*) FILTER (
                WHERE observed_regular_minute_count = expected_regular_minutes
            ) AS complete_session_count,
            SUM(observed_regular_minute_count) AS observed_regular_minute_count,
            SUM(conflicting_key_count) AS conflicting_key_count,
            SUM(invalid_key_count) AS invalid_key_count,
            SUM(exact_duplicate_extra_row_count) AS exact_duplicate_extra_row_count,
            LIST(CAST(session_date AS VARCHAR) ORDER BY session_date) FILTER (
                WHERE observed_regular_minute_count > 0
            ) AS observed_session_dates,
            LIST(CAST(session_date AS VARCHAR) ORDER BY session_date) FILTER (
                WHERE observed_regular_minute_count = expected_regular_minutes
            ) AS complete_session_dates,
            CAST(MIN(first_event_time) AS VARCHAR) AS first_event_time,
            CAST(MAX(last_event_time) AS VARCHAR) AS last_event_time
        FROM session_coverage
        GROUP BY ticker, strftime(session_date, '%Y-%m')
        ORDER BY research_asset_id, partition_month
    """.strip()

    return USRegimeCorpusInventoryPlan(
        manifest_id=manifest.manifest_id,
        data_version=manifest.data_version,
        calendar_id=calendar.calendar_id,
        assets=normalized_assets,
        partition_months=partition_months,
        selected_size_bytes=manifest.total_size_bytes,
        sql=sql,
        output_columns=output_columns,
    )


@dataclass(frozen=True, slots=True)
class USRegimeMonthCoverage:
    asset: str
    month: str
    expected_session_count: int
    observed_session_count: int
    complete_session_count: int
    expected_regular_minute_count: int
    observed_regular_minute_count: int
    missing_session_count: int
    conflicting_key_count: int
    invalid_key_count: int
    exact_duplicate_extra_row_count: int
    session_membership_sha256: str
    complete_session_membership_sha256: str
    first_session_date: date | None = None
    last_session_date: date | None = None
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None
    schema_version: str = "finagent.us-r2-regime-month-coverage.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _text(self.asset, "asset"))
        month = _text(self.month, "month")
        if len(month) != 7 or month[4] != "-":
            raise ValueError("month must be YYYY-MM")
        object.__setattr__(self, "month", month)
        counts = (
            self.expected_session_count,
            self.observed_session_count,
            self.complete_session_count,
            self.expected_regular_minute_count,
            self.observed_regular_minute_count,
            self.missing_session_count,
            self.conflicting_key_count,
            self.invalid_key_count,
            self.exact_duplicate_extra_row_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("US-R2 month coverage counts must be >= 0")
        if self.observed_session_count > self.expected_session_count:
            raise ValueError("observed sessions cannot exceed admitted calendar sessions")
        if self.complete_session_count > self.observed_session_count:
            raise ValueError("complete sessions cannot exceed observed sessions")
        if self.missing_session_count != self.expected_session_count - self.observed_session_count:
            raise ValueError("missing_session_count must equal expected minus observed sessions")
        for field_name in ("session_membership_sha256", "complete_session_membership_sha256"):
            digest = str(getattr(self, field_name)).strip().lower()
            if len(digest) != 64 or any(item not in "0123456789abcdef" for item in digest):
                raise ValueError(f"{field_name} must be a SHA-256 hex digest")
            object.__setattr__(self, field_name, digest)

    @property
    def regular_minute_coverage_ratio(self) -> float | None:
        if self.expected_regular_minute_count == 0:
            return None
        return self.observed_regular_minute_count / self.expected_regular_minute_count

    @property
    def complete_session_ratio(self) -> float | None:
        if self.expected_session_count == 0:
            return None
        return self.complete_session_count / self.expected_session_count

    @property
    def coverage_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-r2-month-coverage",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "asset": self.asset,
            "month": self.month,
            "expected_session_count": self.expected_session_count,
            "observed_session_count": self.observed_session_count,
            "complete_session_count": self.complete_session_count,
            "expected_regular_minute_count": self.expected_regular_minute_count,
            "observed_regular_minute_count": self.observed_regular_minute_count,
            "missing_session_count": self.missing_session_count,
            "regular_minute_coverage_ratio": self.regular_minute_coverage_ratio,
            "complete_session_ratio": self.complete_session_ratio,
            "conflicting_key_count": self.conflicting_key_count,
            "invalid_key_count": self.invalid_key_count,
            "exact_duplicate_extra_row_count": self.exact_duplicate_extra_row_count,
            "session_membership_sha256": self.session_membership_sha256,
            "complete_session_membership_sha256": self.complete_session_membership_sha256,
            "first_session_date": self.first_session_date.isoformat() if self.first_session_date else None,
            "last_session_date": self.last_session_date.isoformat() if self.last_session_date else None,
            "first_event_time": self.first_event_time.isoformat() if self.first_event_time else None,
            "last_event_time": self.last_event_time.isoformat() if self.last_event_time else None,
        }
        if include_id:
            payload["coverage_id"] = self.coverage_id
        return payload


@dataclass(frozen=True, slots=True)
class USRegimeAssetCoverage:
    asset: str
    first_observed_session: date | None
    last_observed_session: date | None
    observed_month_count: int
    active_span_expected_session_count: int
    active_span_observed_session_count: int
    active_span_complete_session_count: int
    active_span_expected_regular_minute_count: int
    active_span_observed_regular_minute_count: int
    month_coverage_ids: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-asset-coverage.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _text(self.asset, "asset"))
        if (self.first_observed_session is None) != (self.last_observed_session is None):
            raise ValueError("asset history boundaries must both be present or both be absent")
        if (
            self.first_observed_session is not None
            and self.last_observed_session is not None
            and self.last_observed_session < self.first_observed_session
        ):
            raise ValueError("asset history end cannot precede start")
        counts = (
            self.observed_month_count,
            self.active_span_expected_session_count,
            self.active_span_observed_session_count,
            self.active_span_complete_session_count,
            self.active_span_expected_regular_minute_count,
            self.active_span_observed_regular_minute_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("US-R2 asset coverage counts must be >= 0")
        if self.active_span_observed_session_count > self.active_span_expected_session_count:
            raise ValueError("asset observed sessions cannot exceed active-span calendar sessions")
        if self.active_span_complete_session_count > self.active_span_observed_session_count:
            raise ValueError("asset complete sessions cannot exceed observed sessions")
        if len(self.month_coverage_ids) != len(set(self.month_coverage_ids)):
            raise ValueError("asset month coverage IDs must be unique")

    @property
    def active_span_missing_session_count(self) -> int:
        return self.active_span_expected_session_count - self.active_span_observed_session_count

    @property
    def active_span_regular_minute_coverage_ratio(self) -> float | None:
        if self.active_span_expected_regular_minute_count == 0:
            return None
        return (
            self.active_span_observed_regular_minute_count
            / self.active_span_expected_regular_minute_count
        )

    @property
    def coverage_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-r2-asset-coverage",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "asset": self.asset,
            "first_observed_session": (
                self.first_observed_session.isoformat() if self.first_observed_session else None
            ),
            "last_observed_session": (
                self.last_observed_session.isoformat() if self.last_observed_session else None
            ),
            "observed_month_count": self.observed_month_count,
            "active_span_expected_session_count": self.active_span_expected_session_count,
            "active_span_observed_session_count": self.active_span_observed_session_count,
            "active_span_complete_session_count": self.active_span_complete_session_count,
            "active_span_missing_session_count": self.active_span_missing_session_count,
            "active_span_expected_regular_minute_count": (
                self.active_span_expected_regular_minute_count
            ),
            "active_span_observed_regular_minute_count": (
                self.active_span_observed_regular_minute_count
            ),
            "active_span_regular_minute_coverage_ratio": (
                self.active_span_regular_minute_coverage_ratio
            ),
            "month_coverage_ids": list(self.month_coverage_ids),
            "history_boundary_semantics": (
                "first_last_observed_regular_session_not_listing_or_delisting_authority"
            ),
        }
        if include_id:
            payload["coverage_id"] = self.coverage_id
        return payload


@dataclass(frozen=True, slots=True)
class USRegimeYearBreadth:
    year: int
    expected_session_count: int
    observed_asset_count_histogram: tuple[int, ...]
    complete_asset_count_histogram: tuple[int, ...]
    minimum_observed_asset_count: int
    median_observed_asset_count: float
    maximum_observed_asset_count: int
    minimum_complete_asset_count: int
    median_complete_asset_count: float
    maximum_complete_asset_count: int
    schema_version: str = "finagent.us-r2-regime-year-breadth.v1"

    def __post_init__(self) -> None:
        if self.year < 1900 or self.expected_session_count < 0:
            raise ValueError("invalid US-R2 year breadth identity/count")
        if not self.observed_asset_count_histogram or not self.complete_asset_count_histogram:
            raise ValueError("year breadth histograms cannot be empty")
        if len(self.observed_asset_count_histogram) != len(self.complete_asset_count_histogram):
            raise ValueError("observed/complete breadth histograms must have the same bins")
        if sum(self.observed_asset_count_histogram) != self.expected_session_count:
            raise ValueError("observed breadth histogram must cover every expected session")
        if sum(self.complete_asset_count_histogram) != self.expected_session_count:
            raise ValueError("complete breadth histogram must cover every expected session")

    @property
    def full_universe_observed_session_count(self) -> int:
        return self.observed_asset_count_histogram[-1]

    @property
    def full_universe_complete_session_count(self) -> int:
        return self.complete_asset_count_histogram[-1]

    @property
    def breadth_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-year-breadth")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "year": self.year,
            "expected_session_count": self.expected_session_count,
            "observed_asset_count_histogram": list(self.observed_asset_count_histogram),
            "complete_asset_count_histogram": list(self.complete_asset_count_histogram),
            "minimum_observed_asset_count": self.minimum_observed_asset_count,
            "median_observed_asset_count": self.median_observed_asset_count,
            "maximum_observed_asset_count": self.maximum_observed_asset_count,
            "minimum_complete_asset_count": self.minimum_complete_asset_count,
            "median_complete_asset_count": self.median_complete_asset_count,
            "maximum_complete_asset_count": self.maximum_complete_asset_count,
            "full_universe_observed_session_count": self.full_universe_observed_session_count,
            "full_universe_complete_session_count": self.full_universe_complete_session_count,
        }
        if include_id:
            payload["breadth_id"] = self.breadth_id
        return payload


@dataclass(frozen=True, slots=True)
class USRegimeResearchCorpus:
    plan: USRegimeCorpusInventoryPlan
    source_id: str
    source_revision: str
    cleaning_identity: str
    engineering_universe_id: str
    candidate_denominator_id: str
    month_coverages: tuple[USRegimeMonthCoverage, ...]
    asset_coverages: tuple[USRegimeAssetCoverage, ...]
    year_breadth: tuple[USRegimeYearBreadth, ...]
    common_all_asset_start: date | None
    common_all_asset_end: date | None
    common_all_asset_session_count: int
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-research-corpus.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_revision",
            "cleaning_identity",
            "engineering_universe_id",
            "candidate_denominator_id",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if (self.common_all_asset_start is None) != (self.common_all_asset_end is None):
            raise ValueError("common all-asset window boundaries must both exist or both be absent")
        if (
            self.common_all_asset_start is not None
            and self.common_all_asset_end is not None
            and self.common_all_asset_end < self.common_all_asset_start
        ):
            raise ValueError("common all-asset window end cannot precede start")
        if self.common_all_asset_session_count < 0:
            raise ValueError("common_all_asset_session_count must be >= 0")
        if tuple(item.asset for item in self.asset_coverages) != tuple(sorted(self.plan.assets)):
            raise ValueError("asset coverages must match the complete inventory-plan assets")
        if len(self.month_coverages) != len(self.plan.assets) * len(self.plan.partition_months):
            raise ValueError("month coverage matrix must retain every asset x partition cell")

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def corpus_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-r2-regime-corpus",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "plan": self.plan.to_dict(),
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "cleaning_identity": self.cleaning_identity,
            "engineering_universe_id": self.engineering_universe_id,
            "candidate_denominator_id": self.candidate_denominator_id,
            "candidate_performance_read": False,
            "performance_filter_applied": False,
            "point_in_time_security_master_available": False,
            "survivorship_safe_market_claim": False,
            "month_coverage_count": len(self.month_coverages),
            "month_coverages": [item.to_dict() for item in self.month_coverages],
            "asset_coverages": [item.to_dict() for item in self.asset_coverages],
            "year_breadth": [item.to_dict() for item in self.year_breadth],
            "common_all_asset_start": (
                self.common_all_asset_start.isoformat() if self.common_all_asset_start else None
            ),
            "common_all_asset_end": (
                self.common_all_asset_end.isoformat() if self.common_all_asset_end else None
            ),
            "common_all_asset_session_count": self.common_all_asset_session_count,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "research_scope": "multi_regime_engineering_evidence_inventory_only",
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
        }
        if include_id:
            payload["corpus_id"] = self.corpus_id
        return payload


def _calendar_sessions_by_month(
    calendar: TradingCalendarEvidence,
    months: frozenset[str],
) -> dict[str, tuple[TradingSession, ...]]:
    grouped: dict[str, list[TradingSession]] = defaultdict(list)
    for session in calendar.sessions:
        month = session.session_date.strftime("%Y-%m")
        if month in months:
            grouped[month].append(session)
    return {month: tuple(values) for month, values in grouped.items()}


def _row_mapping(rows: Sequence[Mapping[str, object]]) -> dict[tuple[str, str], Mapping[str, object]]:
    result: dict[tuple[str, str], Mapping[str, object]] = {}
    for row in rows:
        key = (
            _text(row.get("research_asset_id"), "research_asset_id"),
            _text(row.get("partition_month"), "partition_month"),
        )
        if key in result:
            raise ValueError(f"duplicate US-R2 aggregate row for {key}")
        result[key] = row
    return result


def execute_us_r2_corpus_inventory(
    plan: USRegimeCorpusInventoryPlan,
    manifest: MinuteStoreManifest,
    calendar: TradingCalendarEvidence,
    *,
    engineering_universe_id: str,
    candidate_denominator_id: str,
    policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
) -> USRegimeResearchCorpus:
    if plan.manifest_id != manifest.manifest_id or plan.data_version != manifest.data_version:
        raise ValueError("US-R2 inventory plan does not bind the supplied minute-store manifest")
    if plan.calendar_id != calendar.calendar_id:
        raise ValueError("US-R2 inventory plan does not bind the supplied trading calendar")
    if plan.partition_months != tuple(item.month for item in manifest.partitions):
        raise ValueError("US-R2 inventory plan partition identity mismatch")

    maximum_rows = len(plan.assets) * len(plan.partition_months) + 1_000
    if maximum_rows > 100_000:
        raise ValueError("US-R2 aggregate preview exceeds the bounded Python fetch limit")
    raw_rows = fetch_plan_rows(
        plan,
        limit=max(1, maximum_rows),
        policy=policy,
        temp_directory=temp_directory,
    )
    row_by_key = _row_mapping(raw_rows)

    months = frozenset(plan.partition_months)
    sessions_by_month = _calendar_sessions_by_month(calendar, months)
    observed_dates_by_asset: dict[str, set[date]] = {asset: set() for asset in plan.assets}
    complete_dates_by_asset: dict[str, set[date]] = {asset: set() for asset in plan.assets}
    blockers: list[str] = []
    month_coverages: list[USRegimeMonthCoverage] = []

    for asset in plan.assets:
        for month in plan.partition_months:
            expected_sessions = sessions_by_month.get(month, ())
            expected_dates = tuple(item.session_date for item in expected_sessions)
            expected_date_set = frozenset(expected_dates)
            expected_minutes = sum(item.regular_minutes for item in expected_sessions)
            row = row_by_key.get((asset, month))
            if row is None:
                observed_dates: tuple[date, ...] = ()
                complete_dates: tuple[date, ...] = ()
                observed_minutes = 0
                conflicting_keys = 0
                invalid_keys = 0
                exact_duplicate_extra_rows = 0
                first_session = None
                last_session = None
                first_event = None
                last_event = None
            else:
                observed_dates = tuple(
                    date.fromisoformat(item)
                    for item in _string_sequence(
                        row.get("observed_session_dates"),
                        "observed_session_dates",
                    )
                )
                complete_dates = tuple(
                    date.fromisoformat(item)
                    for item in _string_sequence(
                        row.get("complete_session_dates"),
                        "complete_session_dates",
                    )
                )
                if not set(observed_dates).issubset(expected_date_set):
                    raise ValueError("US-R2 SQL emitted a session outside the admitted calendar")
                if not set(complete_dates).issubset(set(observed_dates)):
                    raise ValueError("complete sessions must be a subset of observed sessions")
                if _integer(row.get("observed_session_count"), "observed_session_count") != len(
                    observed_dates
                ):
                    raise ValueError("US-R2 observed-session aggregate/list mismatch")
                if _integer(row.get("complete_session_count"), "complete_session_count") != len(
                    complete_dates
                ):
                    raise ValueError("US-R2 complete-session aggregate/list mismatch")
                observed_minutes = _integer(
                    row.get("observed_regular_minute_count"),
                    "observed_regular_minute_count",
                )
                conflicting_keys = _integer(row.get("conflicting_key_count"), "conflicting_key_count")
                invalid_keys = _integer(row.get("invalid_key_count"), "invalid_key_count")
                exact_duplicate_extra_rows = _integer(
                    row.get("exact_duplicate_extra_row_count"),
                    "exact_duplicate_extra_row_count",
                )
                first_session = _optional_date(row.get("first_session_date"), "first_session_date")
                last_session = _optional_date(row.get("last_session_date"), "last_session_date")
                first_event = _optional_datetime(row.get("first_event_time"), "first_event_time")
                last_event = _optional_datetime(row.get("last_event_time"), "last_event_time")

            if observed_minutes > expected_minutes:
                blockers.append(f"regular_minute_density_above_calendar_expectation:{asset}:{month}")
            observed_dates_by_asset[asset].update(observed_dates)
            complete_dates_by_asset[asset].update(complete_dates)
            month_coverages.append(
                USRegimeMonthCoverage(
                    asset=asset,
                    month=month,
                    expected_session_count=len(expected_sessions),
                    observed_session_count=len(observed_dates),
                    complete_session_count=len(complete_dates),
                    expected_regular_minute_count=expected_minutes,
                    observed_regular_minute_count=observed_minutes,
                    missing_session_count=len(expected_sessions) - len(observed_dates),
                    conflicting_key_count=conflicting_keys,
                    invalid_key_count=invalid_keys,
                    exact_duplicate_extra_row_count=exact_duplicate_extra_rows,
                    session_membership_sha256=_membership_sha256(observed_dates),
                    complete_session_membership_sha256=_membership_sha256(complete_dates),
                    first_session_date=first_session,
                    last_session_date=last_session,
                    first_event_time=first_event,
                    last_event_time=last_event,
                )
            )

    expected_sessions = tuple(
        session
        for session in calendar.sessions
        if session.session_date.strftime("%Y-%m") in months
    )
    coverage_by_asset_month: dict[str, list[USRegimeMonthCoverage]] = defaultdict(list)
    for coverage in month_coverages:
        coverage_by_asset_month[coverage.asset].append(coverage)

    asset_coverages: list[USRegimeAssetCoverage] = []
    for asset in plan.assets:
        observed_dates = observed_dates_by_asset[asset]
        complete_dates = complete_dates_by_asset[asset]
        month_rows = tuple(sorted(coverage_by_asset_month[asset], key=lambda item: item.month))
        if not observed_dates:
            blockers.append(f"asset_without_regular_session_history:{asset}")
            first_observed = None
            last_observed = None
            active_expected: tuple[TradingSession, ...] = ()
        else:
            first_observed = min(observed_dates)
            last_observed = max(observed_dates)
            active_expected = tuple(
                session
                for session in expected_sessions
                if first_observed <= session.session_date <= last_observed
            )
        active_expected_minutes = sum(item.regular_minutes for item in active_expected)
        observed_minutes = sum(item.observed_regular_minute_count for item in month_rows)
        asset_coverages.append(
            USRegimeAssetCoverage(
                asset=asset,
                first_observed_session=first_observed,
                last_observed_session=last_observed,
                observed_month_count=sum(item.observed_session_count > 0 for item in month_rows),
                active_span_expected_session_count=len(active_expected),
                active_span_observed_session_count=len(observed_dates),
                active_span_complete_session_count=len(complete_dates),
                active_span_expected_regular_minute_count=active_expected_minutes,
                active_span_observed_regular_minute_count=observed_minutes,
                month_coverage_ids=tuple(item.coverage_id for item in month_rows),
            )
        )

    non_empty_asset_coverages = [
        item for item in asset_coverages if item.first_observed_session is not None
    ]
    if len(non_empty_asset_coverages) == len(plan.assets):
        common_start = max(
            item.first_observed_session
            for item in non_empty_asset_coverages
            if item.first_observed_session is not None
        )
        common_end = min(
            item.last_observed_session
            for item in non_empty_asset_coverages
            if item.last_observed_session is not None
        )
        if common_end < common_start:
            common_start = None
            common_end = None
            common_session_count = 0
        else:
            common_session_count = sum(
                common_start <= item.session_date <= common_end for item in expected_sessions
            )
    else:
        common_start = None
        common_end = None
        common_session_count = 0

    sessions_by_year: dict[int, list[TradingSession]] = defaultdict(list)
    for session in expected_sessions:
        sessions_by_year[session.session_date.year].append(session)
    year_breadth: list[USRegimeYearBreadth] = []
    universe_size = len(plan.assets)
    for year in sorted(sessions_by_year):
        year_sessions = sessions_by_year[year]
        observed_counts = [
            sum(session.session_date in observed_dates_by_asset[asset] for asset in plan.assets)
            for session in year_sessions
        ]
        complete_counts = [
            sum(session.session_date in complete_dates_by_asset[asset] for asset in plan.assets)
            for session in year_sessions
        ]
        observed_histogram = [0] * (universe_size + 1)
        complete_histogram = [0] * (universe_size + 1)
        for value in observed_counts:
            observed_histogram[value] += 1
        for value in complete_counts:
            complete_histogram[value] += 1
        year_breadth.append(
            USRegimeYearBreadth(
                year=year,
                expected_session_count=len(year_sessions),
                observed_asset_count_histogram=tuple(observed_histogram),
                complete_asset_count_histogram=tuple(complete_histogram),
                minimum_observed_asset_count=min(observed_counts),
                median_observed_asset_count=float(median(observed_counts)),
                maximum_observed_asset_count=max(observed_counts),
                minimum_complete_asset_count=min(complete_counts),
                median_complete_asset_count=float(median(complete_counts)),
                maximum_complete_asset_count=max(complete_counts),
            )
        )

    limitations = (
        "universe:engineering_integration_only_not_pit_research_universe",
        "universe:current_symbol_fixed_universe_is_survivorship_conditioned",
        "identity:no_point_in_time_security_master",
        "history:first_last_observed_session_not_listing_or_delisting_authority",
        "research:no_candidate_performance_read_or_filter",
        "authority:inventory_does_not_establish_robust_alpha_or_execution_readiness",
    )
    return USRegimeResearchCorpus(
        plan=plan,
        source_id=manifest.source_id,
        source_revision=manifest.source_revision,
        cleaning_identity=manifest.cleaning_identity,
        engineering_universe_id=engineering_universe_id,
        candidate_denominator_id=candidate_denominator_id,
        month_coverages=tuple(sorted(month_coverages, key=lambda item: (item.asset, item.month))),
        asset_coverages=tuple(sorted(asset_coverages, key=lambda item: item.asset)),
        year_breadth=tuple(year_breadth),
        common_all_asset_start=common_start,
        common_all_asset_end=common_end,
        common_all_asset_session_count=common_session_count,
        blockers=tuple(dict.fromkeys(blockers)),
        limitations=limitations,
    )
