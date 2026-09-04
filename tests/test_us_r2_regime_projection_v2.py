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
from finagent.research.us_r2_regime_projection_v2 import (
    build_us_r2_regime_projection_evidence_v2,
    build_us_r2_regime_projection_plan_v2,
    canonical_us_r2_regime_endpoint_policy,
)


def _sessions() -> tuple[TradingSession, ...]:
    frozen = canonical_us_r2_frozen_protocol()
    dates: list[date] = []
    for fold in frozen.walk_forward_protocol.folds:
        dates.extend(fold.train_end - timedelta(days=offset) for offset in range(80, 0, -1))
        dates.extend(fold.evaluation_start + timedelta(days=offset) for offset in range(100))
    unique_dates = tuple(sorted(dict.fromkeys(dates)))
    return tuple(
        TradingSession(
            session_date=session_date,
            open_at=datetime.combine(session_date, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=14, minutes=30),
            close_at=datetime.combine(session_date, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=15, minutes=30),
            is_half_day=False,
        )
        for session_date in unique_dates
    )


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="UTC",
        source="synthetic",
        source_revision="endpoint-v2-test",
        sessions=_sessions(),
        regular_session_minutes=60,
    )


def _source_plan(
    *,
    bad_open_endpoint: date | None = None,
    assets: tuple[str, ...] = ("IWM",),
) -> tuple[MinuteQueryPlan, SessionizationEvidence]:
    calendar = _calendar()
    values: list[str] = []
    for index, session in enumerate(calendar.sessions):
        first_offset = 15 if session.session_date == bad_open_endpoint else 0
        last_offset = 59
        sign = -1.0 if index % 6 in {0, 1, 2} else 1.0
        magnitude = 0.003 if index % 10 < 5 else 0.018
        open_price = 100.0 + index * 0.02
        close_price = open_price * (1.0 + sign * magnitude)
        first_time = session.open_at + timedelta(minutes=first_offset)
        last_time = session.open_at + timedelta(minutes=last_offset)
        values.append(
            "("
            f"DATE '{session.session_date.isoformat()}', "
            f"TIMESTAMPTZ '{first_time.isoformat()}', "
            f"{open_price!r}::DOUBLE, {open_price!r}::DOUBLE, "
            f"{first_offset}::BIGINT, true"
            ")"
        )
        values.append(
            "("
            f"DATE '{session.session_date.isoformat()}', "
            f"TIMESTAMPTZ '{last_time.isoformat()}', "
            f"{close_price!r}::DOUBLE, {close_price!r}::DOUBLE, "
            f"{last_offset}::BIGINT, true"
            ")"
        )
    sql = (
        "SELECT * FROM (VALUES\n"
        + ",\n".join(values)
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
        manifest_id="synthetic-manifest-v2",
        data_version="synthetic-sessionized-endpoint-v2",
        sql=sql,
        partition_months=("synthetic",),
        selected_size_bytes=2048,
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
        spec_id="synthetic-sessionization-spec-v2",
        calendar_id=calendar.calendar_id,
        base_plan_id="synthetic-base-plan-v2",
        sessionized_plan_id=plan.plan_id,
        source_data_version="synthetic-raw-v2",
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


def _materialization(plan, row_count: int, digest: str = "0") -> MinuteMaterialization:
    return MinuteMaterialization(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        row_count=row_count,
        size_bytes=4096,
        content_sha256=digest * 64,
        output_filename="us_r2_regime_projection_v2.parquet",
    )


def test_v2_accepts_sparse_interior_when_session_endpoints_are_bounded() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan()
    plan = build_us_r2_regime_projection_plan_v2(
        source_plan,
        sessionization,
        calendar,
        canonical_us_r2_frozen_protocol(),
    )
    rows = _execute(plan)

    assert plan.endpoint_policy == canonical_us_r2_regime_endpoint_policy()
    assert plan.endpoint_policy.endpoint_band_minutes == 15
    assert plan.endpoint_policy.interior_minute_completeness_required is False
    assert plan.to_dict()["source_scan_asset_count"] == 1
    assert plan.to_dict()["candidate_dependent_scan"] is False
    assert plan.to_dict()["current_session_return_emitted"] is False
    assert plan.to_dict()["source_price_emitted"] is False
    assert len(rows) == sum(count for _fold_id, count in plan.expected_evaluation_sessions)
    assert any(row["regime_available"] is True for row in rows)
    assert all(row["endpoint_policy_id"] == plan.endpoint_policy.policy_id for row in rows)
    assert all(
        row["regime_source_end_session"] is None
        or row["regime_source_end_session"] < row["session_date"]
        for row in rows
    )


def test_endpoint_gap_breaks_calendar_consecutive_lookback() -> None:
    calendar = _calendar()
    missing_endpoint_session = date(2005, 12, 31)
    assert calendar.is_session(missing_endpoint_session)
    source_plan, sessionization = _source_plan(bad_open_endpoint=missing_endpoint_session)
    plan = build_us_r2_regime_projection_plan_v2(
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


def test_v2_rejects_multi_asset_source_query() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan(assets=("IWM", "AAPL"))
    with pytest.raises(ValueError, match="IWM only"):
        build_us_r2_regime_projection_plan_v2(
            source_plan,
            sessionization,
            calendar,
            canonical_us_r2_frozen_protocol(),
        )


def test_v2_evidence_exposes_reason_counts_and_fails_sparse_regimes() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan()
    plan = build_us_r2_regime_projection_plan_v2(
        source_plan,
        sessionization,
        calendar,
        canonical_us_r2_frozen_protocol(),
    )
    rows = _execute(plan)
    evidence = build_us_r2_regime_projection_evidence_v2(
        plan,
        _materialization(plan, len(rows)),
        rows,
    )

    assert evidence.minimum_sessions_per_regime == 20
    assert all(len(summary.unavailable_reason_counts) == 3 for summary in evidence.fold_summaries)
    if not evidence.passed:
        assert any(item.startswith("insufficient_regime_sessions:") for item in evidence.blockers)


def test_v2_evidence_passes_only_with_at_least_20_sessions_per_regime() -> None:
    calendar = _calendar()
    source_plan, sessionization = _source_plan()
    plan = build_us_r2_regime_projection_plan_v2(
        source_plan,
        sessionization,
        calendar,
        canonical_us_r2_frozen_protocol(),
    )
    labels = ("DOWN_HIGH_VOL", "DOWN_LOW_VOL", "UP_HIGH_VOL", "UP_LOW_VOL")
    rows: list[dict[str, object]] = []
    for fold_index, (fold_id, expected_count) in enumerate(plan.expected_evaluation_sessions):
        assert expected_count >= 80
        start = date(2030 + fold_index, 1, 1)
        for offset in range(expected_count):
            session_date = start + timedelta(days=offset)
            rows.append(
                {
                    "fold_id": fold_id,
                    "session_date": session_date,
                    "regime_source_end_session": session_date - timedelta(days=1),
                    "regime_source_session_count": 20,
                    "regime_direction": 0.01 if offset % 2 else -0.01,
                    "regime_volatility": 0.02 + (offset % 7) * 0.001,
                    "train_volatility_threshold": 0.023,
                    "train_volatility_observation_count": 200,
                    "regime_label": labels[offset % 4],
                    "regime_available": True,
                    "unavailable_reason": None,
                    "endpoint_policy_id": plan.endpoint_policy.policy_id,
                    "frozen_protocol_id": plan.frozen_protocol_id,
                    "data_version": plan.data_version,
                }
            )
    evidence = build_us_r2_regime_projection_evidence_v2(
        plan,
        _materialization(plan, len(rows), digest="1"),
        rows,
    )

    assert evidence.passed is True
    assert evidence.blockers == ()
    assert all(min(dict(summary.label_counts).values()) >= 20 for summary in evidence.fold_summaries)
