from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finagent.data.capabilities import AdapterCapabilities
from finagent.data.minute_store import MinuteQueryPlan
from finagent.data.query import MarketDataField, MarketDataQuery, MarketDataView, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

from .sessionize import CalendarSessionizedMinuteStore, SessionizationEvidence

RESAMPLED_MINUTE_ADAPTER_ID = "us-minute-resampled-duckdb-v1"
_SUPPORTED_INTERVALS = frozenset(
    {BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30}
)


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True, slots=True)
class ResamplingSpec:
    calendar_id: str
    target_interval: BarInterval
    bucket_anchor: str = "session_open"
    partial_bar_policy: str = "reject_non_divisible_session"
    missing_minute_policy: str = "preserve_incomplete"
    bar_timestamp: str = "bucket_start"
    availability_clock: str = "bucket_end"
    schema_version: str = "finagent.minute-resampling-spec.v1"

    def __post_init__(self) -> None:
        calendar_id = self.calendar_id.strip()
        if not calendar_id:
            raise ValueError("calendar_id must be non-empty")
        if self.target_interval not in _SUPPORTED_INTERVALS:
            raise ValueError("v1 resampling supports only 5m, 15m and 30m")
        if self.bucket_anchor != "session_open":
            raise ValueError("v1 buckets must be anchored to session_open")
        if self.partial_bar_policy != "reject_non_divisible_session":
            raise ValueError("v1 partial bars must fail closed on non-divisible sessions")
        if self.missing_minute_policy != "preserve_incomplete":
            raise ValueError("v1 missing minutes must remain explicit incomplete coverage")
        if self.bar_timestamp != "bucket_start":
            raise ValueError("v1 resampled event_time must be the bucket start")
        if self.availability_clock != "bucket_end":
            raise ValueError("v1 resampled available_at must be the bucket end")
        object.__setattr__(self, "calendar_id", calendar_id)

    @property
    def interval_minutes(self) -> int:
        minutes = self.target_interval.minutes
        if minutes is None:  # pragma: no cover - guarded by supported interval set
            raise ValueError("target interval must be intraday")
        return minutes

    @property
    def spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="minute-resampling-spec")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "calendar_id": self.calendar_id,
            "target_interval": self.target_interval.value,
            "interval_minutes": self.interval_minutes,
            "bucket_anchor": self.bucket_anchor,
            "partial_bar_policy": self.partial_bar_policy,
            "missing_minute_policy": self.missing_minute_policy,
            "bar_timestamp": self.bar_timestamp,
            "availability_clock": self.availability_clock,
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


@dataclass(frozen=True, slots=True)
class ResamplingEvidence:
    spec_id: str
    calendar_id: str
    sessionization_evidence_id: str
    source_plan_id: str
    resampled_plan_id: str
    source_data_version: str
    resampled_data_version: str
    schema_version: str = "finagent.minute-resampling-evidence.v1"

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="minute-resampling")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "calendar_id": self.calendar_id,
            "sessionization_evidence_id": self.sessionization_evidence_id,
            "source_plan_id": self.source_plan_id,
            "resampled_plan_id": self.resampled_plan_id,
            "source_data_version": self.source_data_version,
            "resampled_data_version": self.resampled_data_version,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def _resampled_data_version(
    *,
    source_data_version: str,
    spec: ResamplingSpec,
) -> str:
    return _canonical_hash(
        {
            "source_data_version": source_data_version,
            "resampling_spec_id": spec.spec_id,
            "calendar_id": spec.calendar_id,
        },
        prefix="resampled-minute-data-version",
    )


def _relevant_session_durations(
    store: CalendarSessionizedMinuteStore,
    query: MarketDataQuery,
) -> tuple[int, ...]:
    calendar = store.calendar
    zone = ZoneInfo(calendar.timezone)
    start_date = query.start.astimezone(zone).date() - timedelta(days=1)
    end_date = query.end.astimezone(zone).date() + timedelta(days=1)
    return tuple(
        session.regular_minutes
        for session in calendar.sessions
        if start_date <= session.session_date <= end_date
    )


def _require_divisible_sessions(
    store: CalendarSessionizedMinuteStore,
    query: MarketDataQuery,
    spec: ResamplingSpec,
) -> None:
    durations = _relevant_session_durations(store, query)
    if not durations:
        raise ValueError("resampling query does not intersect a materialized trading session")
    non_divisible = sorted(
        set(minutes for minutes in durations if minutes % spec.interval_minutes != 0)
    )
    if non_divisible:
        rendered = ",".join(str(value) for value in non_divisible)
        raise ValueError(
            f"session duration(s) {rendered} are not divisible by "
            f"{spec.interval_minutes} minutes"
        )


def _base_event_window(
    query: MarketDataQuery,
    interval_minutes: int,
) -> tuple[datetime, datetime]:
    delta = timedelta(minutes=interval_minutes)
    if query.availability_policy is AvailabilityPolicy.AVAILABLE_AT:
        return query.start - delta, query.end
    return query.start, query.end + delta


def _aggregation_expression(field: MarketDataField) -> str:
    if field is MarketDataField.OPEN:
        return "CAST(arg_min(d.open, d.event_time) AS DOUBLE) AS open"
    if field is MarketDataField.HIGH:
        return "CAST(max(d.high) AS DOUBLE) AS high"
    if field is MarketDataField.LOW:
        return "CAST(min(d.low) AS DOUBLE) AS low"
    if field is MarketDataField.CLOSE:
        return "CAST(arg_max(d.close, d.event_time) AS DOUBLE) AS close"
    if field is MarketDataField.VOLUME:
        return "CAST(sum(d.volume) AS DOUBLE) AS volume"
    raise ValueError(f"unsupported market-data field {field!r}")  # pragma: no cover


def build_resampled_minute_plan(
    source_plan: MinuteQueryPlan,
    sessionization_evidence: SessionizationEvidence,
    query: MarketDataQuery,
    spec: ResamplingSpec,
) -> tuple[MinuteQueryPlan, ResamplingEvidence]:
    interval_minutes = spec.interval_minutes
    data_version = _resampled_data_version(
        source_data_version=source_plan.data_version,
        spec=spec,
    )
    aggregations = ",\n                ".join(
        _aggregation_expression(field) for field in query.fields
    )
    value_columns = tuple(field.value for field in query.fields)
    value_projection = "\n            ".join(f", a.{name} AS {name}" for name in value_columns)
    interval_literal = _sql_string(query.interval.value)
    data_version_literal = _sql_string(data_version)
    clock_column = (
        "available_at"
        if query.availability_policy is AvailabilityPolicy.AVAILABLE_AT
        else "event_time"
    )
    output_columns = (
        "research_asset_id",
        "session_date",
        "event_time",
        "available_at",
        "interval",
        *value_columns,
        "session_type",
        "session_id",
        "session_open",
        "session_close",
        "bar_index",
        "observed_minute_count",
        "expected_minute_count",
        "coverage_ratio",
        "is_complete",
        "is_half_day",
        "source_id",
        "source_revision",
        "data_version",
    )
    sql = f"""
        WITH source_rows AS (
            {source_plan.sql}
        ),
        bucketed AS (
            SELECT
                d.*,
                CAST(floor(d.minute_offset / {interval_minutes}) AS BIGINT) AS bucket_index
            FROM source_rows AS d
            WHERE d.is_regular_session
              AND d.minute_offset IS NOT NULL
        ),
        aggregated AS (
            SELECT
                d.research_asset_id,
                d.session_date,
                d.session_id,
                d.session_open,
                d.session_close,
                d.bucket_index,
                d.session_open
                    + d.bucket_index * INTERVAL '{interval_minutes} minutes' AS event_time,
                {aggregations},
                count(*) AS observed_minute_count,
                {interval_minutes}::BIGINT AS expected_minute_count,
                count(*)::DOUBLE / {interval_minutes}::DOUBLE AS coverage_ratio,
                count(*) = {interval_minutes} AS is_complete,
                bool_or(d.is_half_day) AS is_half_day,
                min(d.source_id) AS source_id,
                min(d.source_revision) AS source_revision
            FROM bucketed AS d
            GROUP BY
                d.research_asset_id,
                d.session_date,
                d.session_id,
                d.session_open,
                d.session_close,
                d.bucket_index
        ),
        projected AS (
            SELECT
                a.research_asset_id,
                a.session_date,
                a.event_time,
                a.event_time + INTERVAL '{interval_minutes} minutes' AS available_at,
                {interval_literal} AS interval
                {value_projection},
                'regular' AS session_type,
                a.session_id,
                a.session_open,
                a.session_close,
                a.bucket_index AS bar_index,
                a.observed_minute_count,
                a.expected_minute_count,
                a.coverage_ratio,
                a.is_complete,
                a.is_half_day,
                a.source_id,
                a.source_revision,
                {data_version_literal} AS data_version
            FROM aggregated AS a
        )
        SELECT {', '.join(output_columns)}
        FROM projected AS p
        WHERE p.{clock_column} >= TIMESTAMPTZ {_sql_string(query.start.isoformat())}
          AND p.{clock_column} < TIMESTAMPTZ {_sql_string(query.end.isoformat())}
        ORDER BY event_time, research_asset_id
    """.strip()

    plan = MinuteQueryPlan(
        query=query,
        manifest_id=source_plan.manifest_id,
        data_version=data_version,
        sql=sql,
        partition_months=source_plan.partition_months,
        selected_size_bytes=source_plan.selected_size_bytes,
        output_columns=output_columns,
    )
    evidence = ResamplingEvidence(
        spec_id=spec.spec_id,
        calendar_id=spec.calendar_id,
        sessionization_evidence_id=sessionization_evidence.evidence_id,
        source_plan_id=source_plan.plan_id,
        resampled_plan_id=plan.plan_id,
        source_data_version=source_plan.data_version,
        resampled_data_version=data_version,
    )
    return plan, evidence


class SessionResampledMinuteStore:
    def __init__(self, sessionized_store: CalendarSessionizedMinuteStore) -> None:
        self.sessionized_store = sessionized_store

    @property
    def capabilities(self) -> AdapterCapabilities:
        raw_store = self.sessionized_store.raw_store
        return AdapterCapabilities(
            adapter_id=RESAMPLED_MINUTE_ADAPTER_ID,
            provider=raw_store.manifest.source_id,
            market_ids=frozenset({self.sessionized_store.calendar.market_id}),
            intervals=_SUPPORTED_INTERVALS,
            fields=frozenset(MarketDataField),
            session_policies=frozenset({SessionPolicy.REGULAR}),
            adjustment_policies=frozenset({ResearchPriceBasis.RAW}),
            availability_policies=frozenset(
                {AvailabilityPolicy.EVENT_TIME, AvailabilityPolicy.AVAILABLE_AT}
            ),
            supports_corporate_actions=False,
            lazy_query=True,
        )

    def plan(self, query: MarketDataQuery) -> tuple[MinuteQueryPlan, ResamplingEvidence]:
        self.capabilities.require(query)
        spec = ResamplingSpec(
            calendar_id=self.sessionized_store.calendar.calendar_id,
            target_interval=query.interval,
        )
        _require_divisible_sessions(self.sessionized_store, query, spec)
        base_start, base_end = _base_event_window(query, spec.interval_minutes)
        base_query = MarketDataQuery(
            market_id=query.market_id,
            assets=query.assets,
            start=base_start,
            end=base_end,
            interval=BarInterval.MINUTE_1,
            fields=query.fields,
            session_policy=SessionPolicy.REGULAR,
            adjustment_policy=query.adjustment_policy,
            availability_policy=AvailabilityPolicy.EVENT_TIME,
        )
        source_plan, sessionization_evidence = self.sessionized_store.plan(base_query)
        return build_resampled_minute_plan(
            source_plan,
            sessionization_evidence,
            query,
            spec,
        )

    def view(self, query: MarketDataQuery) -> MarketDataView:
        plan, _evidence = self.plan(query)
        return MarketDataView(
            query=query,
            adapter_id=RESAMPLED_MINUTE_ADAPTER_ID,
            data_version=plan.data_version,
            lazy=True,
            estimated_rows=None,
        )
