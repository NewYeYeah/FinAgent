from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import duckdb
import pytest

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import (
    LabelMaterializationSpec,
    ResamplingSpec,
    SessionizationEvidence,
    build_resampled_minute_plan,
    build_same_session_label_plan,
    canonical_same_session_60m_label_spec,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.us_r2_base_panel import (
    FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
    FROZEN_REGIME_PROJECTION_V2_MATERIALIZATION_ID,
    FROZEN_REGIME_PROJECTION_V2_PLAN_ID,
    build_us_r2_annual_base_panel_evidence,
    build_us_r2_annual_base_panel_plan,
    build_us_r2_base_panel_summary_plan,
    validate_us_r2_regime_projection_v2_gate,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    canonical_us_r2_frozen_protocol,
)
from finagent.research.us_r2_regime_projection_v2 import (
    canonical_us_r2_regime_endpoint_policy,
)


def _calendar() -> TradingCalendarEvidence:
    sessions = []
    for day in (2, 3, 4):
        session_date = date(2001, 1, day)
        open_at = datetime(2001, 1, day, 14, 30, tzinfo=UTC)
        sessions.append(
            TradingSession(
                session_date=session_date,
                open_at=open_at,
                close_at=open_at + timedelta(minutes=90),
                is_half_day=False,
            )
        )
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="UTC",
        source="synthetic",
        source_revision="r2-base-panel-test",
        sessions=tuple(sessions),
        regular_session_minutes=90,
    )


def _source_plan() -> tuple[MinuteQueryPlan, SessionizationEvidence]:
    calendar = _calendar()
    rows: list[str] = []
    for asset_index, asset in enumerate(FROZEN_ASSETS):
        for session_index, session in enumerate(calendar.sessions):
            for minute_offset in range(90):
                if asset == FROZEN_ASSETS[0] and session_index == 1 and minute_offset == 14:
                    continue
                if asset == FROZEN_ASSETS[1] and session_index == 2 and minute_offset == 74:
                    continue
                event_time = session.open_at + timedelta(minutes=minute_offset)
                available_at = event_time + timedelta(minutes=1)
                base = 100.0 + asset_index + session_index * 0.5 + minute_offset * 0.001
                rows.append(
                    "("
                    f"{asset!r}, DATE '{session.session_date.isoformat()}', "
                    f"TIMESTAMPTZ '{event_time.isoformat()}', "
                    f"TIMESTAMPTZ '{available_at.isoformat()}', "
                    f"{base!r}::DOUBLE, {(base + 0.2)!r}::DOUBLE, {(base - 0.2)!r}::DOUBLE, "
                    f"{(base + 0.05)!r}::DOUBLE, {(1000.0 + minute_offset)!r}::DOUBLE, "
                    f"'XNYS:{session.session_date.isoformat()}', "
                    f"TIMESTAMPTZ '{session.open_at.isoformat()}', "
                    f"TIMESTAMPTZ '{session.close_at.isoformat()}', "
                    f"{minute_offset}::BIGINT, true, 'synthetic', 'test-revision'"
                    ")"
                )
    sql = (
        "SELECT * FROM (VALUES\n"
        + ",\n".join(rows)
        + ") AS synthetic_source_scan("
        "research_asset_id, session_date, event_time, available_at, open, high, low, close, volume, "
        "session_id, session_open, session_close, minute_offset, is_regular_session, source_id, source_revision)"
    )
    query = MarketDataQuery(
        market_id="XNYS",
        assets=FROZEN_ASSETS,
        start=calendar.sessions[0].open_at,
        end=calendar.sessions[-1].close_at,
        interval=BarInterval.MINUTE_1,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )
    plan = MinuteQueryPlan(
        query=query,
        manifest_id="synthetic-manifest",
        data_version="synthetic-sessionized-data-v1",
        sql=sql,
        partition_months=("2001-01",),
        selected_size_bytes=123456,
        output_columns=(
            "research_asset_id",
            "session_date",
            "event_time",
            "available_at",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "session_id",
            "session_open",
            "session_close",
            "minute_offset",
            "is_regular_session",
            "source_id",
            "source_revision",
        ),
    )
    sessionization = SessionizationEvidence(
        spec_id="synthetic-sessionization-spec",
        calendar_id=calendar.calendar_id,
        base_plan_id="synthetic-base-plan",
        sessionized_plan_id=plan.plan_id,
        source_data_version="synthetic-raw-v1",
        sessionized_data_version=plan.data_version,
    )
    return plan, sessionization


def _regime_document() -> dict[str, object]:
    frozen = canonical_us_r2_frozen_protocol()
    labels = frozen.classifier_policy.labels
    return {
        "schema_version": "finagent.us-r2-regime-projection-evidence.v2",
        "evidence_id": FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
        "plan_id": FROZEN_REGIME_PROJECTION_V2_PLAN_ID,
        "frozen_protocol_id": frozen.freeze_id,
        "endpoint_policy_id": canonical_us_r2_regime_endpoint_policy().policy_id,
        "materialization_id": FROZEN_REGIME_PROJECTION_V2_MATERIALIZATION_ID,
        "materialized_row_count": 5092,
        "minimum_sessions_per_regime": 20,
        "fold_summaries": [
            {
                "fold_id": f"us-r2-fold-{ordinal:02d}",
                "label_counts": {label: 20 + ordinal for label in labels},
            }
            for ordinal in range(1, 6)
        ],
        "blockers": [],
        "passed": True,
        "candidate_performance_read": False,
        "candidate_dependent_scan": False,
    }


def _execute(sql: str) -> tuple[dict[str, object], ...]:
    connection = duckdb.connect(database=":memory:")
    try:
        cursor = connection.execute(sql)
        columns = tuple(str(item[0]) for item in cursor.description)
        return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
    finally:
        connection.close()


def _reference_rows(
    source_plan: MinuteQueryPlan,
    sessionization: SessionizationEvidence,
) -> tuple[dict[str, object], ...]:
    calendar = _calendar()
    start = calendar.sessions[0].open_at
    end = calendar.sessions[-1].close_at + timedelta(minutes=1)
    bar_query = MarketDataQuery(
        market_id="XNYS",
        assets=FROZEN_ASSETS,
        start=start,
        end=end,
        interval=BarInterval.MINUTE_15,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    bars, _ = build_resampled_minute_plan(
        source_plan,
        sessionization,
        bar_query,
        ResamplingSpec(calendar_id=calendar.calendar_id, target_interval=BarInterval.MINUTE_15),
    )
    label_query = MarketDataQuery(
        market_id="XNYS",
        assets=FROZEN_ASSETS,
        start=start,
        end=end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    label_spec = canonical_same_session_60m_label_spec()
    labels, _ = build_same_session_label_plan(
        source_plan,
        sessionization,
        label_query,
        LabelMaterializationSpec(label_spec=label_spec, calendar_id=calendar.calendar_id),
    )
    sql = f"""
        WITH bars AS (
            {bars.sql}
        ),
        labels AS (
            {labels.sql}
        )
        SELECT
            b.research_asset_id,
            b.session_date,
            b.event_time,
            b.available_at,
            b.bar_index,
            CAST(b.open AS DOUBLE) AS open,
            CAST(b.high AS DOUBLE) AS high,
            CAST(b.low AS DOUBLE) AS low,
            CAST(b.close AS DOUBLE) AS close,
            CAST(b.volume AS DOUBLE) AS volume,
            b.observed_minute_count,
            b.expected_minute_count,
            b.coverage_ratio,
            b.is_complete,
            l.source_available_at,
            CAST(l.source_price AS DOUBLE) AS source_price,
            l.target_available_at,
            CAST(l.label_value AS DOUBLE) AS label_value,
            l.label_available,
            l.unavailable_reason,
            l.source_available_at IS NOT NULL AS label_row_present,
            CASE
                WHEN l.source_price IS NULL THEN NULL
                ELSE abs(CAST(b.close AS DOUBLE) - CAST(l.source_price AS DOUBLE))
            END AS close_anchor_difference
        FROM bars AS b
        LEFT JOIN labels AS l
          ON l.research_asset_id = b.research_asset_id
         AND l.session_date = b.session_date
         AND l.source_available_at = b.available_at
        WHERE EXTRACT(year FROM b.session_date) = 2001
        ORDER BY b.available_at, b.research_asset_id
    """
    return _execute(sql)


def _float_hex(value: object) -> str | None:
    if value is None:
        return None
    return float(value).hex()


def test_real_regime_gate_is_bound_and_fail_closed() -> None:
    assert validate_us_r2_regime_projection_v2_gate(_regime_document()) == (
        FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID
    )

    changed = _regime_document()
    changed["passed"] = False
    with pytest.raises(ValueError, match="passed blocker-free"):
        validate_us_r2_regime_projection_v2_gate(changed)

    changed = _regime_document()
    fold_summaries = changed["fold_summaries"]
    assert isinstance(fold_summaries, list)
    first = fold_summaries[0]
    assert isinstance(first, dict)
    label_counts = first["label_counts"]
    assert isinstance(label_counts, dict)
    label_counts["DOWN_LOW_VOL"] = 19
    with pytest.raises(ValueError, match="falls below"):
        validate_us_r2_regime_projection_v2_gate(changed)


def test_base_panel_uses_one_shared_materialized_source_relation() -> None:
    source_plan, sessionization = _source_plan()
    plan = build_us_r2_annual_base_panel_plan(
        source_plan,
        sessionization,
        year=2001,
        regime_projection_evidence_id=FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
    )

    assert plan.sql.count("WITH source_rows AS MATERIALIZED") == 1
    assert plan.sql.count(source_plan.sql) == 1
    assert plan.to_dict()["source_scan_relation_count"] == 1
    assert plan.to_dict()["candidate_dependent_scan"] is False
    assert plan.to_dict()["candidate_performance_read"] is False


def test_base_panel_is_bitwise_equal_to_existing_15m_and_60m_semantics() -> None:
    source_plan, sessionization = _source_plan()
    plan = build_us_r2_annual_base_panel_plan(
        source_plan,
        sessionization,
        year=2001,
        regime_projection_evidence_id=FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
    )
    observed = _execute(plan.sql)
    reference = _reference_rows(source_plan, sessionization)

    assert len(observed) == len(reference)
    keys = ("research_asset_id", "session_date", "event_time", "available_at", "bar_index")
    numeric = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "coverage_ratio",
        "source_price",
        "label_value",
        "close_anchor_difference",
    )
    exact = (
        "observed_minute_count",
        "expected_minute_count",
        "is_complete",
        "source_available_at",
        "target_available_at",
        "label_available",
        "unavailable_reason",
        "label_row_present",
    )
    for left, right in zip(observed, reference, strict=True):
        assert tuple(left[item] for item in keys) == tuple(right[item] for item in keys)
        for field in numeric:
            assert _float_hex(left[field]) == _float_hex(right[field]), field
        for field in exact:
            assert left[field] == right[field], field


def test_summary_is_row_free_and_preserves_dynamic_cross_section() -> None:
    source_plan, sessionization = _source_plan()
    plan = build_us_r2_annual_base_panel_plan(
        source_plan,
        sessionization,
        year=2001,
        regime_projection_evidence_id=FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
    )
    rows = _execute(plan.sql)
    summary_plan = build_us_r2_base_panel_summary_plan(
        plan,
        relation_sql=plan.sql,
    )
    summary_rows = _execute(summary_plan.sql)
    assert len(summary_rows) == 1
    materialization = MinuteMaterialization(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        row_count=len(rows),
        size_bytes=4096,
        content_sha256="0" * 64,
        output_filename="us_r2_15m60m_base.parquet",
    )
    evidence = build_us_r2_annual_base_panel_evidence(
        plan,
        materialization,
        summary_rows[0],
    )

    assert evidence.passed is True
    assert evidence.blockers == ()
    assert evidence.asset_count == len(FROZEN_ASSETS)
    assert evidence.maximum_joint_breadth >= 10
    assert evidence.formation_count_at_minimum_cross_section > 0


def test_base_panel_rejects_partial_source_universe() -> None:
    source_plan, sessionization = _source_plan()
    bad_query = MarketDataQuery(
        market_id=source_plan.query.market_id,
        assets=FROZEN_ASSETS[:-1],
        start=source_plan.query.start,
        end=source_plan.query.end,
        interval=source_plan.query.interval,
        fields=source_plan.query.fields,
        session_policy=source_plan.query.session_policy,
        adjustment_policy=source_plan.query.adjustment_policy,
        availability_policy=source_plan.query.availability_policy,
    )
    bad_plan = MinuteQueryPlan(
        query=bad_query,
        manifest_id=source_plan.manifest_id,
        data_version=source_plan.data_version,
        sql=source_plan.sql,
        partition_months=source_plan.partition_months,
        selected_size_bytes=source_plan.selected_size_bytes,
        output_columns=source_plan.output_columns,
    )
    with pytest.raises(ValueError, match="complete frozen 25-name"):
        build_us_r2_annual_base_panel_plan(
            bad_plan,
            sessionization,
            year=2001,
            regime_projection_evidence_id=FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
        )
