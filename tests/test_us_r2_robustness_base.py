from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan, fetch_plan_rows
from finagent.data.minute_transform import (
    LabelMaterializationSpec,
    ResamplingSpec,
    SessionizationEvidence,
    build_resampled_minute_plan,
    build_same_session_label_plan,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.us_r1_materialization_evidence import canonical_us_r1_label_spec
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r2_frozen_protocol import FROZEN_ASSETS, FROZEN_CALENDAR_ID
from finagent.research.us_r2_robustness_base import (
    FROZEN_POOLED_INFERENCE_REPORT_ID,
    ROBUSTNESS_BASE_EVIDENCE_FILENAME,
    ROBUSTNESS_BASE_FILENAME,
    ROBUSTNESS_BASE_PLAN_FILENAME,
    build_us_r2_annual_robustness_base_evidence,
    build_us_r2_annual_robustness_base_plan,
    build_us_r2_robustness_summary_plan,
    canonical_us_r2_robustness_materialization_policy,
    canonical_us_r2_robustness_slices,
)
from finagent.research.us_r2_robustness_batch import (
    inspect_completed_us_r2_annual_robustness_base,
    materialize_us_r2_robustness_batch,
    us_r2_annual_robustness_paths,
)


@dataclass(frozen=True, slots=True)
class _TestPlan:
    plan_id: str
    data_version: str
    sql: str
    output_columns: tuple[str, ...]


def _calendar() -> TradingCalendarEvidence:
    sessions = []
    for day in (3, 4, 5):
        session_date = date(2006, 1, day)
        open_at = datetime(2006, 1, day, 14, 30, tzinfo=UTC)
        sessions.append(
            TradingSession(
                session_date=session_date,
                open_at=open_at,
                close_at=open_at + timedelta(minutes=180),
                is_half_day=False,
            )
        )
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="UTC",
        source="synthetic",
        source_revision="r2-robustness-test",
        sessions=tuple(sessions),
        regular_session_minutes=180,
    )


def _source_plan() -> tuple[MinuteQueryPlan, SessionizationEvidence]:
    calendar = _calendar()
    rows: list[str] = []
    for asset_index, asset in enumerate(FROZEN_ASSETS):
        for session_index, session in enumerate(calendar.sessions):
            for minute_offset in range(180):
                # Exercise incomplete bars and exact target-minute missingness.
                if asset == FROZEN_ASSETS[0] and session_index == 0 and minute_offset == 14:
                    continue
                if asset == FROZEN_ASSETS[1] and session_index == 1 and minute_offset == 64:
                    continue
                event_time = session.open_at + timedelta(minutes=minute_offset)
                available_at = event_time + timedelta(minutes=1)
                base = 100.0 + asset_index + session_index * 0.25 + minute_offset * 0.001
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
                    f"{minute_offset}::BIGINT, true, false, 'synthetic', 'test-revision'"
                    ")"
                )
    sql = (
        "SELECT * FROM (VALUES\n"
        + ",\n".join(rows)
        + ") AS synthetic_source_scan("
        "research_asset_id, session_date, event_time, available_at, open, high, low, close, volume, "
        "session_id, session_open, session_close, minute_offset, is_regular_session, is_half_day, "
        "source_id, source_revision)"
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
        partition_months=("2006-01",),
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
            "is_half_day",
            "source_id",
            "source_revision",
        ),
    )
    evidence = SessionizationEvidence(
        spec_id="synthetic-sessionization-spec",
        calendar_id=FROZEN_CALENDAR_ID,
        base_plan_id="synthetic-base-plan",
        sessionized_plan_id=plan.plan_id,
        source_data_version="synthetic-raw-v1",
        sessionized_data_version=plan.data_version,
    )
    return plan, evidence


def _execute(sql: str) -> tuple[dict[str, object], ...]:
    connection = duckdb.connect(database=":memory:")
    try:
        cursor = connection.execute(f"SELECT * FROM ({sql}) AS described_query LIMIT 0")
        columns = tuple(str(item[0]) for item in cursor.description)
    finally:
        connection.close()
    return fetch_plan_rows(
        _TestPlan(
            plan_id="synthetic-test-plan",
            data_version="synthetic-test-data-version",
            sql=sql,
            output_columns=columns,
        ),
        limit=100_000,
    )


def _reference_slice_rows(
    source_plan: MinuteQueryPlan,
    sessionization: SessionizationEvidence,
    *,
    interval: BarInterval,
    horizon: int,
) -> tuple[dict[str, object], ...]:
    calendar = _calendar()
    start = calendar.sessions[0].open_at
    end = calendar.sessions[-1].close_at + timedelta(minutes=1)
    bar_query = MarketDataQuery(
        market_id="XNYS",
        assets=FROZEN_ASSETS,
        start=start,
        end=end,
        interval=interval,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    bars, _ = build_resampled_minute_plan(
        source_plan,
        sessionization,
        bar_query,
        ResamplingSpec(calendar_id=FROZEN_CALENDAR_ID, target_interval=interval),
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
    labels, _ = build_same_session_label_plan(
        source_plan,
        sessionization,
        label_query,
        LabelMaterializationSpec(
            label_spec=canonical_us_r1_label_spec(horizon),
            calendar_id=FROZEN_CALENDAR_ID,
        ),
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
            b.session_id,
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
            b.is_half_day,
            l.source_available_at,
            CAST(l.source_price AS DOUBLE) AS source_price,
            l.target_available_at,
            CAST(l.label_value AS DOUBLE) AS label_value,
            l.label_available,
            l.unavailable_reason,
            l.source_available_at IS NOT NULL AS label_row_present,
            CASE WHEN l.source_price IS NULL THEN NULL
                 ELSE abs(CAST(b.close AS DOUBLE) - CAST(l.source_price AS DOUBLE)) END
                AS close_anchor_difference
        FROM bars AS b
        LEFT JOIN labels AS l
          ON l.research_asset_id = b.research_asset_id
         AND l.session_date = b.session_date
         AND l.source_available_at = b.available_at
        WHERE EXTRACT(year FROM b.session_date) = 2006
        ORDER BY b.available_at, b.research_asset_id
    """
    return _execute(sql)


def _float_hex(value: object) -> str | None:
    return None if value is None else float(value).hex()


def _materialization(plan_id: str, data_version: str, row_count: int, content: bytes) -> MinuteMaterialization:
    return MinuteMaterialization(
        plan_id=plan_id,
        data_version=data_version,
        row_count=row_count,
        size_bytes=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
        output_filename=ROBUSTNESS_BASE_FILENAME,
    )


def test_robustness_policy_is_exact_r1_frequency_and_decay_set() -> None:
    r1 = canonical_us_r1_research_protocol()
    slices = canonical_us_r2_robustness_slices()
    assert tuple(item.signal_interval for item in slices if item.kind == "frequency") == (
        BarInterval.MINUTE_5,
        BarInterval.MINUTE_30,
    ) == r1.robustness_intervals
    assert tuple(
        item.label_horizon_trading_minutes for item in slices if item.kind == "decay"
    ) == r1.decay_horizons_trading_minutes

    policy = canonical_us_r2_robustness_materialization_policy()
    payload = policy.to_dict()
    assert payload["pooled_inference_report_id"] == FROZEN_POOLED_INFERENCE_REPORT_ID
    assert payload["raw_1m_required"] is True
    assert payload["derive_from_primary_15m60m_cache"] is False
    assert payload["candidate_performance_read"] is False
    assert payload["alpha_gate_evaluated"] is False


def test_robustness_base_uses_one_shared_raw_relation_and_no_candidate_path() -> None:
    source, sessionization = _source_plan()
    plan = build_us_r2_annual_robustness_base_plan(source, sessionization, year=2006)
    assert plan.sql.count("WITH source_rows AS MATERIALIZED") == 1
    assert plan.sql.count(source.sql) == 1
    assert plan.sql.count("year_rows AS MATERIALIZED") == 1
    assert plan.to_dict()["source_scan_relation_count"] == 1
    assert plan.to_dict()["candidate_dependent_scan"] is False
    assert plan.to_dict()["candidate_performance_read"] is False
    assert plan.to_dict()["candidate_selection_applied"] is False


def test_all_four_robustness_slices_match_existing_r1_bar_and_label_semantics() -> None:
    source, sessionization = _source_plan()
    plan = build_us_r2_annual_robustness_base_plan(source, sessionization, year=2006)
    observed_all = _execute(plan.sql)
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
        "research_asset_id",
        "session_date",
        "session_id",
        "event_time",
        "available_at",
        "bar_index",
        "observed_minute_count",
        "expected_minute_count",
        "is_complete",
        "is_half_day",
        "source_available_at",
        "target_available_at",
        "label_available",
        "unavailable_reason",
        "label_row_present",
    )
    for slice_spec in canonical_us_r2_robustness_slices():
        observed = tuple(row for row in observed_all if row["slice_id"] == slice_spec.slice_id)
        reference = _reference_slice_rows(
            source,
            sessionization,
            interval=slice_spec.signal_interval,
            horizon=slice_spec.label_horizon_trading_minutes,
        )
        assert len(observed) == len(reference), slice_spec.slice_id
        for left, right in zip(observed, reference, strict=True):
            for field in exact:
                assert left[field] == right[field], (slice_spec.slice_id, field)
            for field in numeric:
                assert _float_hex(left[field]) == _float_hex(right[field]), (
                    slice_spec.slice_id,
                    field,
                )


def test_robustness_summary_and_evidence_preserve_each_slice_breadth() -> None:
    source, sessionization = _source_plan()
    plan = build_us_r2_annual_robustness_base_plan(source, sessionization, year=2006)
    rows = _execute(plan.sql)
    summary = _execute(build_us_r2_robustness_summary_plan(plan, relation_sql=plan.sql).sql)
    evidence = build_us_r2_annual_robustness_base_evidence(
        plan,
        _materialization(plan.plan_id, plan.data_version, len(rows), b"synthetic-parquet"),
        summary,
    )
    assert evidence.passed is True
    assert evidence.blockers == ()
    assert len(evidence.slices) == 4
    assert all(item.asset_count == len(FROZEN_ASSETS) for item in evidence.slices)
    assert all(item.maximum_joint_breadth >= 10 for item in evidence.slices)
    assert all(item.formation_count_at_minimum_cross_section > 0 for item in evidence.slices)

    broken = [dict(row) for row in summary]
    broken[0]["formation_count_at_minimum_cross_section"] = 0
    blocked = build_us_r2_annual_robustness_base_evidence(
        plan,
        _materialization(plan.plan_id, plan.data_version, len(rows), b"synthetic-parquet"),
        tuple(broken),
    )
    assert blocked.passed is False
    assert any("slice_never_reaches_minimum_cross_section" in item for item in blocked.blockers)


def _write_triplet(tmp_path: Path, *, tamper_data: bool = False) -> tuple[Path, Path]:
    source, sessionization = _source_plan()
    plan = build_us_r2_annual_robustness_base_plan(source, sessionization, year=2006)
    rows = _execute(plan.sql)
    summary = _execute(build_us_r2_robustness_summary_plan(plan, relation_sql=plan.sql).sql)
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports"
    paths = us_r2_annual_robustness_paths(
        year=2006,
        data_root=data_root,
        report_root=report_root,
    )
    paths.data_path.parent.mkdir(parents=True, exist_ok=True)
    paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    content = b"immutable-parquet-placeholder"
    paths.data_path.write_bytes(content)
    materialization = _materialization(plan.plan_id, plan.data_version, len(rows), content)
    evidence = build_us_r2_annual_robustness_base_evidence(
        plan,
        materialization,
        summary,
    )
    paths.plan_path.write_text(json.dumps(plan.to_dict(), sort_keys=True), encoding="utf-8")
    paths.evidence_path.write_text(json.dumps(evidence.to_dict(), sort_keys=True), encoding="utf-8")
    if tamper_data:
        paths.data_path.write_bytes(content + b"tampered")
    return data_root, report_root


def test_resumable_inspector_binds_parquet_content_and_skips_valid_year(tmp_path: Path) -> None:
    data_root, report_root = _write_triplet(tmp_path)
    paths = us_r2_annual_robustness_paths(
        year=2006,
        data_root=data_root,
        report_root=report_root,
    )
    completed = inspect_completed_us_r2_annual_robustness_base(paths)
    assert completed is not None
    assert completed.year == 2006
    calls: list[int] = []
    _evidence, preexisting, materialized = materialize_us_r2_robustness_batch(
        years=(2006,),
        data_root=data_root,
        report_root=report_root,
        materialize_year=calls.append,
    )
    assert calls == []
    assert preexisting == (2006,)
    assert materialized == ()


def test_resumable_inspector_fails_closed_on_partial_or_tampered_triplet(tmp_path: Path) -> None:
    data_root = tmp_path / "partial-data"
    report_root = tmp_path / "partial-reports"
    paths = us_r2_annual_robustness_paths(
        year=2006,
        data_root=data_root,
        report_root=report_root,
    )
    paths.data_path.parent.mkdir(parents=True, exist_ok=True)
    paths.data_path.write_bytes(b"partial")
    with pytest.raises(ValueError, match="triplet is partial"):
        inspect_completed_us_r2_annual_robustness_base(paths)

    tamper_root = tmp_path / "tampered"
    tampered_data, tampered_reports = _write_triplet(tamper_root, tamper_data=True)
    with pytest.raises(ValueError, match="Parquet identity mismatch"):
        inspect_completed_us_r2_annual_robustness_base(
            us_r2_annual_robustness_paths(
                year=2006,
                data_root=tampered_data,
                report_root=tampered_reports,
            )
        )


def test_operator_has_no_candidate_or_primary_cache_fallback() -> None:
    source = Path("scripts/materialize_us_r2_robustness_base_year.py").read_text(encoding="utf-8")
    assert "candidate-cache" not in source
    assert "primary-data-root" not in source
    assert "pooled_inference_report.json" not in source
    assert '"candidate_performance_read": False' in source
    assert '"candidate_selection_applied": False' in source
    assert '"alpha_gate_evaluated": False' in source
