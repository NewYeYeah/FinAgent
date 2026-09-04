from __future__ import annotations

from datetime import UTC, datetime, timedelta

from finagent.data.us_minute.reconciliation import (
    MinuteReferenceReconciliationPolicy,
    MinuteReferenceReconciliationReport,
    ReferenceMinuteBar,
    reconcile_reference_symbol,
)
from scripts.reconcile_us_minute_mt5 import _select_reference_mappings


def _bars(*, offset_minutes: int = 0, price_shift: float = 0.0, count: int = 120):
    start = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    return tuple(
        ReferenceMinuteBar(
            timestamp=start + timedelta(minutes=index + offset_minutes),
            close=100.0 + index * 0.01 + price_shift,
            volume=1000.0 if offset_minutes == 0 else None,
            tick_volume=500.0 if offset_minutes != 0 else None,
            real_volume=0.0 if offset_minutes != 0 else None,
        )
        for index in range(count)
    )


def _policy() -> MinuteReferenceReconciliationPolicy:
    return MinuteReferenceReconciliationPolicy(
        start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
        end=datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
        required_symbol_count=1,
        minimum_rows_per_symbol=100,
        minimum_aligned_overlap_ratio=0.8,
        maximum_abs_offset_minutes=360,
    )


def test_reconciliation_detects_broker_timestamp_offset_without_rewriting_source() -> None:
    check = reconcile_reference_symbol(
        "MSFT",
        "MSFT",
        _bars(),
        _bars(offset_minutes=180, price_shift=0.05),
        policy=_policy(),
    )

    assert check.exact_overlap_count == 0
    assert check.best_broker_to_research_offset_minutes == -180
    assert check.aligned_overlap_count == 120
    assert check.aligned_overlap_ratio == 1.0
    assert check.median_close_relative_difference is not None
    assert check.median_close_relative_difference > 0


def test_reconciliation_report_passes_structural_overlap_and_preserves_price_difference() -> None:
    policy = _policy()
    check = reconcile_reference_symbol(
        "MSFT",
        "MSFT",
        _bars(),
        _bars(offset_minutes=180, price_shift=0.10),
        policy=policy,
    )
    report = MinuteReferenceReconciliationReport(
        policy=policy,
        source_revision="776328445b7ac6e7815ef3a483e9c8ded1eb6d56",
        source_data_version="minute-data-version-1",
        calendar_id="trading-calendar-03a9c29f566d6634aedbbbdc",
        mt5_probe_id="mt5-probe-1",
        broker_server="MetaQuotes-Demo",
        symbol_checks=(check,),
        retrieved_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
    )

    assert report.passed
    assert report.blockers == ()
    assert report.report_id.startswith("minute-reference-reconciliation-")
    assert "price_difference:diagnostic_not_adjustment_authority" in report.to_dict()["limitations"]


def test_low_overlap_fails_closed() -> None:
    policy = _policy()
    check = reconcile_reference_symbol(
        "MSFT",
        "MSFT",
        _bars(count=120),
        _bars(offset_minutes=180, count=20),
        policy=policy,
    )
    report = MinuteReferenceReconciliationReport(
        policy=policy,
        source_revision="revision",
        source_data_version="data-version",
        calendar_id="calendar",
        mt5_probe_id="probe",
        broker_server="server",
        symbol_checks=(check,),
        retrieved_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
    )

    assert not report.passed
    assert "symbol:MSFT:broker_rows_insufficient" in report.blockers


def test_explicit_reference_selection_preserves_reviewed_order() -> None:
    mappings = (("NVDA", "NVDA.NAS"), ("IWM", "IWM.NYS"), ("GLD", "GLD.NYS"))

    selected = _select_reference_mappings(mappings, ("GLD", "IWM"), 2)

    assert selected == (("GLD", "GLD.NYS"), ("IWM", "IWM.NYS"))


def test_explicit_reference_selection_rejects_count_or_universe_drift() -> None:
    mappings = (("IWM", "IWM.NYS"), ("GLD", "GLD.NYS"))

    try:
        _select_reference_mappings(mappings, ("IWM",), 2)
    except ValueError as exc:
        assert "count must equal" in str(exc)
    else:
        raise AssertionError("expected explicit reference-count mismatch")

    try:
        _select_reference_mappings(mappings, ("IWM", "EEM"), 2)
    except ValueError as exc:
        assert "absent from the accepted EngineeringUniverse" in str(exc)
    else:
        raise AssertionError("expected missing accepted reference mapping")
