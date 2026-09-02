from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from finagent.research.us_agent_value_experiment import (
    USAgentValuePredecessorBinding,
    bind_us_a0_predecessor,
)
from finagent.research.us_agent_value_protocol import USAgentValueExperimentProtocol


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


@dataclass(frozen=True, slots=True)
class USAgentValueStageAuthority:
    us_b0_evidence_graph_id: str
    us_b0_aggregate_report_id: str
    schema_version: str = "finagent.us-agent-value-stage-authority.v1"

    def __post_init__(self) -> None:
        for field_name in ("us_b0_evidence_graph_id", "us_b0_aggregate_report_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)


def require_us_a0_stage_authority(
    status_document: Mapping[str, object],
) -> USAgentValueStageAuthority:
    """Require the sole project-stage authority to have explicitly accepted US-B0.

    A content hash proves identity, not acceptance. Formal A0 execution must therefore bind
    the B0 graph/report IDs recorded in docs/status.toml after human review.
    """

    if _text(status_document.get("current_stage"), "status.current_stage") != "US-A0":
        raise ValueError("formal US-A0 execution requires docs/status.toml current_stage=US-A0")
    stages = _mapping(status_document.get("stage"), "status.stage")
    us_b0 = _mapping(stages.get("us_b0"), "status.stage.us_b0")
    if _text(us_b0.get("status"), "status.stage.us_b0.status") != "accepted":
        raise ValueError("formal US-A0 execution requires accepted US-B0 stage authority")
    if us_b0.get("stage_exit_gate_passed") is not True:
        raise ValueError("formal US-A0 execution requires US-B0 stage_exit_gate_passed=true")
    return USAgentValueStageAuthority(
        us_b0_evidence_graph_id=_text(
            us_b0.get("walk_forward_evidence_graph_id"),
            "status.stage.us_b0.walk_forward_evidence_graph_id",
        ),
        us_b0_aggregate_report_id=_text(
            us_b0.get("walk_forward_aggregate_report_id"),
            "status.stage.us_b0.walk_forward_aggregate_report_id",
        ),
    )


def bind_authorized_us_a0_predecessor(
    status_document: Mapping[str, object],
    evidence_graph_document: Mapping[str, object],
    protocol: USAgentValueExperimentProtocol,
) -> USAgentValuePredecessorBinding:
    authority = require_us_a0_stage_authority(status_document)
    binding = bind_us_a0_predecessor(evidence_graph_document, protocol)
    if binding.us_b0_evidence_graph_id != authority.us_b0_evidence_graph_id:
        raise ValueError("US-B0 graph identity does not match project-stage authority")
    if binding.us_b0_aggregate_report_id != authority.us_b0_aggregate_report_id:
        raise ValueError("US-B0 aggregate identity does not match project-stage authority")
    return binding
