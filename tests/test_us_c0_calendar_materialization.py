from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from finagent.data.calendar_materialization import (
    RECOMMENDED_EXCHANGE_CALENDARS_VERSION,
    CalendarAnchorCheck,
    ExchangeCalendarMaterializationSpec,
    TradingCalendarMaterializationReport,
    materialize_calendar_evidence_from_rows,
    validate_xnys_research_anchors,
)


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _anchor_rows() -> list[dict[str, object]]:
    return [
        {
            "session_date": date(2025, 7, 1),
            "open": _utc(2025, 7, 1, 13, 30),
            "close": _utc(2025, 7, 1, 20, 0),
        },
        {
            "session_date": date(2025, 11, 28),
            "open": _utc(2025, 11, 28, 14, 30),
            "close": _utc(2025, 11, 28, 18, 0),
        },
        {
            "session_date": date(2026, 3, 6),
            "open": _utc(2026, 3, 6, 14, 30),
            "close": _utc(2026, 3, 6, 21, 0),
        },
        {
            "session_date": date(2026, 3, 9),
            "open": _utc(2026, 3, 9, 13, 30),
            "close": _utc(2026, 3, 9, 20, 0),
        },
        {
            "session_date": date(2026, 3, 31),
            "open": _utc(2026, 3, 31, 13, 30),
            "close": _utc(2026, 3, 31, 20, 0),
        },
    ]


def _anchor_evidence():
    return materialize_calendar_evidence_from_rows(
        reversed(_anchor_rows()),
        market_id="XNYS",
        timezone="America/New_York",
        source="fixture:XNYS",
        source_revision=RECOMMENDED_EXCHANGE_CALENDARS_VERSION,
    )


def test_row_materialization_sorts_sessions_and_derives_half_day() -> None:
    evidence = _anchor_evidence()

    assert evidence.coverage_start == date(2025, 7, 1)
    assert evidence.coverage_end == date(2026, 3, 31)
    assert evidence.require_session(date(2025, 11, 28)).regular_minutes == 210
    assert evidence.require_session(date(2025, 11, 28)).is_half_day is True
    assert evidence.require_session(date(2026, 3, 9)).is_half_day is False


def test_research_anchor_checks_pass_inside_admitted_data_interval() -> None:
    checks = validate_xnys_research_anchors(_anchor_evidence())

    assert {item.check_id for item in checks} == {
        "xnys-independence-day-2025",
        "xnys-thanksgiving-half-day-2025",
        "xnys-thanksgiving-half-day-flag-2025",
        "xnys-dst-before-2026",
        "xnys-dst-after-2026",
    }
    assert all(item.passed for item in checks)


def test_anchor_check_fails_if_holiday_is_materialized_as_session() -> None:
    rows = _anchor_rows()
    rows.append(
        {
            "session_date": date(2025, 7, 4),
            "open": _utc(2025, 7, 4, 13, 30),
            "close": _utc(2025, 7, 4, 20, 0),
        }
    )
    evidence = materialize_calendar_evidence_from_rows(
        rows,
        market_id="XNYS",
        timezone="America/New_York",
        source="fixture:XNYS",
        source_revision=RECOMMENDED_EXCHANGE_CALENDARS_VERSION,
    )

    checks = {item.check_id: item for item in validate_xnys_research_anchors(evidence)}
    assert checks["xnys-independence-day-2025"].passed is False


def test_materialization_report_binds_version_calendar_and_boundary() -> None:
    spec = ExchangeCalendarMaterializationSpec(
        requested_start=date(2025, 7, 1),
        requested_end=date(2026, 3, 31),
    )
    evidence = _anchor_evidence()
    checks = validate_xnys_research_anchors(evidence)
    report = TradingCalendarMaterializationReport(
        spec=spec,
        evidence=evidence,
        observed_package_version=RECOMMENDED_EXCHANGE_CALENDARS_VERSION,
        anchor_checks=checks,
        materialized_at=_utc(2026, 9, 1, 7, 30),
    )

    assert report.coverage_boundary_passed is True
    assert report.passed is True
    assert report.report_id.startswith("calendar-materialization-")
    assert report.to_dict()["evidence"]["calendar_id"] == evidence.calendar_id

    changed = replace(spec, expected_package_version="4.13.1")
    assert changed.spec_id != spec.spec_id
    with pytest.raises(ValueError, match="version does not match"):
        replace(report, spec=changed)


def test_materialization_report_fails_when_anchor_fails() -> None:
    spec = ExchangeCalendarMaterializationSpec(
        requested_start=date(2025, 7, 1),
        requested_end=date(2026, 3, 31),
    )
    report = TradingCalendarMaterializationReport(
        spec=spec,
        evidence=_anchor_evidence(),
        observed_package_version=RECOMMENDED_EXCHANGE_CALENDARS_VERSION,
        anchor_checks=(CalendarAnchorCheck("forced-failure", False, "fixture"),),
        materialized_at=_utc(2026, 9, 1, 7, 30),
    )

    assert report.coverage_boundary_passed is True
    assert report.passed is False
