from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from finagent.research.us_agent_value_experiment import AgentValueExperiment
from finagent.research.us_agent_value_gate import USAgentValueGateReview
from finagent.research.us_r1_protocol import (
    USR1CandidateDenominator,
    build_us_r1_candidate_denominator,
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


@dataclass(frozen=True, slots=True)
class USR1StageAuthority:
    a0_terminal_gate_review_id: str
    a0_experiment_id: str
    a0_evidence_graph_id: str
    schema_version: str = "finagent.us-r1-stage-authority.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "a0_terminal_gate_review_id",
            "a0_experiment_id",
            "a0_evidence_graph_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)


def require_us_r1_stage_authority(
    status_document: Mapping[str, object],
) -> USR1StageAuthority:
    if _text(status_document.get("current_stage"), "status.current_stage") != "US-R1":
        raise ValueError("formal US-R1 execution requires docs/status.toml current_stage=US-R1")
    stages = _mapping(status_document.get("stage"), "status.stage")
    us_a0 = _mapping(stages.get("us_a0"), "status.stage.us_a0")
    if _text(us_a0.get("status"), "status.stage.us_a0.status") != "accepted":
        raise ValueError("formal US-R1 execution requires accepted US-A0 stage authority")
    if us_a0.get("stage_exit_gate_passed") is not True:
        raise ValueError("formal US-R1 execution requires US-A0 stage_exit_gate_passed=true")
    return USR1StageAuthority(
        a0_terminal_gate_review_id=_text(
            us_a0.get("terminal_gate_review_id"),
            "status.stage.us_a0.terminal_gate_review_id",
        ),
        a0_experiment_id=_text(
            us_a0.get("experiment_id"),
            "status.stage.us_a0.experiment_id",
        ),
        a0_evidence_graph_id=_text(
            us_a0.get("evidence_graph_id"),
            "status.stage.us_a0.evidence_graph_id",
        ),
    )


def bind_authorized_us_r1_candidate_denominator(
    status_document: Mapping[str, object],
    experiment: AgentValueExperiment,
    review: USAgentValueGateReview,
) -> USR1CandidateDenominator:
    authority = require_us_r1_stage_authority(status_document)
    if review.review_id != authority.a0_terminal_gate_review_id:
        raise ValueError("A0 Gate review identity does not match US-R1 stage authority")
    if experiment.experiment_id != authority.a0_experiment_id:
        raise ValueError("A0 experiment identity does not match US-R1 stage authority")
    if review.assessment.evidence_graph_id != authority.a0_evidence_graph_id:
        raise ValueError("A0 evidence graph identity does not match US-R1 stage authority")
    return build_us_r1_candidate_denominator(experiment, review)
