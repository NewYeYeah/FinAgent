from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from finagent.research.factor_stability import adjust_family_pvalues
from finagent.research.us_r1_inference import (
    USR1PeriodMetricPoint,
    newey_west_mean_test,
    session_block_bootstrap_mean_test,
)
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r2_frozen_protocol import FROZEN_REGIME_LABELS
from finagent.research.us_r2_pooled_inference import (
    FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID,
    FROZEN_PRIMARY_EVALUATION_POLICY_ID,
    FROZEN_PRIMARY_STATISTICS_PLAN_ID,
    FROZEN_PRIMARY_STATISTICS_REPORT_ID,
    POOLED_INFERENCE_YEARS,
    USR2PooledCandidateInference,
    USR2PooledInferenceReport,
    adjust_us_r2_pooled_rank_ic_pvalues,
    build_us_r2_raw_pooled_candidate_inference,
    collect_us_r2_pooled_candidate_points,
    validate_us_r2_primary_statistics_report_gate,
)
from finagent.research.us_r2_primary_statistics import (
    METRIC_AVAILABLE,
    USR2AnnualPrimaryMetricArrays,
)

_EPOCH_DATE = date(1970, 1, 1)
_EPOCH_DATETIME = datetime(1970, 1, 1, tzinfo=UTC)


def _day(value: date) -> int:
    return (value - _EPOCH_DATE).days


def _us(value: datetime) -> int:
    return int((value - _EPOCH_DATETIME).total_seconds() * 1_000_000)


def _annual_arrays(year: int, *, offset: int) -> USR2AnnualPrimaryMetricArrays:
    rows = 20
    session_dates = [date(year, 1, 1) + timedelta(days=index) for index in range(rows)]
    formations = [
        datetime(year, 1, 1, 14, 30, tzinfo=UTC) + timedelta(days=index)
        for index in range(rows)
    ]
    base = np.arange(offset, offset + rows, dtype=np.float64)
    rank = ((base % 17.0) - 8.0) / 100.0
    long_short = ((base % 13.0) - 6.0) * 2.5
    turnover = 0.2 + (base % 5.0) / 20.0
    coverage = 0.8 + (base % 4.0) / 20.0
    monotonicity = ((base % 9.0) - 4.0) / 5.0
    return USR2AnnualPrimaryMetricArrays(
        session_date_days=np.asarray([_day(item) for item in session_dates], dtype=np.int32),
        formation_at_us=np.asarray([_us(item) for item in formations], dtype=np.int64),
        regime_codes=np.asarray([int(item) % 4 for item in base], dtype=np.uint8),
        rank_ic=rank[:, None],
        long_short_return_bps=long_short[:, None],
        one_way_turnover=turnover[:, None],
        coverage=coverage[:, None],
        quantile_monotonicity=monotonicity[:, None],
        status_codes=np.full((rows, 1), METRIC_AVAILABLE, dtype=np.uint8),
    )


def _synthetic_annual_series() -> tuple[tuple[int, USR2AnnualPrimaryMetricArrays], ...]:
    return tuple(
        (year, _annual_arrays(year, offset=index * 20))
        for index, year in enumerate(POOLED_INFERENCE_YEARS)
    )


def _hex_tuple(values: tuple[float, ...]) -> tuple[str, ...]:
    return tuple(float(value).hex() for value in values)


def test_pooled_series_is_chronological_and_never_regime_grouped() -> None:
    annual = _synthetic_annual_series()
    points, regime_codes = collect_us_r2_pooled_candidate_points(annual, candidate_slot=0)

    assert len(points) == 420
    assert len({point.session_id for point in points}) == 420
    assert all(left.event_time < right.event_time for left, right in zip(points, points[1:]))
    assert tuple(regime_codes[:8]) == (0, 1, 2, 3, 0, 1, 2, 3)
    assert tuple(FROZEN_REGIME_LABELS[code] for code in regime_codes[:4]) == FROZEN_REGIME_LABELS


def test_rank_ic_hac_and_session_bootstrap_are_exact_r1_parity() -> None:
    points, regime_codes = collect_us_r2_pooled_candidate_points(
        _synthetic_annual_series(),
        candidate_slot=0,
    )
    direction = -1
    raw = build_us_r2_raw_pooled_candidate_inference(
        candidate_id="synthetic",
        direction=direction,
        points=points,
        regime_codes=regime_codes,
    )
    r1 = canonical_us_r1_research_protocol()
    expected_hac = newey_west_mean_test(
        tuple(direction * point.rank_ic for point in points),
        lags=r1.hac_lags_15m,
    )
    expected_bootstrap = session_block_bootstrap_mean_test(
        points,
        direction=direction,
        samples=r1.bootstrap_samples,
        block_sessions=r1.bootstrap_block_sessions,
        seed=r1.bootstrap_seed,
    )

    assert raw.rank_ic_hac_lags == r1.hac_lags_15m == 4
    assert _hex_tuple((raw.rank_ic_hac_tstat, raw.rank_ic_raw_hac_pvalue)) == _hex_tuple(
        expected_hac
    )
    assert _hex_tuple(
        (
            raw.rank_ic_bootstrap_pvalue,
            raw.rank_ic_bootstrap_ci_lower,
            raw.rank_ic_bootstrap_ci_upper,
        )
    ) == _hex_tuple(expected_bootstrap)


def test_long_short_diagnostic_uses_same_hac_and_session_block_mechanics() -> None:
    points, regime_codes = collect_us_r2_pooled_candidate_points(
        _synthetic_annual_series(),
        candidate_slot=0,
    )
    direction = 1
    raw = build_us_r2_raw_pooled_candidate_inference(
        candidate_id="synthetic",
        direction=direction,
        points=points,
        regime_codes=regime_codes,
    )
    r1 = canonical_us_r1_research_protocol()
    expected_hac = newey_west_mean_test(
        tuple(direction * point.long_short_return_bps for point in points),
        lags=r1.hac_lags_15m,
    )
    surrogate = tuple(
        USR1PeriodMetricPoint(
            event_time=point.event_time,
            session_id=point.session_id,
            rank_ic=point.long_short_return_bps,
            long_short_return_bps=point.long_short_return_bps,
            one_way_turnover=point.one_way_turnover,
            coverage=point.coverage,
            quantile_monotonicity=point.quantile_monotonicity,
        )
        for point in points
    )
    expected_bootstrap = session_block_bootstrap_mean_test(
        surrogate,
        direction=direction,
        samples=r1.bootstrap_samples,
        block_sessions=r1.bootstrap_block_sessions,
        seed=r1.bootstrap_seed,
    )

    assert _hex_tuple((raw.long_short_hac_tstat, raw.long_short_raw_hac_pvalue)) == _hex_tuple(
        expected_hac
    )
    assert _hex_tuple(
        (
            raw.long_short_bootstrap_pvalue,
            raw.long_short_bootstrap_ci_lower_bps,
            raw.long_short_bootstrap_ci_upper_bps,
        )
    ) == _hex_tuple(expected_bootstrap)


def test_multiplicity_is_exact_full_37_denominator_r1_parity() -> None:
    candidate_ids = tuple(f"candidate-{index:02d}" for index in range(37))
    raw = {
        candidate_id: min(0.99, 0.001 + index * 0.017)
        for index, candidate_id in enumerate(candidate_ids)
    }

    observed = adjust_us_r2_pooled_rank_ic_pvalues(candidate_ids, raw)
    expected = adjust_family_pvalues(raw)

    assert observed == expected
    with pytest.raises(ValueError, match="exactly 37"):
        adjust_us_r2_pooled_rank_ic_pvalues(candidate_ids[:-1], dict(list(raw.items())[:-1]))
    tampered = dict(raw)
    tampered.pop(candidate_ids[-1])
    tampered["replacement"] = 0.5
    with pytest.raises(ValueError, match="denominator differs"):
        adjust_us_r2_pooled_rank_ic_pvalues(candidate_ids, tampered)


def test_pooled_builder_rejects_regime_grouped_or_incomplete_time_input() -> None:
    annual = list(_synthetic_annual_series())
    annual[1], annual[2] = annual[2], annual[1]
    with pytest.raises(ValueError, match="exact 2006-2026 order"):
        collect_us_r2_pooled_candidate_points(tuple(annual), candidate_slot=0)

    points, regimes = collect_us_r2_pooled_candidate_points(
        _synthetic_annual_series(),
        candidate_slot=0,
    )
    with pytest.raises(ValueError, match="incomplete"):
        build_us_r2_raw_pooled_candidate_inference(
            candidate_id="short",
            direction=1,
            points=points[:399],
            regime_codes=regimes[:399],
        )


def test_pooled_report_remains_non_authoritative() -> None:
    points, regimes = collect_us_r2_pooled_candidate_points(
        _synthetic_annual_series(),
        candidate_slot=0,
    )
    base_raw = build_us_r2_raw_pooled_candidate_inference(
        candidate_id="candidate-00",
        direction=1,
        points=points,
        regime_codes=regimes,
    )
    candidates = tuple(
        USR2PooledCandidateInference(
            raw=replace(base_raw, candidate_id=f"candidate-{index:02d}"),
            holm_adjusted_rank_ic_pvalue=0.5,
            bh_rank_ic_qvalue=0.4,
        )
        for index in range(37)
    )
    report = USR2PooledInferenceReport(
        primary_statistics_report_id=FROZEN_PRIMARY_STATISTICS_REPORT_ID,
        primary_statistics_plan_id=FROZEN_PRIMARY_STATISTICS_PLAN_ID,
        evaluation_policy_id=FROZEN_PRIMARY_EVALUATION_POLICY_ID,
        direction_evidence_id=FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID,
        denominator_id="denominator",
        annual_metric_evidence_ids=tuple(f"annual-{year}" for year in POOLED_INFERENCE_YEARS),
        candidates=candidates,
    )
    payload = report.to_dict()

    assert report.passed is True
    assert payload["frequency_robustness_evaluated"] is False
    assert payload["decay_robustness_evaluated"] is False
    assert payload["candidate_selection_applied"] is False
    assert payload["alpha_gate_evaluated"] is False
    assert payload["terminal_authority"] is False
    assert payload["stage_exit_authority"] is False
    assert payload["alpha_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["order_authority"] is False
    assert payload["paper_authority"] is False
    assert payload["live_capital_authority"] is False
    assert payload["raw_minute_source_access"] is False
    assert payload["annual_base_parquet_access"] is False
    assert payload["candidate_cache_npz_access"] is False


def test_primary_report_gate_rejects_any_nonreviewed_content() -> None:
    class _Plan:
        plan_id = FROZEN_PRIMARY_STATISTICS_PLAN_ID
        candidate_ids = tuple(f"candidate-{index:02d}" for index in range(37))

    class _Direction:
        evidence_id = FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID

        @staticmethod
        def direction(_candidate_id: str) -> int:
            return 1

    document: dict[str, object] = {
        "schema_version": "finagent.us-r2-primary-statistics-report.v1",
        "report_id": FROZEN_PRIMARY_STATISTICS_REPORT_ID,
        "plan_id": FROZEN_PRIMARY_STATISTICS_PLAN_ID,
        "evaluation_policy_id": FROZEN_PRIMARY_EVALUATION_POLICY_ID,
        "direction_evidence_id": FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID,
        "annual_metric_evidence_ids": [f"annual-{year}" for year in POOLED_INFERENCE_YEARS],
        "slice_count": 740,
        "slices": [],
        "passed": True,
        "blockers": [],
        "hac_bootstrap_multiplicity_evaluated": False,
        "frequency_robustness_evaluated": False,
        "decay_robustness_evaluated": False,
        "alpha_gate_evaluated": False,
        "terminal_authority": False,
        "stage_exit_authority": False,
        "alpha_authority": False,
        "execution_authority": False,
    }
    with pytest.raises(ValueError, match="content-addressed identity mismatch"):
        validate_us_r2_primary_statistics_report_gate(
            document,
            plan=_Plan(),  # type: ignore[arg-type]
            direction=_Direction(),  # type: ignore[arg-type]
            policy=__import__(
                "finagent.research.us_r2_evaluation_policy",
                fromlist=["canonical_us_r2_statistical_evaluation_policy"],
            ).canonical_us_r2_statistical_evaluation_policy(),
        )


def test_operator_has_no_candidate_or_raw_source_arguments() -> None:
    source = Path("scripts/evaluate_us_r2_pooled_inference.py").read_text(encoding="utf-8")
    assert "--candidate-data-root" not in source
    assert "--candidate-cache-plan" not in source
    assert "--regime-data" not in source
    assert "raw_minute_source_access\": False" in source
    assert "candidate_cache_npz_access\": False" in source
