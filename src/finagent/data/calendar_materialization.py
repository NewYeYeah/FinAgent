from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any

from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession

RECOMMENDED_EXCHANGE_CALENDARS_VERSION = "4.13.2"


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _as_date(value: object, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    date_method = getattr(value, "date", None)
    if callable(date_method):
        rendered = date_method()
        if isinstance(rendered, date):
            return rendered
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be date-like") from exc


def _as_aware_datetime(value: object, field: str) -> datetime:
    candidate = value
    to_pydatetime = getattr(candidate, "to_pydatetime", None)
    if callable(to_pydatetime):
        candidate = to_pydatetime()
    if not isinstance(candidate, datetime):
        try:
            candidate = datetime.fromisoformat(str(candidate))
        except ValueError as exc:
            raise ValueError(f"{field} must be datetime-like") from exc
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return candidate


@dataclass(frozen=True, slots=True)
class ExchangeCalendarMaterializationSpec:
    market_id: str = "XNYS"
    timezone: str = "America/New_York"
    requested_start: date = date(1992, 1, 1)
    requested_end: date = date(2026, 3, 31)
    package_name: str = "exchange_calendars"
    expected_package_version: str = RECOMMENDED_EXCHANGE_CALENDARS_VERSION
    regular_session_minutes: int = 390
    schema_version: str = "finagent.exchange-calendar-materialization-spec.v1"

    def __post_init__(self) -> None:
        if not self.market_id.strip():
            raise ValueError("market_id must be non-empty")
        if not self.timezone.strip():
            raise ValueError("timezone must be non-empty")
        if self.requested_end <= self.requested_start:
            raise ValueError("requested_end must be later than requested_start")
        if not self.package_name.strip():
            raise ValueError("package_name must be non-empty")
        if not self.expected_package_version.strip():
            raise ValueError("expected_package_version must be non-empty")
        if self.regular_session_minutes <= 0:
            raise ValueError("regular_session_minutes must be positive")

    @property
    def spec_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "market_id": self.market_id,
            "timezone": self.timezone,
            "requested_start": self.requested_start.isoformat(),
            "requested_end": self.requested_end.isoformat(),
            "package_name": self.package_name,
            "expected_package_version": self.expected_package_version,
            "regular_session_minutes": self.regular_session_minutes,
        }
        return _canonical_hash(payload, prefix="calendar-materialization-spec")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "market_id": self.market_id,
            "timezone": self.timezone,
            "requested_start": self.requested_start.isoformat(),
            "requested_end": self.requested_end.isoformat(),
            "package_name": self.package_name,
            "expected_package_version": self.expected_package_version,
            "regular_session_minutes": self.regular_session_minutes,
        }


@dataclass(frozen=True, slots=True)
class CalendarAnchorCheck:
    check_id: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class TradingCalendarMaterializationReport:
    spec: ExchangeCalendarMaterializationSpec
    evidence: TradingCalendarEvidence
    observed_package_version: str
    anchor_checks: tuple[CalendarAnchorCheck, ...]
    materialized_at: datetime
    schema_version: str = "finagent.trading-calendar-materialization-report.v1"

    def __post_init__(self) -> None:
        if self.materialized_at.tzinfo is None or self.materialized_at.utcoffset() is None:
            raise ValueError("materialized_at must be timezone-aware")
        if self.observed_package_version != self.spec.expected_package_version:
            raise ValueError("observed calendar package version does not match materialization spec")

    @property
    def coverage_boundary_passed(self) -> bool:
        grace = timedelta(days=7)
        return (
            self.spec.requested_start
            <= self.evidence.coverage_start
            <= self.spec.requested_start + grace
            and self.spec.requested_end - grace
            <= self.evidence.coverage_end
            <= self.spec.requested_end
        )

    @property
    def passed(self) -> bool:
        return self.coverage_boundary_passed and all(item.passed for item in self.anchor_checks)

    @property
    def report_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "spec_id": self.spec.spec_id,
            "calendar_id": self.evidence.calendar_id,
            "observed_package_version": self.observed_package_version,
            "anchor_checks": [item.to_dict() for item in self.anchor_checks],
            "coverage_boundary_passed": self.coverage_boundary_passed,
        }
        return _canonical_hash(payload, prefix="calendar-materialization")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "passed": self.passed,
            "coverage_boundary_passed": self.coverage_boundary_passed,
            "spec": self.spec.to_dict(),
            "observed_package_version": self.observed_package_version,
            "anchor_checks": [item.to_dict() for item in self.anchor_checks],
            "evidence": self.evidence.to_dict(),
            "materialized_at": self.materialized_at.astimezone(UTC).isoformat(),
        }

    def write_json(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return output


def materialize_calendar_evidence_from_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    market_id: str,
    timezone: str,
    source: str,
    source_revision: str,
    regular_session_minutes: int = 390,
) -> TradingCalendarEvidence:
    sessions: list[TradingSession] = []
    for row in rows:
        session_date = _as_date(row["session_date"], "session_date")
        open_at = _as_aware_datetime(row["open"], "open")
        close_at = _as_aware_datetime(row["close"], "close")
        regular_minutes = int((close_at - open_at).total_seconds() // 60)
        sessions.append(
            TradingSession(
                session_date=session_date,
                open_at=open_at,
                close_at=close_at,
                is_half_day=regular_minutes < regular_session_minutes,
            )
        )
    return TradingCalendarEvidence(
        market_id=market_id,
        timezone=timezone,
        source=source,
        source_revision=source_revision,
        sessions=tuple(sessions),
        regular_session_minutes=regular_session_minutes,
    )


def validate_xnys_research_anchors(
    evidence: TradingCalendarEvidence,
) -> tuple[CalendarAnchorCheck, ...]:
    """Validate a few high-information NYSE anchors inside the admitted data range.

    The dataset ends at 2026-03-31, so holiday/half-day anchors deliberately use
    2025 dates while DST anchors exercise March 2026.
    """

    def session_clock(
        session_date: date,
        expected_open: datetime,
        expected_close: datetime,
        check_id: str,
    ) -> CalendarAnchorCheck:
        session = evidence.session(session_date)
        passed = (
            session is not None
            and session.open_at.astimezone(UTC) == expected_open
            and session.close_at.astimezone(UTC) == expected_close
        )
        detail = (
            f"{session_date.isoformat()} expected "
            f"{expected_open.isoformat()}..{expected_close.isoformat()}"
        )
        return CalendarAnchorCheck(check_id, passed, detail)

    independence_day_2025 = CalendarAnchorCheck(
        "xnys-independence-day-2025",
        evidence.covers(date(2025, 7, 4)) and not evidence.is_session(date(2025, 7, 4)),
        "2025-07-04 must be absent as the NYSE Independence Day closure",
    )
    thanksgiving_half_day_2025 = session_clock(
        date(2025, 11, 28),
        datetime(2025, 11, 28, 14, 30, tzinfo=UTC),
        datetime(2025, 11, 28, 18, 0, tzinfo=UTC),
        "xnys-thanksgiving-half-day-2025",
    )
    half_day = evidence.session(date(2025, 11, 28))
    half_day_flag = CalendarAnchorCheck(
        "xnys-thanksgiving-half-day-flag-2025",
        half_day is not None and half_day.is_half_day,
        "2025-11-28 must be classified as a 210-minute half-day session",
    )
    dst_before = session_clock(
        date(2026, 3, 6),
        datetime(2026, 3, 6, 14, 30, tzinfo=UTC),
        datetime(2026, 3, 6, 21, 0, tzinfo=UTC),
        "xnys-dst-before-2026",
    )
    dst_after = session_clock(
        date(2026, 3, 9),
        datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
        datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
        "xnys-dst-after-2026",
    )
    return (
        independence_day_2025,
        thanksgiving_half_day_2025,
        half_day_flag,
        dst_before,
        dst_after,
    )


def materialize_xnys_exchange_calendars(
    spec: ExchangeCalendarMaterializationSpec,
    *,
    materialized_at: datetime | None = None,
) -> TradingCalendarMaterializationReport:
    try:
        package = importlib.import_module(spec.package_name)
    except ImportError as exc:
        raise RuntimeError(
            "XNYS materialization requires the optional exchange_calendars package in the "
            "active Conda environment; install the exact version declared by the spec"
        ) from exc

    observed_version = metadata.version(spec.package_name)
    if observed_version != spec.expected_package_version:
        raise RuntimeError(
            f"calendar package version mismatch: observed {observed_version}, "
            f"expected {spec.expected_package_version}"
        )

    get_calendar: Any = package.get_calendar
    calendar: Any = get_calendar(
        spec.market_id,
        start=spec.requested_start.isoformat(),
        end=spec.requested_end.isoformat(),
        side="left",
    )
    rows: list[dict[str, object]] = []
    for session_label, raw_row in calendar.schedule.iterrows():
        rows.append(
            {
                "session_date": session_label,
                "open": raw_row["open"],
                "close": raw_row["close"],
            }
        )

    evidence = materialize_calendar_evidence_from_rows(
        rows,
        market_id=spec.market_id,
        timezone=spec.timezone,
        source=f"{spec.package_name}:{spec.market_id}",
        source_revision=observed_version,
        regular_session_minutes=spec.regular_session_minutes,
    )
    return TradingCalendarMaterializationReport(
        spec=spec,
        evidence=evidence,
        observed_package_version=observed_version,
        anchor_checks=validate_xnys_research_anchors(evidence),
        materialized_at=materialized_at or datetime.now(UTC),
    )
