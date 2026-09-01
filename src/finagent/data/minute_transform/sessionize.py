from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from finagent.data.capabilities import AdapterCapabilities
from finagent.data.minute_store import DuckDBParquetMinuteStore, MinuteQueryPlan
from finagent.data.query import MarketDataField, MarketDataQuery, MarketDataView, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession

SESSIONIZED_MINUTE_ADAPTER_ID = "us-minute-sessionized-duckdb-v1"


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


def _sql_timestamp(value: datetime) -> str:
    return f"TIMESTAMPTZ {_sql_string(value.astimezone(UTC).isoformat())}"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _aware_datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _optional_aware_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _aware_datetime(value, field_name)


@dataclass(frozen=True, slots=True)
class SessionizationSpec:
    calendar_id: str
    market_id: str = "XNYS"
    classify_clock: str = "event_time"
    regular_boundary: str = "open_inclusive_close_exclusive"
    unmatched_session_action: str = "preserve_outside_calendar"
    schema_version: str = "finagent.minute-sessionization-spec.v1"

    def __post_init__(self) -> None:
        calendar_id = self.calendar_id.strip()
        market_id = self.market_id.strip()
        if not calendar_id:
            raise ValueError("calendar_id must be non-empty")
        if not market_id:
            raise ValueError("market_id must be non-empty")
        if self.classify_clock != "event_time":
            raise ValueError("v1 sessionization classifies only by event_time")
        if self.regular_boundary != "open_inclusive_close_exclusive":
            raise ValueError("v1 regular boundary must be open-inclusive / close-exclusive")
        if self.unmatched_session_action != "preserve_outside_calendar":
            raise ValueError("v1 unmatched rows must be preserved as outside_calendar")
        object.__setattr__(self, "calendar_id", calendar_id)
        object.__setattr__(self, "market_id", market_id)

    @property
    def spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="minute-sessionization-spec")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "calendar_id": self.calendar_id,
            "market_id": self.market_id,
            "classify_clock": self.classify_clock,
            "regular_boundary": self.regular_boundary,
            "unmatched_session_action": self.unmatched_session_action,
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


@dataclass(frozen=True, slots=True)
class SessionizationEvidence:
    spec_id: str
    calendar_id: str
    base_plan_id: str
    sessionized_plan_id: str
    source_data_version: str
    sessionized_data_version: str
    schema_version: str = "finagent.minute-sessionization-evidence.v1"

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="minute-sessionization")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "calendar_id": self.calendar_id,
            "base_plan_id": self.base_plan_id,
            "sessionized_plan_id": self.sessionized_plan_id,
            "source_data_version": self.source_data_version,
            "sessionized_data_version": self.sessionized_data_version,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def load_trading_calendar_evidence_json(
    path: str | Path,
    *,
    expected_calendar_id: str | None = None,
) -> TradingCalendarEvidence:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    root = _mapping(raw, "calendar JSON")
    evidence_raw = _mapping(root.get("evidence", root), "evidence")
    sessions: list[TradingSession] = []
    for item in _sequence(evidence_raw.get("sessions"), "evidence.sessions"):
        row = _mapping(item, "evidence.sessions[]")
        sessions.append(
            TradingSession(
                session_date=date.fromisoformat(_text(row.get("session_date"), "session_date")),
                open_at=_aware_datetime(row.get("open_at"), "open_at"),
                close_at=_aware_datetime(row.get("close_at"), "close_at"),
                pre_open_at=_optional_aware_datetime(row.get("pre_open_at"), "pre_open_at"),
                post_close_at=_optional_aware_datetime(row.get("post_close_at"), "post_close_at"),
                is_half_day=bool(row.get("is_half_day", False)),
            )
        )
    evidence = TradingCalendarEvidence(
        market_id=_text(evidence_raw.get("market_id"), "evidence.market_id"),
        timezone=_text(evidence_raw.get("timezone"), "evidence.timezone"),
        source=_text(evidence_raw.get("source"), "evidence.source"),
        source_revision=_text(evidence_raw.get("source_revision"), "evidence.source_revision"),
        sessions=tuple(sessions),
        regular_session_minutes=int(evidence_raw.get("regular_session_minutes", 390)),
        schema_version=_text(
            evidence_raw.get("schema_version", "finagent.trading-calendar-evidence.v1"),
            "evidence.schema_version",
        ),
    )
    stored_id = evidence_raw.get("calendar_id")
    if stored_id is not None and str(stored_id) != evidence.calendar_id:
        raise ValueError("stored calendar_id does not match materialized calendar content")
    if expected_calendar_id is not None and evidence.calendar_id != expected_calendar_id:
        raise ValueError(
            f"calendar identity mismatch: observed {evidence.calendar_id}, "
            f"expected {expected_calendar_id}"
        )
    return evidence


def _relevant_sessions(
    calendar: TradingCalendarEvidence,
    query: MarketDataQuery,
) -> tuple[TradingSession, ...]:
    zone = ZoneInfo(calendar.timezone)
    start_date = query.start.astimezone(zone).date() - timedelta(days=1)
    end_date = query.end.astimezone(zone).date() + timedelta(days=1)
    sessions = tuple(
        item for item in calendar.sessions if start_date <= item.session_date <= end_date
    )
    if not sessions:
        raise ValueError("market-data query does not intersect materialized calendar coverage")
    return sessions


def _calendar_values_sql(sessions: tuple[TradingSession, ...]) -> str:
    values = []
    for session in sessions:
        values.append(
            "("
            f"DATE {_sql_string(session.session_date.isoformat())}, "
            f"{_sql_timestamp(session.open_at)}, "
            f"{_sql_timestamp(session.close_at)}, "
            + ("true" if session.is_half_day else "false")
            + ")"
        )
    return ",\n                ".join(values)


def _sessionized_data_version(
    *,
    source_data_version: str,
    spec: SessionizationSpec,
) -> str:
    return _canonical_hash(
        {
            "source_data_version": source_data_version,
            "sessionization_spec_id": spec.spec_id,
            "calendar_id": spec.calendar_id,
        },
        prefix="sessionized-minute-data-version",
    )


def build_sessionized_minute_plan(
    base_plan: MinuteQueryPlan,
    calendar: TradingCalendarEvidence,
    query: MarketDataQuery,
) -> tuple[MinuteQueryPlan, SessionizationEvidence]:
    if query.market_id != calendar.market_id:
        raise ValueError("query market_id must match calendar market_id")
    if query.session_policy is SessionPolicy.EXTENDED:
        raise ValueError(
            "session_policy:extended is unavailable until explicit pre/post-market "
            "calendar boundaries are materialized"
        )
    if query.session_policy not in {SessionPolicy.REGULAR, SessionPolicy.ALL_OBSERVED}:
        raise ValueError(f"unsupported session policy {query.session_policy.value!r}")

    spec = SessionizationSpec(calendar_id=calendar.calendar_id, market_id=calendar.market_id)
    sessions = _relevant_sessions(calendar, query)
    data_version = _sessionized_data_version(
        source_data_version=base_plan.data_version,
        spec=spec,
    )
    value_columns = tuple(item.value for item in query.fields)
    value_projection = "\n            ".join(f", d.{name} AS {name}" for name in value_columns)
    regular_expression = "d.event_time >= c.open_at AND d.event_time < c.close_at"
    session_filter = (
        f"WHERE {regular_expression}" if query.session_policy is SessionPolicy.REGULAR else ""
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
        "minute_offset",
        "is_regular_session",
        "is_half_day",
        "source_id",
        "source_revision",
        "data_version",
    )
    sql = f"""
        WITH base_data AS (
            {base_plan.sql}
        ),
        calendar_sessions(session_date, open_at, close_at, is_half_day) AS (
            VALUES
                {_calendar_values_sql(sessions)}
        ),
        classified AS (
            SELECT
                d.research_asset_id,
                d.session_date,
                d.event_time,
                d.available_at,
                d.interval
                {value_projection},
                CASE
                    WHEN c.session_date IS NULL THEN 'outside_calendar'
                    WHEN {regular_expression} THEN 'regular'
                    ELSE 'outside_regular'
                END AS session_type,
                CASE
                    WHEN c.session_date IS NULL THEN NULL
                    ELSE {_sql_string(calendar.market_id + ':')} || CAST(c.session_date AS VARCHAR)
                END AS session_id,
                c.open_at AS session_open,
                c.close_at AS session_close,
                CASE
                    WHEN {regular_expression}
                    THEN date_diff('minute', c.open_at, d.event_time)
                    ELSE NULL
                END AS minute_offset,
                COALESCE({regular_expression}, false) AS is_regular_session,
                COALESCE(c.is_half_day, false) AS is_half_day,
                d.source_id,
                d.source_revision,
                {_sql_string(data_version)} AS data_version
            FROM base_data AS d
            LEFT JOIN calendar_sessions AS c
              ON d.session_date = c.session_date
        )
        SELECT {', '.join(output_columns)}
        FROM classified AS d
        {session_filter.replace('c.', 'd.').replace('d.event_time >= d.open_at', 'd.event_time >= d.session_open').replace('d.event_time < d.close_at', 'd.event_time < d.session_close')}
        ORDER BY event_time, research_asset_id
    """.strip()

    plan = MinuteQueryPlan(
        query=query,
        manifest_id=base_plan.manifest_id,
        data_version=data_version,
        sql=sql,
        partition_months=base_plan.partition_months,
        selected_size_bytes=base_plan.selected_size_bytes,
        output_columns=output_columns,
    )
    evidence = SessionizationEvidence(
        spec_id=spec.spec_id,
        calendar_id=calendar.calendar_id,
        base_plan_id=base_plan.plan_id,
        sessionized_plan_id=plan.plan_id,
        source_data_version=base_plan.data_version,
        sessionized_data_version=data_version,
    )
    return plan, evidence


class CalendarSessionizedMinuteStore:
    def __init__(
        self,
        raw_store: DuckDBParquetMinuteStore,
        calendar: TradingCalendarEvidence,
    ) -> None:
        if raw_store.manifest.market_id != calendar.market_id:
            raise ValueError("minute-store market_id must match calendar market_id")
        self.raw_store = raw_store
        self.calendar = calendar

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=SESSIONIZED_MINUTE_ADAPTER_ID,
            provider=self.raw_store.manifest.source_id,
            market_ids=frozenset({self.calendar.market_id}),
            intervals=frozenset({BarInterval.MINUTE_1}),
            fields=frozenset(MarketDataField),
            session_policies=frozenset({SessionPolicy.REGULAR, SessionPolicy.ALL_OBSERVED}),
            adjustment_policies=frozenset({ResearchPriceBasis.RAW}),
            availability_policies=frozenset(
                {AvailabilityPolicy.EVENT_TIME, AvailabilityPolicy.AVAILABLE_AT}
            ),
            supports_corporate_actions=False,
            lazy_query=True,
        )

    def plan(self, query: MarketDataQuery) -> tuple[MinuteQueryPlan, SessionizationEvidence]:
        self.capabilities.require(query)
        base_query = MarketDataQuery(
            market_id=query.market_id,
            assets=query.assets,
            start=query.start,
            end=query.end,
            interval=query.interval,
            fields=query.fields,
            session_policy=SessionPolicy.ALL_OBSERVED,
            adjustment_policy=query.adjustment_policy,
            availability_policy=query.availability_policy,
        )
        base_plan = self.raw_store.plan(base_query)
        return build_sessionized_minute_plan(base_plan, self.calendar, query)

    def view(self, query: MarketDataQuery) -> MarketDataView:
        plan, _evidence = self.plan(query)
        return MarketDataView(
            query=query,
            adapter_id=SESSIONIZED_MINUTE_ADAPTER_ID,
            data_version=plan.data_version,
            lazy=True,
            estimated_rows=None,
        )
