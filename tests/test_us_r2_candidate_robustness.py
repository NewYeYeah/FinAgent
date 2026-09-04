from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from finagent.domain.market_bars import BarInterval
from finagent.research.us_a1_factor_materialization import (
    compile_factor_graph_batch,
    materialize_compiled_factor_batch,
)
from finagent.research.us_a1_legacy_graphs import (
    legacy_a0_candidate_factor_graph,
    legacy_a0_factor_graph_with_window,
)
from finagent.research.us_agent_value_protocol import canonical_us_a0_primitive_vocabulary
from finagent.research.us_baselines import (
    USBaselineBar,
    USBaselineFeatureKind,
    USBaselineProtocol,
    evaluate_us_baseline_feature,
)
from finagent.research.us_r1_materialization import (
    compile_us_r1_feature_spec,
    effective_us_r1_window_bars,
)
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r2_candidate_robustness import (
    FROZEN_PRIMARY_STATISTICS_REPORT_ID,
    USR2AnnualRobustnessMetricArrays,
    USR2CandidateRobustnessPlan,
    USR2RobustnessBaseRow,
    _is_partial_label_formation,
    build_us_r2_candidate_robustness_report,
    load_us_r2_robustness_metric_npz,
    validate_us_r2_robustness_base_batch_gate,
    write_deterministic_us_r2_robustness_metric_npz,
)
from finagent.research.us_r2_evaluation_policy import (
    canonical_us_r2_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import FROZEN_REGIME_LABELS
from finagent.research.us_r2_primary_statistics import (
    METRIC_AVAILABLE,
    USR2AnnualPrimaryMetricArrays,
    USR2CandidateDirectionEvidence,
    USR2PrimaryDirectionEvidenceSet,
)
from finagent.research.us_r2_robustness_base import (
    canonical_us_r2_robustness_materialization_policy,
    canonical_us_r2_robustness_slices,
)
from finagent.research.us_r2_robustness_batch import (
    USR2RobustnessBaseBatchEvidence,
    canonical_us_r2_robustness_years,
)


def _bars(interval: BarInterval) -> tuple[USBaselineBar, ...]:
    minutes = {
        BarInterval.MINUTE_5: 5,
        BarInterval.MINUTE_15: 15,
        BarInterval.MINUTE_30: 30,
    }[interval]
    count = 390 // minutes
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    rows: list[USBaselineBar] = []
    for index in range(count):
        event_time = start + timedelta(minutes=minutes * index)
        base = 100.0 + index * 0.07
        close = base + ((index % 7) - 3) * 0.013
        open_value = base - 0.02
        rows.append(
            USBaselineBar(
                event_time=event_time,
                available_at=event_time + timedelta(minutes=minutes),
                session_id="2025-01-02",
                open=open_value,
                high=max(open_value, close) + 0.11,
                low=min(open_value, close) - 0.09,
                close=close,
                volume=1_000.0 + index * 3.0,
                is_complete=True,
            )
        )
    return tuple(rows)


def _representative_candidates():
    by_kind = {}
    for candidate in canonical_us_a0_primitive_vocabulary().all_candidates():
        by_kind.setdefault(candidate.kind, candidate)
    assert set(by_kind) == set(USBaselineFeatureKind)
    return tuple(by_kind[kind] for kind in USBaselineFeatureKind)


def test_explicit_window_helper_preserves_every_legacy_default_graph() -> None:
    for candidate in canonical_us_a0_primitive_vocabulary().all_candidates():
        legacy = legacy_a0_candidate_factor_graph(candidate).graph
        explicit = legacy_a0_factor_graph_with_window(
            candidate,
            window_bars=candidate.window_bars,
        )
        assert explicit == legacy


@pytest.mark.parametrize(
    "interval",
    [BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30],
)
def test_elapsed_window_scaled_graph_is_bitwise_equal_to_r1_feature_evaluator(
    interval: BarInterval,
) -> None:
    bars = _bars(interval)
    protocol = USBaselineProtocol()
    for candidate in _representative_candidates():
        window = effective_us_r1_window_bars(candidate, interval)
        spec = compile_us_r1_feature_spec(candidate, interval)
        assert spec.window_bars == window
        graph = legacy_a0_factor_graph_with_window(candidate, window_bars=window)
        materialized = materialize_compiled_factor_batch(
            compile_factor_graph_batch((graph,)),
            bars,
            maximum_bars_per_batch=100_000,
        )
        actual = materialized.candidates[0].values
        for index in range(len(bars)):
            expected = evaluate_us_baseline_feature(
                spec,
                bars[: index + 1],
                protocol=protocol,
            )
            if expected.value is None:
                assert actual[index] is None
            else:
                assert actual[index] is not None
                assert float(actual[index]).hex() == expected.value.hex()


def test_elapsed_window_formula_is_exact_r1_freeze() -> None:
    candidate = next(
        item
        for item in canonical_us_a0_primitive_vocabulary().all_candidates()
        if item.window_bars > 1
    )
    base = candidate.window_bars
    assert effective_us_r1_window_bars(candidate, BarInterval.MINUTE_5) == 1 + (base - 1) * 3
    assert effective_us_r1_window_bars(candidate, BarInterval.MINUTE_15) == base
    assert effective_us_r1_window_bars(candidate, BarInterval.MINUTE_30) == 1 + int(
        np.ceil((base - 1) / 2.0)
    )


def test_robustness_base_batch_gate_is_dynamic_content_addressed_and_fail_closed() -> None:
    years = canonical_us_r2_robustness_years()
    evidence = USR2RobustnessBaseBatchEvidence(
        policy_id=canonical_us_r2_robustness_materialization_policy().policy_id,
        requested_years=years,
        annual_evidence_ids=tuple(f"evidence-{year}" for year in years),
        annual_materialization_ids=tuple(f"materialization-{year}" for year in years),
        total_row_count=123_456,
    )
    parsed = validate_us_r2_robustness_base_batch_gate(evidence.to_dict())
    assert parsed.evidence_id == evidence.evidence_id

    changed = evidence.to_dict()
    changed["total_row_count"] = 123_457
    with pytest.raises(ValueError, match="content-addressed"):
        validate_us_r2_robustness_base_batch_gate(changed)


def _row(*, present: bool, reason: str | None, label_available: bool | None) -> USR2RobustnessBaseRow:
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    return USR2RobustnessBaseRow(
        slice_id="frequency_5m_60m",
        research_asset_id="AAPL",
        session_date=date(2025, 1, 2),
        session_id="2025-01-02",
        event_time=start,
        available_at=start + timedelta(minutes=5),
        bar_index=0,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0,
        is_complete=True,
        label_value=0.01 if label_available else None,
        label_available=label_available,
        unavailable_reason=reason,
        label_row_present=present,
    )


def test_r2_partial_label_policy_omits_anchor_or_target_missing_but_not_boundary() -> None:
    assert _is_partial_label_formation(
        (_row(present=False, reason=None, label_available=None),)
    )
    assert _is_partial_label_formation(
        (_row(present=True, reason="target_minute_missing", label_available=False),)
    )
    assert not _is_partial_label_formation(
        (_row(present=True, reason="target_crosses_session", label_available=False),)
    )


def _direction(candidate_ids: tuple[str, ...]) -> USR2PrimaryDirectionEvidenceSet:
    policy = canonical_us_r2_statistical_evaluation_policy()
    candidates = tuple(
        USR2CandidateDirectionEvidence(
            candidate_id=candidate_id,
            period_count=100,
            boundary_unrealized_period_count=0,
            partial_label_omitted_period_count=0,
            insufficient_cross_section_period_count=0,
            mean_raw_rank_ic=0.01,
            direction=1,
            blockers=(),
        )
        for candidate_id in candidate_ids
    )
    return USR2PrimaryDirectionEvidenceSet(
        plan_id="synthetic-primary-plan",
        evaluation_policy_id=policy.policy_id,
        candidate_cache_batch_evidence_id="synthetic-primary-batch",
        source_fold_id="us-r2-fold-01",
        source_years=(2001, 2002, 2003, 2004, 2005),
        source_annual_evidence_ids=tuple(f"source-{year}" for year in range(2001, 2006)),
        candidates=candidates,
    )


def _robustness_arrays(year_index: int) -> USR2AnnualRobustnessMetricArrays:
    rows = len(FROZEN_REGIME_LABELS) * len(canonical_us_r2_robustness_slices())
    rank = np.full((rows, 37), 0.02, dtype=np.float64)
    session_days = np.empty(rows, dtype=np.int32)
    formation = np.empty(rows, dtype=np.int64)
    regimes = np.empty(rows, dtype=np.uint8)
    slices = np.empty(rows, dtype=np.uint8)
    cursor = 0
    for regime_code in range(len(FROZEN_REGIME_LABELS)):
        for slice_code, spec in enumerate(canonical_us_r2_robustness_slices()):
            session_days[cursor] = 15_000 + year_index * 20 + regime_code
            formation[cursor] = year_index * 1_000_000 + cursor
            regimes[cursor] = regime_code
            slices[cursor] = slice_code
            if spec.slice_id in {"frequency_5m_60m", "frequency_30m_60m"}:
                rank[cursor, 1] = -0.02
            cursor += 1
    return USR2AnnualRobustnessMetricArrays(
        session_date_days=session_days,
        formation_at_us=formation,
        regime_codes=regimes,
        slice_codes=slices,
        rank_ic=rank,
        status_codes=np.full((rows, 37), METRIC_AVAILABLE, dtype=np.uint8),
    )


def _primary_arrays(year_index: int) -> USR2AnnualPrimaryMetricArrays:
    rows = len(FROZEN_REGIME_LABELS)
    rank = np.full((rows, 37), 0.03, dtype=np.float64)
    shape = (rows, 37)
    return USR2AnnualPrimaryMetricArrays(
        session_date_days=np.asarray(
            [15_000 + year_index * 20 + index for index in range(rows)], dtype=np.int32
        ),
        formation_at_us=np.asarray(
            [year_index * 1_000_000 + 100 + index for index in range(rows)], dtype=np.int64
        ),
        regime_codes=np.arange(rows, dtype=np.uint8),
        rank_ic=rank,
        long_short_return_bps=np.ones(shape, dtype=np.float64),
        one_way_turnover=np.zeros(shape, dtype=np.float64),
        coverage=np.ones(shape, dtype=np.float64),
        quantile_monotonicity=np.ones(shape, dtype=np.float64),
        status_codes=np.full(shape, METRIC_AVAILABLE, dtype=np.uint8),
    )


def test_sign_consistency_is_strict_two_of_three_and_not_candidate_selection() -> None:
    candidate_ids = tuple(f"candidate-{index:02d}" for index in range(37))
    direction = _direction(candidate_ids)
    policy = canonical_us_r2_statistical_evaluation_policy()
    plan = USR2CandidateRobustnessPlan(
        frozen_protocol_id="synthetic-freeze",
        evaluation_policy_id=policy.policy_id,
        denominator_id="synthetic-denominator",
        robustness_policy_id="synthetic-robustness-policy",
        robustness_base_batch_evidence_id="synthetic-base-batch",
        regime_projection_evidence_id="synthetic-regime",
        primary_statistics_plan_id="synthetic-primary-plan",
        primary_direction_evidence_id=direction.evidence_id,
        primary_statistics_report_id=FROZEN_PRIMARY_STATISTICS_REPORT_ID,
        pooled_inference_report_id="synthetic-pooled",
        candidate_ids=candidate_ids,
        interval_executions=(),
    )
    robustness = tuple(_robustness_arrays(index) for index in range(21))
    primary = tuple(_primary_arrays(index) for index in range(21))
    report = build_us_r2_candidate_robustness_report(
        robustness,
        primary,
        plan=plan,
        direction_evidence=direction,
        annual_robustness_metric_evidence_ids=tuple(f"robust-{index}" for index in range(21)),
        annual_primary_metric_evidence_ids=tuple(f"primary-{index}" for index in range(21)),
        policy=policy,
    )

    assert report.passed is True
    assert len(report.candidates) == 37
    assert report.candidates[0].robustness_passed is True
    assert report.candidates[1].all_regimes_frequency_passed is False
    assert report.candidates[1].robustness_passed is False
    assert report.to_dict()["candidate_selection_applied"] is False
    assert report.to_dict()["alpha_gate_evaluated"] is False
    for cell in report.candidates[0].regime_cells:
        assert cell.frequency_sign_consistency == pytest.approx(1.0)
        assert cell.decay_sign_consistency == pytest.approx(1.0)
    for cell in report.candidates[1].regime_cells:
        assert cell.frequency_sign_consistency == pytest.approx(1.0 / 3.0)
        assert cell.frequency_passed is False


def test_deterministic_robustness_metric_npz_is_byte_stable(tmp_path: Path) -> None:
    arrays = _robustness_arrays(0)
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    first_hash, first_size = write_deterministic_us_r2_robustness_metric_npz(first, arrays)
    second_hash, second_size = write_deterministic_us_r2_robustness_metric_npz(second, arrays)
    assert first_hash == second_hash
    assert first_size == second_size
    assert first.read_bytes() == second.read_bytes()
    loaded = load_us_r2_robustness_metric_npz(first)
    for name, expected in arrays.as_npz_arrays().items():
        actual = loaded.as_npz_arrays()[name]
        if np.issubdtype(expected.dtype, np.floating):
            assert np.array_equal(actual, expected, equal_nan=True)
        else:
            assert np.array_equal(actual, expected)


def test_plan_serialization_declares_three_feature_intervals_and_no_authority() -> None:
    candidate_ids = tuple(f"candidate-{index:02d}" for index in range(37))
    direction = _direction(candidate_ids)
    plan = USR2CandidateRobustnessPlan(
        frozen_protocol_id="synthetic-freeze",
        evaluation_policy_id=canonical_us_r2_statistical_evaluation_policy().policy_id,
        denominator_id="synthetic-denominator",
        robustness_policy_id="synthetic-policy",
        robustness_base_batch_evidence_id="synthetic-batch",
        regime_projection_evidence_id="synthetic-regime",
        primary_statistics_plan_id="synthetic-primary-plan",
        primary_direction_evidence_id=direction.evidence_id,
        primary_statistics_report_id=FROZEN_PRIMARY_STATISTICS_REPORT_ID,
        pooled_inference_report_id="synthetic-pooled",
        candidate_ids=candidate_ids,
        interval_executions=(),
    )
    document = plan.to_dict()
    assert document["feature_interval_evaluation_count_per_year"] == 3
    assert document["robustness_slice_count"] == 4
    assert document["primary_15m_60m_feature_recomputation"] is False
    assert document["candidate_selection_applied"] is False
    assert document["alpha_gate_evaluated"] is False
    assert document["stage_exit_authority"] is False
    assert canonical_us_r1_research_protocol().same_session_only is True
