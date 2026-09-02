from __future__ import annotations

from finagent.research.us_baseline_evaluation import (
    USBaselineCandidateEvidence,
    USBaselineEvaluationReport,
    USBaselineRunSpec,
)
from finagent.research.us_baseline_walkforward import (
    bind_us_b0_fold_execution_specs,
    canonical_us_b0_pilot_walk_forward,
)
from finagent.research.us_baseline_walkforward_aggregate import aggregate_us_b0_walk_forward
from finagent.research.us_baselines import canonical_us_baseline_denominator


def _run_spec() -> USBaselineRunSpec:
    denominator = canonical_us_baseline_denominator()
    return USBaselineRunSpec(
        certification_report_id="us-minute-research-cert-test",
        certification_outcome="CERTIFIED_FOR_ENGINEERING_RESEARCH",
        engineering_universe_id="engineering-universe-test",
        denominator_id=denominator.denominator_id,
    )


def _report(
    fold_index: int,
    *,
    invalid_feature: str | None = None,
) -> USBaselineEvaluationReport:
    denominator = canonical_us_baseline_denominator()
    run_spec = _run_spec()
    candidates = tuple(
        USBaselineCandidateEvidence(
            feature_id=spec.feature_id,
            feature_spec_id=spec.spec_id,
            run_spec_id=run_spec.spec_id,
            observation_count=100,
            eligible_cell_count=100,
            valid_feature_cell_count=95,
            evaluated_periods=30,
            ic_periods=30,
            boundary_unrealized_periods=2,
            mean_rank_ic=(-0.03 + 0.01 * fold_index if index == 0 else 0.02 + index * 0.001),
            mean_gross_return=(-0.001 + 0.0005 * fold_index if index == 0 else 0.001),
            mean_one_way_turnover=0.10 + 0.01 * fold_index,
            mean_gross_traded_weight=0.20 + 0.02 * fold_index,
            feature_coverage=0.95,
            blockers=("insufficient_ic_periods",) if spec.feature_id == invalid_feature else (),
        )
        for index, spec in enumerate(denominator.candidates)
    )
    return USBaselineEvaluationReport(
        run_spec=run_spec,
        denominator_id=denominator.denominator_id,
        candidates=candidates,
    )


def test_walk_forward_aggregate_retains_full_denominator_and_worst_fold_metrics() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    run_spec = _run_spec()
    executions = bind_us_b0_fold_execution_specs(protocol, run_spec)
    reports = tuple(_report(index) for index in range(3))

    aggregate = aggregate_us_b0_walk_forward(protocol, executions, reports)

    assert aggregate.passed
    assert len(aggregate.candidates) == 8
    first = aggregate.candidates[0]
    assert first.mean_rank_ic == -0.02
    assert first.worst_fold_rank_ic == -0.03
    assert first.valid_fold_count == 3
    assert aggregate.to_dict()["factor_selection_authority"] is False
    assert aggregate.to_dict()["alpha_authority"] is False


def test_negative_worst_fold_is_a_result_not_a_structural_blocker() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    run_spec = _run_spec()
    aggregate = aggregate_us_b0_walk_forward(
        protocol,
        bind_us_b0_fold_execution_specs(protocol, run_spec),
        tuple(_report(index) for index in range(3)),
    )

    first = aggregate.candidates[0]
    assert first.worst_fold_rank_ic < 0
    assert first.blockers == ()
    assert first.valid


def test_invalid_candidate_fold_is_preserved_as_aggregate_blocker() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    run_spec = _run_spec()
    feature_id = canonical_us_baseline_denominator().candidates[0].feature_id
    reports = (
        _report(0),
        _report(1, invalid_feature=feature_id),
        _report(2),
    )

    aggregate = aggregate_us_b0_walk_forward(
        protocol,
        bind_us_b0_fold_execution_specs(protocol, run_spec),
        reports,
    )

    assert not aggregate.passed
    first = aggregate.candidates[0]
    assert first.valid_fold_count == 2
    assert "fold:2:insufficient_ic_periods" in first.blockers
    assert any(item.startswith(f"candidate:{feature_id}:") for item in aggregate.blockers)
