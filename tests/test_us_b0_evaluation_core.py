from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.research.us_baseline_evaluation import (
    USBaselineObservation,
    USBaselineRunSpec,
    evaluate_us_baseline_candidate,
    evaluate_us_baseline_denominator,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator


def _run_spec(
    *,
    minimum_cross_section: int = 4,
    fail_on_partial_realized_label: bool = True,
) -> USBaselineRunSpec:
    denominator = canonical_us_baseline_denominator()
    return USBaselineRunSpec(
        certification_report_id="us-minute-research-cert-test",
        certification_outcome="CERTIFIED_FOR_ENGINEERING_RESEARCH",
        engineering_universe_id="engineering-universe-test",
        denominator_id=denominator.denominator_id,
        minimum_cross_section=minimum_cross_section,
        minimum_evaluated_periods=1,
        minimum_ic_periods=1,
        fail_on_partial_realized_label=fail_on_partial_realized_label,
    )


def _candidate(feature_id: str):
    denominator = canonical_us_baseline_denominator()
    return next(item for item in denominator.candidates if item.feature_id == feature_id)


def _period(
    feature_id: str,
    *,
    period_index: int,
    feature_values: tuple[float | None, ...],
    labels: tuple[float | None, ...],
    reasons: tuple[str | None, ...] | None = None,
) -> tuple[USBaselineObservation, ...]:
    spec = _candidate(feature_id)
    formation = datetime(2026, 3, 9, 14, 0, tzinfo=UTC) + timedelta(
        minutes=15 * period_index
    )
    resolved_reasons = reasons or tuple(
        None if value is not None else "target_crosses_session" for value in labels
    )
    rows = []
    for index, (feature, label, reason) in enumerate(
        zip(feature_values, labels, resolved_reasons, strict=True)
    ):
        rows.append(
            USBaselineObservation(
                feature_id=feature_id,
                feature_spec_id=spec.spec_id,
                asset=f"A{index:02d}",
                event_time=formation - timedelta(minutes=15),
                feature_available_at=formation,
                eligible_at_formation=True,
                feature_value=feature,
                realized_label=label,
                label_available_at=(
                    formation + timedelta(minutes=60) if label is not None else None
                ),
                label_unavailable_reason=reason,
            )
        )
    return tuple(rows)


def test_run_spec_requires_certified_data_and_binds_denominator() -> None:
    denominator = canonical_us_baseline_denominator()
    spec = _run_spec()

    assert spec.denominator_id == denominator.denominator_id
    assert spec.certification_outcome == "CERTIFIED_FOR_ENGINEERING_RESEARCH"
    assert spec.signal_interval == "15m"
    assert spec.label_name == "us_same_session_60m_simple_return_raw"
    assert USBaselineRunSpec(
        certification_report_id="cert",
        certification_outcome="CERTIFIED_FOR_ENGINEERING_RESEARCH",
        engineering_universe_id="universe",
        denominator_id=denominator.denominator_id,
    ).minimum_evaluated_periods == 20

    with pytest.raises(ValueError, match="accepted US-D3"):
        USBaselineRunSpec(
            certification_report_id="rejected",
            certification_outcome="REJECTED",
            engineering_universe_id="universe",
            denominator_id=denominator.denominator_id,
        )


def test_monotonic_cross_section_has_unit_rank_ic_and_deterministic_return() -> None:
    feature_id = "manual_momentum_4bar"
    candidate = _candidate(feature_id)
    rows = _period(
        feature_id,
        period_index=0,
        feature_values=(-2.0, -1.0, 1.0, 2.0),
        labels=(-0.04, -0.02, 0.02, 0.04),
    )

    result = evaluate_us_baseline_candidate(candidate, rows, run_spec=_run_spec())

    assert result.valid
    assert result.evaluated_periods == 1
    assert result.ic_periods == 1
    assert result.mean_rank_ic == pytest.approx(1.0)
    assert result.mean_gross_return is not None and result.mean_gross_return > 0
    assert result.mean_one_way_turnover == pytest.approx(0.5)
    assert result.mean_gross_traded_weight == pytest.approx(1.0)
    assert result.feature_coverage == pytest.approx(1.0)


def test_weights_are_formed_without_using_label_availability() -> None:
    feature_id = "manual_reversal_1bar"
    candidate = _candidate(feature_id)
    complete = _period(
        feature_id,
        period_index=0,
        feature_values=(-2.0, -1.0, 1.0, 2.0),
        labels=(0.04, 0.02, -0.02, -0.04),
    )
    partial = _period(
        feature_id,
        period_index=1,
        feature_values=(-3.0, -1.0, 1.0, 3.0),
        labels=(0.03, None, -0.01, -0.03),
        reasons=(None, "target_minute_missing", None, None),
    )

    result = evaluate_us_baseline_candidate(
        candidate,
        complete + partial,
        run_spec=_run_spec(),
    )

    assert result.evaluated_periods == 1
    assert result.feature_coverage == pytest.approx(1.0)
    assert result.blockers == (
        "partial_realized_label_missing:2026-03-09T14:15:00+00:00",
    )


def test_complete_case_policy_omits_entire_partial_label_period_without_reweighting() -> None:
    feature_id = "manual_reversal_1bar"
    candidate = _candidate(feature_id)
    first = _period(
        feature_id,
        period_index=0,
        feature_values=(-2.0, -1.0, 1.0, 2.0),
        labels=(0.04, 0.02, -0.02, -0.04),
    )
    partial = _period(
        feature_id,
        period_index=1,
        feature_values=(-3.0, -1.0, 1.0, 3.0),
        labels=(0.03, None, -0.01, -0.03),
        reasons=(None, "target_minute_missing", None, None),
    )
    third = _period(
        feature_id,
        period_index=2,
        feature_values=(2.0, 1.0, -1.0, -2.0),
        labels=(-0.04, -0.02, 0.02, 0.04),
    )

    result = evaluate_us_baseline_candidate(
        candidate,
        first + partial + third,
        run_spec=_run_spec(fail_on_partial_realized_label=False),
    )

    assert result.valid
    assert result.evaluated_periods == 2
    assert result.ic_periods == 2
    assert result.partial_realized_label_omitted_periods == 1
    assert result.blockers == ()
    # The omitted period does not become the turnover baseline.  Turnover moves
    # directly from the first accepted cross-section to the third.
    assert result.mean_one_way_turnover == pytest.approx(0.75)
    assert result.to_dict()["partial_realized_label_omitted_periods"] == 1


def test_all_cross_session_labels_are_expected_boundary_not_zero_filled() -> None:
    feature_id = "manual_close_location_1bar"
    candidate = _candidate(feature_id)
    boundary = _period(
        feature_id,
        period_index=0,
        feature_values=(-2.0, -1.0, 1.0, 2.0),
        labels=(None, None, None, None),
        reasons=(
            "target_crosses_session",
            "target_crosses_session",
            "target_crosses_session",
            "target_crosses_session",
        ),
    )

    result = evaluate_us_baseline_candidate(candidate, boundary, run_spec=_run_spec())

    assert result.valid is False
    assert result.evaluated_periods == 0
    assert result.boundary_unrealized_periods == 1
    assert result.mean_gross_return is None
    assert result.mean_rank_ic is None
    assert result.blockers == (
        "insufficient_evaluated_periods:0<1",
        "insufficient_ic_periods:0<1",
    )


def test_feature_missingness_changes_coverage_not_formation_eligibility() -> None:
    feature_id = "manual_range_mean_4bar"
    candidate = _candidate(feature_id)
    rows = _period(
        feature_id,
        period_index=0,
        feature_values=(None, -1.0, 1.0, 2.0, 3.0),
        labels=(0.0, -0.02, 0.01, 0.02, 0.03),
    )

    result = evaluate_us_baseline_candidate(
        candidate,
        rows,
        run_spec=_run_spec(minimum_cross_section=4),
    )

    assert result.eligible_cell_count == 5
    assert result.valid_feature_cell_count == 4
    assert result.feature_coverage == pytest.approx(0.8)
    assert result.evaluated_periods == 1


def test_turnover_is_deterministic_across_formation_periods() -> None:
    feature_id = "manual_momentum_8bar"
    candidate = _candidate(feature_id)
    first = _period(
        feature_id,
        period_index=0,
        feature_values=(-2.0, -1.0, 1.0, 2.0),
        labels=(-0.02, -0.01, 0.01, 0.02),
    )
    second = _period(
        feature_id,
        period_index=1,
        feature_values=(2.0, 1.0, -1.0, -2.0),
        labels=(0.02, 0.01, -0.01, -0.02),
    )

    result = evaluate_us_baseline_candidate(
        candidate,
        first + second,
        run_spec=_run_spec(),
    )

    assert result.evaluated_periods == 2
    assert result.mean_one_way_turnover == pytest.approx(0.75)
    assert result.mean_gross_traded_weight == pytest.approx(1.5)


def test_full_denominator_retains_and_marks_missing_candidates_invalid() -> None:
    denominator = canonical_us_baseline_denominator()
    run_spec = _run_spec()
    first = denominator.candidates[0]
    rows = _period(
        first.feature_id,
        period_index=0,
        feature_values=(-2.0, -1.0, 1.0, 2.0),
        labels=(-0.02, -0.01, 0.01, 0.02),
    )

    report = evaluate_us_baseline_denominator(
        denominator,
        {first.feature_id: rows},
        run_spec=run_spec,
    )

    assert len(report.candidates) == 8
    assert report.denominator_id == denominator.denominator_id
    assert report.candidates[0].observation_count == 4
    assert report.candidates[0].valid
    assert all(item.observation_count == 0 for item in report.candidates[1:])
    assert all(not item.valid for item in report.candidates[1:])
    assert report.valid_candidate_count == 1
    assert report.report_id == evaluate_us_baseline_denominator(
        denominator,
        {first.feature_id: rows},
        run_spec=run_spec,
    ).report_id


def test_duplicate_asset_formation_time_fails_closed() -> None:
    feature_id = "manual_momentum_4bar"
    candidate = _candidate(feature_id)
    rows = list(
        _period(
            feature_id,
            period_index=0,
            feature_values=(-2.0, -1.0, 1.0, 2.0),
            labels=(-0.04, -0.02, 0.02, 0.04),
        )
    )
    rows.append(rows[0])

    with pytest.raises(ValueError, match="duplicate/non-increasing"):
        evaluate_us_baseline_candidate(candidate, rows, run_spec=_run_spec())


def test_observation_requires_forward_label_to_mature_after_formation() -> None:
    candidate = _candidate("manual_momentum_4bar")
    formation = datetime(2026, 3, 9, 14, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="mature after"):
        USBaselineObservation(
            feature_id=candidate.feature_id,
            feature_spec_id=candidate.spec_id,
            asset="A00",
            event_time=formation - timedelta(minutes=15),
            feature_available_at=formation,
            eligible_at_formation=True,
            feature_value=1.0,
            realized_label=0.01,
            label_available_at=formation,
        )
