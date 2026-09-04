from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from finagent.research.us_r1_gate import canonical_us_r1_alpha_gate_policy
from finagent.research.us_r2_final import (
    USR2FinalCandidateEvidence,
    USR2FinalFamilyEvidence,
    assess_us_r2_alpha_gate,
    canonical_us_r2_alpha_gate_policy,
    finalize_us_r2_alpha_gate_review,
)
from finagent.research.us_r2_frozen_protocol import FROZEN_REGIME_LABELS
from finagent.research.us_r2_protocol import USR2Terminal


def _candidate(index: int, **changes: Any) -> USR2FinalCandidateEvidence:
    base = USR2FinalCandidateEvidence(
        candidate_id=f"candidate-{index:02d}",
        fold_regime_cell_count=20,
        mean_directed_rank_ic=0.02,
        worst_fold_regime_rank_ic=0.001,
        regime_mean_directed_rank_ic=tuple((regime, 0.02) for regime in FROZEN_REGIME_LABELS),
        worst_regime_mean_directed_rank_ic=0.02,
        mean_fold_regime_rank_icir=0.10,
        worst_fold_regime_rank_icir=0.01,
        positive_fold_regime_ratio=1.0,
        raw_hac_pvalue=0.001,
        holm_adjusted_pvalue=0.01,
        bh_qvalue=0.01,
        session_bootstrap_pvalue=0.001,
        session_bootstrap_ci_lower=0.001,
        session_bootstrap_ci_upper=0.03,
        frequency_sign_consistency_by_regime=tuple(
            (regime, 2.0 / 3.0) for regime in FROZEN_REGIME_LABELS
        ),
        all_regimes_frequency_passed=True,
        decay_sign_consistency_by_regime=tuple(
            (regime, 2.0 / 3.0) for regime in FROZEN_REGIME_LABELS
        ),
        all_regimes_decay_passed=True,
        coverage_mean=0.95,
        coverage_min=0.90,
        quantile_monotonicity=0.50,
        mean_long_short_return_bps=2.0,
        mean_one_way_turnover=0.50,
        return_per_turnover_bps=4.0,
    )
    return replace(base, **changes)


def _family(candidates: tuple[USR2FinalCandidateEvidence, ...]) -> USR2FinalFamilyEvidence:
    policy = canonical_us_r2_alpha_gate_policy()
    return USR2FinalFamilyEvidence(
        frozen_protocol_id=policy.frozen_protocol_id,
        denominator_id=policy.denominator_id,
        primary_statistics_report_id="primary",
        pooled_inference_report_id="pooled",
        candidate_robustness_report_id="robustness",
        candidates=candidates,
    )


def test_r2_gate_inherits_every_r1_numeric_threshold_without_relaxation() -> None:
    r1 = canonical_us_r1_alpha_gate_policy()
    r2 = canonical_us_r2_alpha_gate_policy()

    assert r2.inherited_r1_alpha_gate_policy_id == r1.policy_id
    assert r2.required_fold_count == 5
    assert r2.required_regime_count == 4
    assert r2.required_fold_regime_cell_count == 20
    assert r2.min_primary_mean_rank_ic == r1.min_primary_mean_rank_ic
    assert r2.min_worst_fold_regime_rank_ic == r1.min_worst_fold_rank_ic
    assert r2.min_mean_fold_regime_rank_icir == r1.min_mean_fold_rank_icir
    assert r2.min_worst_fold_regime_rank_icir == r1.min_worst_fold_rank_icir
    assert r2.min_positive_fold_regime_ratio == r1.min_positive_fold_ratio
    assert r2.max_raw_hac_pvalue == r1.max_raw_hac_pvalue
    assert r2.max_holm_adjusted_pvalue == r1.max_holm_adjusted_pvalue
    assert r2.max_bh_qvalue == r1.max_bh_qvalue
    assert r2.max_session_bootstrap_pvalue == r1.max_session_bootstrap_pvalue
    assert r2.min_session_bootstrap_ci_lower == r1.min_session_bootstrap_ci_lower
    assert r2.min_frequency_sign_consistency == r1.min_frequency_sign_consistency
    assert r2.min_decay_sign_consistency == r1.min_decay_sign_consistency
    assert r2.min_coverage == r1.min_coverage
    assert r2.min_quantile_monotonicity == r1.min_quantile_monotonicity
    assert r2.min_mean_long_short_return_bps == r1.min_mean_long_short_return_bps
    assert r2.max_mean_one_way_turnover == r1.max_mean_one_way_turnover
    assert r2.min_return_per_turnover_bps == r1.min_return_per_turnover_bps
    assert r2.to_dict()["thresholds_relaxed"] is False


def test_positive_terminal_requires_every_candidate_gate_and_review_preserves_boundaries() -> None:
    candidates = tuple(_candidate(index) for index in range(37))
    artifacts_family = _family(candidates)
    assessment = assess_us_r2_alpha_gate(artifacts_family)

    assert assessment.terminal is USR2Terminal.ROBUST_FACTOR_FAMILY
    assert assessment.robust_candidate_ids == tuple(item.candidate_id for item in candidates)


def test_any_failed_dimension_remains_research_result_not_system_failure() -> None:
    candidates = tuple(_candidate(index, quantile_monotonicity=0.10) for index in range(37))
    assessment = assess_us_r2_alpha_gate(_family(candidates))

    assert assessment.terminal is USR2Terminal.NO_ROBUST_FACTOR_FAMILY
    assert assessment.robust_candidate_ids == ()
    assert all(
        item.reasons == ("QUANTILE_MONOTONICITY_BELOW_THRESHOLD",) for item in assessment.candidates
    )


def test_per_regime_frequency_and_decay_are_both_mandatory() -> None:
    candidates = tuple(
        _candidate(
            index,
            all_regimes_frequency_passed=False,
            all_regimes_decay_passed=False,
        )
        for index in range(37)
    )
    assessment = assess_us_r2_alpha_gate(_family(candidates))

    assert assessment.terminal is USR2Terminal.NO_ROBUST_FACTOR_FAMILY
    assert assessment.candidates[0].reasons == (
        "FREQUENCY_SIGN_INCONSISTENT_IN_ONE_OR_MORE_REGIMES",
        "DECAY_SIGN_INCONSISTENT_IN_ONE_OR_MORE_REGIMES",
    )


def test_review_may_not_upgrade_machine_terminal() -> None:
    family = _family(tuple(_candidate(index, coverage_min=0.50) for index in range(37)))
    assessment = assess_us_r2_alpha_gate(family)

    with pytest.raises(ValueError, match="accept the assessment or downgrade"):
        from finagent.research.us_r2_final import USR2FinalArtifacts, USR2InferenceEvidenceGraph

        policy = canonical_us_r2_alpha_gate_policy()
        graph = USR2InferenceEvidenceGraph(
            frozen_protocol_id=policy.frozen_protocol_id,
            denominator_id=policy.denominator_id,
            primary_statistics_report_id="primary",
            pooled_inference_report_id="pooled",
            candidate_robustness_report_id="robustness",
            family_evidence_id=family.evidence_id,
            alpha_gate_policy_id=policy.policy_id,
            alpha_gate_assessment_id=assessment.assessment_id,
        )
        finalize_us_r2_alpha_gate_review(
            USR2FinalArtifacts(policy, family, assessment, graph),
            reviewer_id="independent-reviewer",
            reviewed_at=datetime(2026, 9, 5, tzinfo=UTC),
            review_notes="Independent replay confirms every frozen evidence boundary.",
            terminal=USR2Terminal.ROBUST_FACTOR_FAMILY,
        )
