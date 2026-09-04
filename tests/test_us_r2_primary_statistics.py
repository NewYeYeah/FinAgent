from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_evaluation_policy import canonical_us_r1_statistical_evaluation_policy
from finagent.research.us_r1_gate import canonical_us_r1_alpha_gate_policy
from finagent.research.us_r1_materialization import USR1CandidateObservation, USR1ObservationRole
from finagent.research.us_r1_statistics import evaluate_us_r1_candidate_slice
from finagent.research.us_r2_candidate_cache import USR2AnnualCandidateCacheArrays
from finagent.research.us_r2_evaluation_policy import canonical_us_r2_statistical_evaluation_policy
from finagent.research.us_r2_frozen_protocol import FROZEN_ASSETS, FROZEN_REGIME_LABELS
from finagent.research.us_r2_primary_direction import (
    build_us_r2_primary_direction_evidence_exact,
)
from finagent.research.us_r2_primary_statistics import (
    METRIC_AVAILABLE,
    METRIC_BOUNDARY_UNREALIZED,
    METRIC_INSUFFICIENT_CROSS_SECTION,
    METRIC_PARTIAL_LABEL_OMITTED,
    USR2AnnualPrimaryMetricArrays,
    USR2CandidateDirectionEvidence,
    USR2PrimaryDirectionEvidenceSet,
    USR2PrimaryStatisticsPlan,
    USR2RegimeSession,
    USR2RegimeSessionMap,
    build_us_r2_primary_statistics_report,
    evaluate_us_r2_annual_primary_metrics,
    load_us_r2_primary_metric_npz,
    write_deterministic_us_r2_primary_metric_npz,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_DATE_EPOCH = date(1970, 1, 1)


def _us(value: datetime) -> int:
    delta = value - _EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _days(value: date) -> int:
    return (value - _DATE_EPOCH).days


def _plan(candidate_ids: tuple[str, ...]) -> USR2PrimaryStatisticsPlan:
    policy = canonical_us_r2_statistical_evaluation_policy()
    return USR2PrimaryStatisticsPlan(
        frozen_protocol_id=policy.frozen_protocol_id,
        evaluation_policy_id=policy.policy_id,
        candidate_cache_batch_evidence_id="synthetic-cache-batch",
        candidate_cache_plan_id="synthetic-cache-plan",
        compiled_candidate_batch_id="synthetic-compiled-batch",
        regime_projection_evidence_id="synthetic-regime",
        denominator_id="synthetic-denominator",
        candidate_ids=candidate_ids,
    )


def _candidate_arrays_and_r1_observations(
    *,
    session_dates: tuple[date, ...],
    formations_per_session: int,
    candidate_ids: tuple[str, ...] = ("candidate-a", "candidate-b"),
    include_diagnostics: bool = True,
    role: USR1ObservationRole = USR1ObservationRole.EVALUATION,
) -> tuple[USR2AnnualCandidateCacheArrays, tuple[USR1CandidateObservation, ...]]:
    asset_count = 12
    asset_codes: list[int] = []
    session_days: list[int] = []
    event_us: list[int] = []
    available_us: list[int] = []
    label_values: list[float] = []
    label_available: list[bool] = []
    label_available_at: list[int] = []
    label_reasons: list[int] = []
    candidate_values: list[list[float]] = []
    candidate_reasons: list[list[int]] = []
    observations: list[USR1CandidateObservation] = []

    formation_number = 0
    for session_date in session_dates:
        session_start = datetime(
            session_date.year,
            session_date.month,
            session_date.day,
            14,
            30,
            tzinfo=UTC,
        )
        for formation_index in range(formations_per_session):
            formation_at = session_start + timedelta(minutes=15 * (formation_index + 1))
            boundary = include_diagnostics and formation_number == 2
            partial = include_diagnostics and formation_number == 3
            insufficient_b = include_diagnostics and formation_number == 4
            for asset_code in range(asset_count):
                asset = FROZEN_ASSETS[asset_code]
                label = 0.001 * (asset_code + 1) + 0.00001 * formation_number
                if boundary:
                    label_is_available = False
                    label_reason_code = 1
                    label_reason = "target_crosses_session"
                elif partial and asset_code == 0:
                    label_is_available = False
                    label_reason_code = 2
                    label_reason = "target_minute_missing"
                else:
                    label_is_available = True
                    label_reason_code = 0
                    label_reason = None
                values = [
                    0.02 * asset_code + 0.001 * formation_number,
                    -0.015 * asset_code + 0.0007 * formation_number,
                ]
                reasons = [0, 0]
                if insufficient_b and asset_code < 3:
                    values[1] = float("nan")
                    reasons[1] = 1

                asset_codes.append(asset_code)
                session_days.append(_days(session_date))
                event_us.append(_us(formation_at - timedelta(minutes=15)))
                available_us.append(_us(formation_at))
                label_values.append(label if label_is_available else float("nan"))
                label_available.append(label_is_available)
                label_available_at.append(
                    _us(formation_at + timedelta(minutes=60)) if label_is_available else -1
                )
                label_reasons.append(label_reason_code)
                candidate_values.append(values)
                candidate_reasons.append(reasons)

                for slot, candidate_id in enumerate(candidate_ids):
                    feature_value = values[slot]
                    observations.append(
                        USR1CandidateObservation(
                            candidate_id=candidate_id,
                            feature_spec_id=f"spec-{candidate_id}",
                            role=role,
                            signal_interval=BarInterval.MINUTE_15,
                            label_horizon_trading_minutes=60,
                            asset=asset,
                            session_id=session_date.isoformat(),
                            event_time=formation_at - timedelta(minutes=15),
                            feature_available_at=formation_at,
                            feature_value=(None if np.isnan(feature_value) else feature_value),
                            feature_unavailable_reason=(
                                "insufficient_history" if np.isnan(feature_value) else None
                            ),
                            realized_label=(label if label_is_available else None),
                            label_available_at=(
                                formation_at + timedelta(minutes=60)
                                if label_is_available
                                else None
                            ),
                            label_unavailable_reason=label_reason,
                        )
                    )
            formation_number += 1

    return (
        USR2AnnualCandidateCacheArrays(
            asset_codes=np.asarray(asset_codes, dtype=np.uint8),
            session_date_days=np.asarray(session_days, dtype=np.int32),
            event_time_us=np.asarray(event_us, dtype=np.int64),
            available_at_us=np.asarray(available_us, dtype=np.int64),
            label_values=np.asarray(label_values, dtype=np.float64),
            label_available=np.asarray(label_available, dtype=np.bool_),
            label_available_at_us=np.asarray(label_available_at, dtype=np.int64),
            label_reason_codes=np.asarray(label_reasons, dtype=np.uint8),
            candidate_values=np.asarray(candidate_values, dtype=np.float64),
            candidate_reason_codes=np.asarray(candidate_reasons, dtype=np.uint8),
        ),
        tuple(observations),
    )


def test_r2_primary_period_metrics_are_bitwise_equal_to_r1_slice_semantics() -> None:
    candidate_ids = ("candidate-a", "candidate-b")
    sessions = (date(2006, 1, 3), date(2006, 1, 4))
    arrays, observations = _candidate_arrays_and_r1_observations(
        session_dates=sessions,
        formations_per_session=4,
        candidate_ids=candidate_ids,
    )
    regime = USR2RegimeSessionMap(
        evidence_id="synthetic-regime",
        sessions=tuple(
            USR2RegimeSession(
                fold_id="us-r2-fold-01",
                session_date_days=_days(session),
                regime_code=0,
                available=True,
                unavailable_reason=None,
            )
            for session in sessions
        ),
    )
    actual, fold_id, _source_count, unavailable_sessions = evaluate_us_r2_annual_primary_metrics(
        arrays,
        year=2006,
        plan=_plan(candidate_ids),
        regime_sessions=regime,
    )
    assert fold_id == "us-r2-fold-01"
    assert unavailable_sessions == 0
    policy = canonical_us_r1_statistical_evaluation_policy()

    for slot, candidate_id in enumerate(candidate_ids):
        expected_stats, expected_points = evaluate_us_r1_candidate_slice(
            observations,
            candidate_id=candidate_id,
            role=USR1ObservationRole.EVALUATION,
            signal_interval=BarInterval.MINUTE_15,
            label_horizon_trading_minutes=60,
            policy=policy,
            minimum_periods=1,
        )
        available_rows = np.flatnonzero(actual.status_codes[:, slot] == METRIC_AVAILABLE)
        assert len(available_rows) == len(expected_points)
        for index, expected in zip(available_rows, expected_points, strict=True):
            assert float(actual.rank_ic[index, slot]).hex() == expected.rank_ic.hex()
            assert (
                float(actual.long_short_return_bps[index, slot]).hex()
                == expected.long_short_return_bps.hex()
            )
            assert float(actual.one_way_turnover[index, slot]).hex() == expected.one_way_turnover.hex()
            assert float(actual.coverage[index, slot]).hex() == expected.coverage.hex()
            assert (
                float(actual.quantile_monotonicity[index, slot]).hex()
                == expected.quantile_monotonicity.hex()
            )
        assert int(np.count_nonzero(actual.status_codes[:, slot] == METRIC_BOUNDARY_UNREALIZED)) == (
            expected_stats.boundary_unrealized_period_count
        )
        assert int(
            np.count_nonzero(actual.status_codes[:, slot] == METRIC_PARTIAL_LABEL_OMITTED)
        ) == expected_stats.partial_label_omitted_period_count
        assert int(
            np.count_nonzero(actual.status_codes[:, slot] == METRIC_INSUFFICIENT_CROSS_SECTION)
        ) == expected_stats.insufficient_cross_section_period_count


def test_fold01_direction_uses_exact_r1_numpy_mean_and_positive_zero_tie() -> None:
    candidate_ids = ("candidate-a", "candidate-b")
    annual = []
    observations: list[USR1CandidateObservation] = []
    for year in range(2001, 2006):
        arrays, year_observations = _candidate_arrays_and_r1_observations(
            session_dates=(date(year, 1, 3),),
            formations_per_session=5,
            candidate_ids=candidate_ids,
            include_diagnostics=False,
            role=USR1ObservationRole.TRAIN,
        )
        annual.append((year, arrays))
        observations.extend(year_observations)
    source_ids = {year: f"source-{year}" for year in range(2001, 2006)}
    actual = build_us_r2_primary_direction_evidence_exact(
        annual,
        plan=_plan(candidate_ids),
        source_annual_evidence_ids=source_ids,
    )
    policy = canonical_us_r1_statistical_evaluation_policy()
    assert actual.passed
    for item in actual.candidates:
        expected, _points = evaluate_us_r1_candidate_slice(
            observations,
            candidate_id=item.candidate_id,
            role=USR1ObservationRole.TRAIN,
            signal_interval=BarInterval.MINUTE_15,
            label_horizon_trading_minutes=60,
            policy=policy,
            minimum_periods=policy.minimum_train_periods,
        )
        assert expected.mean_raw_rank_ic is not None
        assert item.mean_raw_rank_ic is not None
        assert item.mean_raw_rank_ic.hex() == expected.mean_raw_rank_ic.hex()
        assert item.direction == (1 if expected.mean_raw_rank_ic >= 0.0 else -1)
        assert item.period_count == expected.period_count


def test_primary_metric_npz_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    rows = 8
    candidates = 37
    status = np.zeros((rows, candidates), dtype=np.uint8)
    base = np.arange(rows * candidates, dtype=np.float64).reshape(rows, candidates) / 1000.0
    arrays = USR2AnnualPrimaryMetricArrays(
        session_date_days=np.arange(rows, dtype=np.int32) + 20_000,
        formation_at_us=np.arange(rows, dtype=np.int64) + 1_000_000,
        regime_codes=np.arange(rows, dtype=np.uint8) % 4,
        rank_ic=base,
        long_short_return_bps=base + 1.0,
        one_way_turnover=base + 2.0,
        coverage=np.ones((rows, candidates), dtype=np.float64),
        quantile_monotonicity=base + 3.0,
        status_codes=status,
    )
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    first_hash, first_size = write_deterministic_us_r2_primary_metric_npz(first, arrays)
    second_hash, second_size = write_deterministic_us_r2_primary_metric_npz(second, arrays)
    assert first_hash == second_hash
    assert first_size == second_size
    assert first.read_bytes() == second.read_bytes()
    loaded = load_us_r2_primary_metric_npz(first)
    for name, expected in arrays.as_npz_arrays().items():
        assert np.array_equal(loaded.as_npz_arrays()[name], expected, equal_nan=True)


def _full_direction(candidate_ids: tuple[str, ...], plan: USR2PrimaryStatisticsPlan) -> USR2PrimaryDirectionEvidenceSet:
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
        plan_id=plan.plan_id,
        evaluation_policy_id=plan.evaluation_policy_id,
        candidate_cache_batch_evidence_id=plan.candidate_cache_batch_evidence_id,
        source_fold_id="us-r2-fold-01",
        source_years=(2001, 2002, 2003, 2004, 2005),
        source_annual_evidence_ids=tuple(f"source-{year}" for year in range(2001, 2006)),
        candidates=candidates,
    )


def _complete_fold_metric_array(candidate_count: int) -> USR2AnnualPrimaryMetricArrays:
    rows = 80
    regimes = np.repeat(np.arange(4, dtype=np.uint8), 20)
    sessions = np.concatenate(
        [np.arange(20, dtype=np.int32) + 20_000 + regime * 100 for regime in range(4)]
    )
    shape = (rows, candidate_count)
    return USR2AnnualPrimaryMetricArrays(
        session_date_days=sessions,
        formation_at_us=np.arange(rows, dtype=np.int64) + 1_000_000,
        regime_codes=regimes,
        rank_ic=np.full(shape, 0.02, dtype=np.float64),
        long_short_return_bps=np.full(shape, 2.0, dtype=np.float64),
        one_way_turnover=np.full(shape, 0.5, dtype=np.float64),
        coverage=np.full(shape, 1.0, dtype=np.float64),
        quantile_monotonicity=np.full(shape, 0.5, dtype=np.float64),
        status_codes=np.zeros(shape, dtype=np.uint8),
    )


def test_primary_report_requires_all_37_x_5_x_4_cells_and_preserves_thresholds() -> None:
    candidate_ids = tuple(f"candidate-{index:02d}" for index in range(37))
    plan = _plan(candidate_ids)
    fold_ids = tuple(f"us-r2-fold-{index:02d}" for index in range(1, 6))
    metrics = {fold_id: (_complete_fold_metric_array(37),) for fold_id in fold_ids}
    report = build_us_r2_primary_statistics_report(
        metrics,
        plan=plan,
        direction_evidence=_full_direction(candidate_ids, plan),
        annual_metric_evidence_ids=tuple(f"metric-{index}" for index in range(21)),
    )
    assert report.passed
    assert len(report.slices) == 37 * 5 * 4
    assert {item.regime for item in report.slices} == set(FROZEN_REGIME_LABELS)
    assert all(item.period_count == 20 and item.session_count == 20 for item in report.slices)

    r1_gate = canonical_us_r1_alpha_gate_policy()
    policy = canonical_us_r2_statistical_evaluation_policy().to_dict()
    thresholds = policy["inherited_primary_gate_thresholds"]
    assert isinstance(thresholds, dict)
    assert thresholds["min_primary_mean_rank_ic"] == r1_gate.min_primary_mean_rank_ic
    assert thresholds["min_worst_primary_cell_rank_ic"] == r1_gate.min_worst_fold_rank_ic
    assert thresholds["min_positive_primary_cell_ratio"] == r1_gate.min_positive_fold_ratio
    assert thresholds["min_coverage"] == r1_gate.min_coverage


def test_statistical_operator_has_no_raw_or_base_panel_data_path() -> None:
    script = Path("scripts/evaluate_us_r2_primary_statistics.py").read_text(encoding="utf-8")
    forbidden = (
        "manifest_from_huggingface_snapshot",
        "DuckDBParquetMinuteStore",
        "CalendarSessionizedMinuteStore",
        "MinuteQueryPlan",
        "materialize_us_r2_base_panel",
        "base-data-root",
        "OHLCV-1m",
    )
    for token in forbidden:
        assert token not in script
    assert script.count("read_parquet(?)") == 1  # reviewed small regime-v2 Parquet only
    assert '"raw_minute_source_access": False' in script
    assert '"annual_base_parquet_access": False' in script
    assert '"candidate_feature_recomputation": False' in script


def test_primary_metric_array_rejects_finite_values_with_unavailable_status() -> None:
    with pytest.raises(ValueError, match="finite values must match AVAILABLE status"):
        USR2AnnualPrimaryMetricArrays(
            session_date_days=np.asarray([20_000], dtype=np.int32),
            formation_at_us=np.asarray([1], dtype=np.int64),
            regime_codes=np.asarray([0], dtype=np.uint8),
            rank_ic=np.asarray([[0.1]], dtype=np.float64),
            long_short_return_bps=np.asarray([[1.0]], dtype=np.float64),
            one_way_turnover=np.asarray([[1.0]], dtype=np.float64),
            coverage=np.asarray([[1.0]], dtype=np.float64),
            quantile_monotonicity=np.asarray([[1.0]], dtype=np.float64),
            status_codes=np.asarray([[METRIC_INSUFFICIENT_CROSS_SECTION]], dtype=np.uint8),
        )
