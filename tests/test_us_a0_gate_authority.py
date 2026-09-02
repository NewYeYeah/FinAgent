from __future__ import annotations

import hashlib
import json

import pytest

from finagent.research.us_agent_value_gate_authority import (
    require_us_a0_pilot_formal_progression_authority,
)


def _hash(payload: object, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _pilot_review() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "finagent.us-agent-value-gate-review.v1",
        "assessment": {"assessment_id": "assessment-test"},
        "assessment_id": "assessment-test",
        "policy_id": "policy-test",
        "phase": "PILOT",
        "reviewer_id": "reviewer-test",
        "reviewed_at": "2026-09-02T06:30:00+00:00",
        "decision": "PILOT_PROCEED_TO_FORMAL",
        "review_notes": "Synthetic authority fixture for status binding.",
        "attestations": {
            "thresholds_unchanged_after_result": True,
            "evidence_lineage_verified": True,
            "alpha_gate_is_separate": True,
            "project_stage_authority_is_separate": True,
        },
        "formal_progression_authority": True,
        "agent_value_gate_authority": False,
        "supports_agent_retention_for_us_r1": False,
        "supports_agent_scope_contraction": False,
        "status_authority": False,
        "stage_exit_authority": False,
        "alpha_authority": False,
    }
    payload["review_id"] = _hash(payload, "us-agent-value-gate-review")
    return payload


def _status(review_id: str) -> dict[str, object]:
    return {
        "current_stage": "US-A0",
        "stage": {
            "us_a0": {
                "pilot_gate_review_status": "accepted",
                "pilot_gate_review_id": review_id,
                "pilot_formal_progression_approved": True,
            }
        },
    }


def test_formal_progression_requires_exact_status_accepted_pilot_review() -> None:
    review = _pilot_review()
    review_id = str(review["review_id"])

    assert require_us_a0_pilot_formal_progression_authority(
        _status(review_id),
        review,
    ) == review_id

    with pytest.raises(ValueError, match="docs/status.toml authority"):
        require_us_a0_pilot_formal_progression_authority(
            _status("different-review-id"),
            review,
        )


def test_formal_progression_fails_closed_without_status_acceptance() -> None:
    review = _pilot_review()
    review_id = str(review["review_id"])
    status = _status(review_id)
    us_a0 = status["stage"]["us_a0"]  # type: ignore[index]
    us_a0["pilot_gate_review_status"] = "pending"  # type: ignore[index]

    with pytest.raises(ValueError, match="accepted PILOT gate review"):
        require_us_a0_pilot_formal_progression_authority(status, review)


def test_pilot_review_cannot_smuggle_alpha_authority() -> None:
    review = _pilot_review()
    review["alpha_authority"] = True
    payload = dict(review)
    payload.pop("review_id")
    review["review_id"] = _hash(payload, "us-agent-value-gate-review")

    with pytest.raises(ValueError, match="alpha_authority=false"):
        require_us_a0_pilot_formal_progression_authority(
            _status(str(review["review_id"])),
            review,
        )
