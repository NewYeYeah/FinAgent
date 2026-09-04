from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import duckdb
import pytest

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import SessionizationEvidence
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.us_r2_frozen_protocol import canonical_us_r2_frozen_protocol
from finagent.research.us_r2_regime_projection import (
    build_us_r2_regime_projection_evidence,
    build_us_r2_regime_projection_plan,
)


def _sessions() -> tuple[TradingSession, ...]:
    evaluation_starts = (
        date(2006, 1, 1),
        date(2010, 1, 1),
        date(2014, 1, 1),
        date(2018, 1, 1),
        date(2022, 1, 1),
    )
    dates: list[date] = []
    for evaluation_start in evaluation_starts:
        dates.extend(evaluation_start - timedelta(days=offset) for offset in range(30, 0, -1))
        dates.extend(evaluation_start + timedelta(days=offset) for offset in range(8))
    unique_dates = tuple(sorted(dict.fromkeys(dates)))
    return tuple(
        TradingSession(
            session_date=session_date,
            open_at=datetime.combine(session_date, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=14, minutes=30),
            close_at=datetime.combine(session_date, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=14, minutes=31),
            is_half_day=False,
        )
        for session_date in unique_dates
    )


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="UTC",
        source="synthetic",
        source_revision="test",
        sessions=_sessions(),
        regular_session_minutes=1,
    )


def _source_plan(*, drop_session: date | None = None, assets: tuple[str, ...] = ("IWM",)) -> tuple[MinuteQueryPlan, SessionizationEvidence]:
    calendar = _calendar()
    rows = []
    for index, session in enumerate(calendar.sessions):
        if session.session_date == drop_session:
            continue
        signed = -1.0 if index % 4 in {0, 1} else 1.0
        magnitude = 0.002 if index % 8 < 4 else 0.012
        open_price = 100.0 + index * 0.01
        close_price = open_price * (1.0 + signed * magnitude)
        rows.append(
            "("
            f"DATE '{session.session_date.isoformat()}', "
            f"TIMESTAMPTZ '{session.open_at.isoformat()}', "
            f"{open_price!r}::DOUBLE, {close_price!r}::DOUBLE, 0::BIGINT, true"
            ")"
        )
    sql = (
        "SELECT * FROM (VALUES\n"
        + ",\n".join(rows)
        + ") AS source_rows(session_date, event_time, open, close, minute_offset, is_regular_session)"
    )
    query = MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=calendar.sessions[0].open_at,
        end=calendar.sessions[-1].close_at,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.OPEN, MarketDataField.CLOSE),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )
    plan = MinuteQueryPlan(
        query=query,
        manifest_id="synthetic-manifest",
        data_version="synthetic-sessionized-v1",
        sql=sql,
        partition_months=("synthetic",),
        selected_size_bytes=1234,
        output_columns=(
            "session_date",
            "event_time",
            "open",
            "close",
            "minute_offset",
            "is_regular_session",
        ),
    )
    evidence = SessionizationEvidence(
        spec_id="synthetic-sessionization-spec",
        calendar_id=calendar.calendar_id,
        base_plan_id="synthetic-base-plan",
        sessionized_plan_id=plan.plan_id,
        source_data_version="synthetic-raw-v1",
        sessionized_data_version=plan.data_version,
    )
    return plan, evidence


def _execute(plan) -> tuple[dict[str, object], ...]:
    connection = duckdb.connect(database=":memory:")
    try:
        cursor = connection.execute(plan.sql)
        columns = tuple(str(item[0]) for item in cursor.description)
        return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
    finally:
        connection.close()


def test_projection_scans_iwm_once_and_emits_only_lagged_market_state() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan()
    frozen = canonical_us_r2_frozen_protocol()
    plan = build_us_r2_regime_projection_plan(source_plan, sessionization, calendar, frozen)
    rows = _execute(plan)

    assert plan.to_dict()["source_scan_asset_count"] == 1
    assert plan.to_dict()["candidate_dependent_scan"] is False
    assert plan.to_dict()["current_session_return_emitted"] is False
    assert "session_return" not in plan.output_columns
    assert len(rows) == sum(count for _fold_id, count in plan.expected_evaluation_sessions)
    assert all(row["regime_source_end_session"] < row["session_date"] for row in rows)
    assert all(row["train_volatility_observation_count"] > 0 for row in rows)
    assert any(row["regime_available"] is True for row in rows)


def test_missing_calendar_session_source_row_breaks_consecutive_lookback() -> None:
    calendar = _calendar()
    # Remove a late TRAIN session immediately before the first evaluation window. The calendar
    # session remains present, so rolling count must fall below 20 instead of silently skipping it.
    missing = date(2005, 12, 31)
    source_plan, sessionization = _source_plan(drop_session=missing)
    plan = build_us_r2_regime_projection_plan(
        source_plan,
        sessionization,
        calendar,
        canonical_us_r2_frozen_protocol(),
    )
    rows = _execute(plan)
    first_fold = [row for row in rows if row["fold_id"] == "us-r2-fold-01"]

    assert first_fold
    assert any(row["regime_available"] is False for row in first_fold)
    assert any(row["unavailable_reason"] == "REGIME_LOOKBACK_INCOMPLETE" for row in first_fold)


def test_projection_rejects_multi_asset_source_query() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan(assets=("IWM", "AAPL"))
    with pytest.raises(ValueError, match="IWM only"):
        build_us_r2_regime_projection_plan(
            source_plan,
            sessionization,
            calendar,
            canonical_us_r2_frozen_protocol(),
        )


def test_projection_evidence_requires_all_four_regimes_in_every_fold() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan()
    plan = build_us_r2_regime_projection_plan(
        source_plan,
        sessionization,
        calendar,
        canonical_us_r2_frozen_protocol(),
    )
    source_rows = _execute(plan)
    rows = [dict(row) for row in source_rows]
    first_fold = [row for row in rows if row["fold_id"] == "us-r2-fold-01"]
    assert any(row["regime_label"] == "DOWN_HIGH_VOL" for row in first_fold)
    for row in first_fold:
        if row["regime_label"] == "DOWN_HIGH_VOL":
            row["regime_label"] = "DOWN_LOW_VOL"
    materialization = MinuteMaterialization(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        row_count=len(rows),
        size_bytes=1024,
        content_sha256="0" * 64,
        output_filename="us_r2_regime_projection.parquet",
    )
    evidence = build_us_r2_regime_projection_evidence(plan, materialization, rows)

    missing_blockers = [item for item in evidence.blockers if item.startswith("missing_expected_regimes:")]
    assert "missing_expected_regimes:us-r2-fold-01:DOWN_HIGH_VOL" in missing_blockers
    assert evidence.passed is False


def test_projection_evidence_passes_for_complete_manual_four_state_surface() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan()
    base_plan = build_us_r2_regime_projection_plan(
        source_plan,
        sessionization,
        calendar,
        canonical_us_r2_frozen_protocol(),
    )
    labels = ("DOWN_HIGH_VOL", "DOWN_LOW_VOL", "UP_HIGH_VOL", "UP_LOW_VOL")
    rows: list[dict[str, object]] = []
    for fold_index, (fold_id, expected_count) in enumerate(base_plan.expected_evaluation_sessions):
        start = date(2030 + fold_index, 1, 1)
        for offset in range(expected_count):
            rows.append(
                {
                    "fold_id": fold_id,
                    "session_date": start + timedelta(days=offset),
                    "regime_source_end_session": start + timedelta(days=offset - 1),
                    "regime_direction": 0.01 if offset % 2 else -0.01,
                    "regime_volatility": 0.02 + offset * 0.001,
                    "train_volatility_threshold": 0.023,
                    "train_volatility_observation_count": 100,
                    "regime_label": labels[offset % 4],
                    "regime_available": True,
                    "unavailable_reason": None,
                    "frozen_protocol_id": base_plan.frozen_protocol_id,
                    "data_version": base_plan.data_version,
                }
            )
    materialization = MinuteMaterialization(
        plan_id=base_plan.plan_id,
        data_version=base_plan.data_version,
        row_count=len(rows),
        size_bytes=2048,
        content_sha256="1" * 64,
        output_filename="us_r2_regime_projection.parquet",
    )
    evidence = build_us_r2_regime_projection_evidence(base_plan, materialization, rows)

    assert evidence.passed is True
    assert evidence.blockers == ()
    assert all(summary.observed_regimes == tuple(sorted(labels)) for summary in evidence.fold_summaries)
