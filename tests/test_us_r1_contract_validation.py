from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.research.us_r1_contracts import (
    validate_us_r1_alpha_gate_policy,
    validate_us_r1_research_protocol,
)
from finagent.research.us_r1_gate import (
    USR1AlphaGateAssessment,
    USR1CandidateGateAssessment,
    canonical_us_r1_alpha_gate_policy,
)
from finagent.research.us_r1_protocol import (
    USR1Terminal,
    canonical_us_r1_research_protocol,
)
from finagent.research.us_r1_review import finalize_us_r1_alpha_gate_review

_NOW = datetime(2026, 9, 2, 11, 45, tzinfo=UTC)


def _assessment(terminal: USR1Terminal) -> USR1AlphaGateAssessment:
    passed = terminal is USR1Terminal.ROBUST_FACTOR_FAMILY
    return USR1AlphaGateAssessment(
        policy_id=canonical_us_r1_alpha_gate_policy().policy_id,
        family_evidence_id="us-r1-family-evidence-test",
        denominator_id="us-r1-denominator-test",
        terminal=terminal,
        candidates=(
            USR1CandidateGateAssessment(
                candidate_id="candidate-test",
                passed=passed,
                reasons=() if passed else ("PRIMARY_MEAN_RANK_IC_BELOW_THRESHOLD",),
            ),
        ),
        robust_candidate_ids=("candidate-test",) if passed else (),
        technical_blockers=("missing_frequency_materialization",)
        if terminal is USR1Terminal.SYSTEM_FAILURE
        else (),
    )


def _review(terminal: USR1Terminal):
    assessment = _assessment(terminal)
    return finalize_us_r1_alpha_gate_review(
        assessment,
        reviewer_id="us-r1-contract-reviewer",
        reviewed_at=_NOW,
        review_notes="The preregistered Alpha Gate assessment and exact evidence lineage are accepted.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        agent_value_gate_separation_attested=True,
        execution_gate_separation_attested=True,
        live_capital_separation_attested=True,
    )


def test_us_r1_protocol_validator_requires_full_canonical_document() -> None:
    protocol = canonical_us_r1_research_protocol()
    assert validate_us_r1_research_protocol(protocol.to_dict()) == protocol
    drifted = dict(protocol.to_dict())
    drifted["purge_trading_minutes"] = 45
    with pytest.raises(ValueError, match="exact frozen canonical protocol"):
        validate_us_r1_research_protocol(drifted)


def test_us_r1_alpha_gate_policy_validator_rejects_post_result_threshold_drift() -> None:
    policy = canonical_us_r1_alpha_gate_policy()
    assert validate_us_r1_alpha_gate_policy(policy.to_dict()) == policy
    drifted = dict(policy.to_dict())
    drifted["min_primary_mean_rank_ic"] = 0.0
    with pytest.raises(ValueError, match="exact frozen canonical policy"):
        validate_us_r1_alpha_gate_policy(drifted)


def test_positive_alpha_review_has_gate_and_positive_alpha_authority_only() -> None:
    review = _review(USR1Terminal.ROBUST_FACTOR_FAMILY)
    assert review.alpha_gate_authority
    assert review.alpha_authority
    assert review.supports_us_x0_progression
    assert review.to_dict()["order_authority"] is False
    assert review.to_dict()["live_capital_authority"] is False


def test_negative_alpha_review_is_authoritative_but_does_not_claim_alpha() -> None:
    review = _review(USR1Terminal.NO_ROBUST_FACTOR_FAMILY)
    assert review.alpha_gate_authority
    assert not review.alpha_authority
    assert not review.supports_us_x0_progression
    assert review.to_dict()["status_authority"] is False
    assert review.to_dict()["stage_exit_authority"] is False
