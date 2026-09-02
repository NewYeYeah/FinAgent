from __future__ import annotations

from collections.abc import Mapping

from finagent.research.us_agent_value_gate import (
    validate_pilot_gate_review_for_formal_progression,
)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def require_us_a0_pilot_formal_progression_authority(
    status_document: Mapping[str, object],
    pilot_review_document: Mapping[str, object],
) -> str:
    """Require status-recorded acceptance of the exact PILOT review before FORMAL authority.

    The Gate review has experiment-progression authority only. docs/status.toml remains the sole
    project-stage authority, and the review cannot create Alpha or order authority.
    """

    if _text(status_document.get("current_stage"), "status.current_stage") != "US-A0":
        raise ValueError("FORMAL Agent-value work requires docs/status.toml current_stage=US-A0")
    stages = _mapping(status_document.get("stage"), "status.stage")
    us_a0 = _mapping(stages.get("us_a0"), "status.stage.us_a0")
    if _text(
        us_a0.get("pilot_gate_review_status"),
        "status.stage.us_a0.pilot_gate_review_status",
    ) != "accepted":
        raise ValueError("FORMAL Agent-value work requires accepted PILOT gate review status")
    if us_a0.get("pilot_formal_progression_approved") is not True:
        raise ValueError("FORMAL Agent-value work requires pilot_formal_progression_approved=true")
    expected_review_id = _text(
        us_a0.get("pilot_gate_review_id"),
        "status.stage.us_a0.pilot_gate_review_id",
    )
    return validate_pilot_gate_review_for_formal_progression(
        dict(pilot_review_document),
        expected_review_id=expected_review_id,
    )
