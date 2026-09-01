from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from finagent.data.minute_store import MinuteQueryPlan
from finagent.data.minute_transform import (
    LabelQueryPlan,
    LabelSeriesEvidence,
    ResamplingEvidence,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.research.us_baseline_materialization import (
    bind_us_b0_run_spec,
    build_us_baseline_input_plan,
    materialize_us_baseline_observations,
    write_us_baseline_observation_artifact,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator


def _accepted_documents() -> tuple[dict[str, object], dict[str, object], tuple[str, ...]]:
    assets = tuple(f"T{index:02d}" for index in range(20))
    universe_id = "engineering-universe-test"
    mappings = [
        {
            "status": "accepted_for_engineering",
            "research": {"source_symbol": asset},
        }
        for asset in assets
    ]
    universe: dict[str, object] = {
        "schema_version": "finagent.us-engineering-universe-finalization-report.v2",
        "accepted": True,
        "blockers": [],
        "universe_id": universe_id,
        "accepted_mapping_count": len(assets),
        "selected_symbols": list(assets),
        "quote_evidence": {"passed": True},
        "materialization": {"mappings": mappings},
    }
    certification: dict[str, object] = {
        "schema_version": "finagent.us-minute-certification-report.v1",
        "report_id": "us-minute-research-cert-test",
        "certified": True,
        "outcome": "CERTIFIED_FOR_ENGINEERING_RESEARCH",
        "blockers": [],
        "inputs": {
            "engineering_universe_id": universe_id,
            "engineering_universe_accepted": True,
            "engineering_universe_count": len(assets),
            "reconciliation_passed": True,
        },
    }
    return certification, universe, assets


def _queries() -> tuple[MarketDataQuery, MarketDataQuery]:
    assets = ("AAA", "BBB")
    start = datetime(2026, 3, 9, 13, 45, tzinfo=UTC)
    end = datetime(2026, 3, 9, 19, 45, tzinfo=UTC)
    bars = MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,
        end=end,
        interval=BarInterval.MINUTE_15,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    labels = MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,
        end=end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    return bars, labels


def _plans() -> tuple[
    MinuteQueryPlan,
    LabelQueryPlan,
    ResamplingEvidence,
    LabelSeriesEvidence,
]:
    bar_query, label_query = _queries()
    bar_plan = MinuteQueryPlan(
        query=bar_query,
        manifest_id="manifest",
        data_version="resampled-version",
        sql="SELECT * FROM bars",
        partition_months=("2026-03",),
        selected_size_bytes=100,
        output_columns=(
            "research_asset_id",
            "session_date",
            "session_id",
            "event_time",
            "available_at",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "bar_index",
            "observed_minute_count",
            "expected_minute_count",
            "coverage_ratio",
            "is_complete",
        ),
    )
    label_plan = LabelQueryPlan(
        source_query=label_query,
        materialization_spec_id="label-materialization-spec",
        label_spec_id="label-spec",
        source_plan_id="label-source-plan",
        source_data_version="raw-version",
        data_version="label-version",
        sql="SELECT * FROM labels",
        partition_months=("2026-03",),
        selected_size_bytes=90,
        output_columns=(
            "research_asset_id",
            "session_date",
            "source_event_time",
            "source_available_at",
            "source_price",
            "target_event_time",
            "target_available_at",
            "label_value",
            "label_available",
            "unavailable_reason",
        ),
    )
    resampling = ResamplingEvidence(
        spec_id="resample-spec",
        calendar_id="calendar",
        sessionization_evidence_id="sessionization",
        source_plan_id="raw-plan",
        resampled_plan_id=bar_plan.plan_id,
        source_data_version="raw-version",
        resampled_data_version=bar_plan.data_version,
    )
    labels = LabelSeriesEvidence(
        materialization_spec_id="label-materialization-spec",
        label_spec_id="label-spec",
        calendar_id="calendar",
        sessionization_evidence_id="sessionization",
        source_plan_id="label-source-plan",
        label_plan_id=label_plan.plan_id,
        source_data_version="raw-version",
        label_data_version=label_plan.data_version,
    )
    return bar_plan, label_plan, resampling, labels


def _joined_rows(
    assets: tuple[str, ...] = ("AAA", "BBB"),
    *,
    periods: int = 10,
    mismatch: tuple[str, int] | None = None,
    incomplete: tuple[str, int] | None = None,
) -> tuple[dict[str, object], ...]:
    start = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for index in range(periods):
        event_time = start + timedelta(minutes=15 * index)
        available_at = event_time + timedelta(minutes=15)
        for asset_index, asset in enumerate(assets):
            close = 100.0 + asset_index * 10.0 + index
            source_price = close
            if mismatch == (asset, index):
                source_price += 0.01
            rows.append(
                {
                    "research_asset_id": asset,
                    "session_date": "2026-03-09",
                    "session_id": "XNYS:2026-03-09",
                    "event_time": event_time,
                    "available_at": available_at,
                    "open": close - 0.25,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 1000.0 + index * 10.0,
                    "bar_index": index,
                    "observed_minute_count": 15,
                    "expected_minute_count": 15,
                    "coverage_ratio": 1.0,
                    "is_complete": incomplete != (asset, index),
                    "source_event_time": available_at - timedelta(minutes=1),
                    "source_available_at": available_at,
                    "source_price": source_price,
                    "target_event_time": available_at + timedelta(minutes=59),
                    "target_available_at": available_at + timedelta(minutes=60),
                    "label_value": 0.001 * (asset_index + 1),
                    "label_available": True,
                    "unavailable_reason": None,
                    "label_row_present": True,
                    "close_anchor_difference": abs(close - source_price),
                }
            )
    return tuple(rows)


def test_run_spec_binds_exact_certification_and_final_universe() -> None:
    certification, universe, assets = _accepted_documents()
    denominator = canonical_us_baseline_denominator()

    run_spec, selected = bind_us_b0_run_spec(
        certification,
        universe,
        denominator=denominator,
    )

    assert selected == assets
    assert run_spec.certification_report_id == certification["report_id"]
    assert run_spec.engineering_universe_id == universe["universe_id"]
    assert run_spec.denominator_id == denominator.denominator_id

    bad = dict(certification)
    bad["blockers"] = ["still-blocked"]
    with pytest.raises(ValueError, match="blocker-free"):
        bind_us_b0_run_spec(bad, universe, denominator=denominator)


def test_run_spec_rejects_universe_identity_drift() -> None:
    certification, universe, _assets = _accepted_documents()
    denominator = canonical_us_baseline_denominator()
    drifted = dict(universe)
    drifted["universe_id"] = "engineering-universe-drifted"

    with pytest.raises(ValueError, match="identity mismatch"):
        bind_us_b0_run_spec(certification, drifted, denominator=denominator)


def test_input_plan_joins_on_formation_availability_not_bar_event_time() -> None:
    certification, universe, _assets = _accepted_documents()
    denominator = canonical_us_baseline_denominator()
    run_spec, _ = bind_us_b0_run_spec(
        certification,
        universe,
        denominator=denominator,
    )
    bar_plan, label_plan, resampling, labels = _plans()

    plan = build_us_baseline_input_plan(
        bar_plan,
        label_plan,
        resampling,
        labels,
        run_spec=run_spec,
    )

    assert "l.source_available_at = b.available_at" in plan.sql
    assert "l.source_event_time = b.event_time" not in plan.sql
    assert "close_anchor_difference" in plan.output_columns
    assert plan.run_spec_id == run_spec.spec_id


def test_materializer_retains_full_denominator_and_explicit_warmup_missingness() -> None:
    denominator = canonical_us_baseline_denominator()
    rows = _joined_rows()

    observations, diagnostics = materialize_us_baseline_observations(
        rows,
        denominator,
        expected_assets=("AAA", "BBB"),
    )

    assert diagnostics.passed
    assert diagnostics.expected_asset_count == 2
    assert diagnostics.observed_asset_count == 2
    assert diagnostics.complete_bar_count == 20
    assert len(observations) == 8
    assert all(len(feature_rows) == 20 for feature_rows in observations.values())
    checks = {item.feature_id: item for item in diagnostics.candidate_checks}
    volume = checks["manual_volume_surprise_8bar"]
    assert volume.available_feature_count == 4
    assert dict(volume.unavailable_reason_counts)["insufficient_history"] == 16


def test_incomplete_bar_remains_in_history_and_propagates_explicit_feature_unavailability() -> None:
    denominator = canonical_us_baseline_denominator()
    rows = _joined_rows(incomplete=("AAA", 4))

    observations, diagnostics = materialize_us_baseline_observations(
        rows,
        denominator,
        expected_assets=("AAA", "BBB"),
    )

    assert diagnostics.incomplete_bar_count == 1
    assert diagnostics.passed
    assert len(observations["manual_momentum_8bar"]) == 19
    momentum_check = next(
        item
        for item in diagnostics.candidate_checks
        if item.feature_id == "manual_momentum_8bar"
    )
    assert dict(momentum_check.unavailable_reason_counts)["incomplete_bar"] >= 1


def test_missing_engineering_asset_and_close_anchor_drift_fail_closed() -> None:
    denominator = canonical_us_baseline_denominator()
    rows = _joined_rows(assets=("AAA",), mismatch=("AAA", 3))

    _observations, diagnostics = materialize_us_baseline_observations(
        rows,
        denominator,
        expected_assets=("AAA", "BBB"),
    )

    assert not diagnostics.passed
    assert diagnostics.missing_assets == ("BBB",)
    assert diagnostics.close_anchor_mismatch_count == 1
    assert any("engineering_assets_missing:BBB" in item for item in diagnostics.blockers)
    assert any("close_anchor_mismatch_count:1" in item for item in diagnostics.blockers)


def test_observation_artifact_is_content_addressed_independent_of_filename(
    tmp_path: Path,
) -> None:
    certification, universe, _assets = _accepted_documents()
    denominator = canonical_us_baseline_denominator()
    run_spec, _ = bind_us_b0_run_spec(
        certification,
        universe,
        denominator=denominator,
        minimum_cross_section=2,
        minimum_evaluated_periods=1,
        minimum_ic_periods=1,
    )
    observations, diagnostics = materialize_us_baseline_observations(
        _joined_rows(),
        denominator,
        expected_assets=("AAA", "BBB"),
    )
    assert diagnostics.passed

    first = write_us_baseline_observation_artifact(
        observations,
        tmp_path / "first.jsonl",
        run_spec=run_spec,
    )
    second = write_us_baseline_observation_artifact(
        observations,
        tmp_path / "second.jsonl",
        run_spec=run_spec,
    )

    assert first.content_sha256 == second.content_sha256
    assert first.artifact_id == second.artifact_id
    assert first.row_count == second.row_count
