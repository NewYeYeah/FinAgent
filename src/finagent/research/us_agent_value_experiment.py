from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass

from finagent.research.us_agent_value_generation import CandidateGenerationRun
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
)
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import canonical_us_baseline_denominator


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    result = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be integer-like")
    return result


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _float_or_none(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric or null")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class USAgentValuePredecessorBinding:
    us_b0_evidence_graph_id: str
    us_b0_aggregate_report_id: str
    us_b0_run_spec_id: str
    us_b0_denominator_id: str
    us_b0_walk_forward_protocol_id: str
    candidate_count: int
    schema_version: str = "finagent.us-agent-value-predecessor-binding.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "us_b0_evidence_graph_id",
            "us_b0_aggregate_report_id",
            "us_b0_run_spec_id",
            "us_b0_denominator_id",
            "us_b0_walk_forward_protocol_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.candidate_count != 8:
            raise ValueError("US-A0 predecessor must retain the frozen eight-candidate US-B0 denominator")

    @property
    def binding_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-predecessor",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "us_b0_evidence_graph_id": self.us_b0_evidence_graph_id,
            "us_b0_aggregate_report_id": self.us_b0_aggregate_report_id,
            "us_b0_run_spec_id": self.us_b0_run_spec_id,
            "us_b0_denominator_id": self.us_b0_denominator_id,
            "us_b0_walk_forward_protocol_id": self.us_b0_walk_forward_protocol_id,
            "candidate_count": self.candidate_count,
            "authority": "accepted_split_bound_US-B0_predecessor_only",
        }
        if include_id:
            payload["binding_id"] = self.binding_id
        return payload


def bind_us_a0_predecessor(
    document: Mapping[str, object],
    protocol: USAgentValueExperimentProtocol,
) -> USAgentValuePredecessorBinding:
    """Bind A0 to the exact split-bound B0 graph without recomputing B0 statistics."""

    if _text(document.get("schema_version"), "us_b0.schema_version") != (
        "finagent.us-baseline-walk-forward-evidence-graph.v1"
    ):
        raise ValueError("US-A0 requires the split-bound US-B0 evidence graph schema")
    claimed_graph_id = _text(document.get("graph_id"), "us_b0.graph_id")
    graph_payload = dict(document)
    del graph_payload["graph_id"]
    recomputed_graph_id = _canonical_hash(
        graph_payload,
        prefix="us-baseline-walk-forward-evidence",
    )
    if claimed_graph_id != recomputed_graph_id:
        raise ValueError("US-B0 evidence graph content identity mismatch")
    if not _boolean(document.get("passed"), "us_b0.passed"):
        raise ValueError("US-A0 requires a passing US-B0 evidence graph")
    if not _boolean(
        document.get("ready_for_us_a0_candidate"),
        "us_b0.ready_for_us_a0_candidate",
    ):
        raise ValueError("US-B0 evidence is not technically ready for US-A0")
    blockers = document.get("blockers")
    if not isinstance(blockers, list) or blockers:
        raise ValueError("US-A0 requires blocker-free US-B0 evidence")
    for field_name in (
        "status_authority",
        "stage_exit_authority",
        "factor_selection_authority",
        "alpha_authority",
    ):
        if _boolean(document.get(field_name), f"us_b0.{field_name}"):
            raise ValueError(f"US-B0 evidence graph cannot claim {field_name}")

    expected_walk_forward = canonical_us_b0_pilot_walk_forward().protocol_id
    graph_protocol_id = _text(document.get("protocol_id"), "us_b0.protocol_id")
    if graph_protocol_id != expected_walk_forward:
        raise ValueError("US-B0 evidence graph does not bind the canonical pilot walk-forward")
    if protocol.us_b0_walk_forward_protocol_id != graph_protocol_id:
        raise ValueError("US-A0 protocol/US-B0 walk-forward identity mismatch")
    denominator_id = _text(document.get("denominator_id"), "us_b0.denominator_id")
    if denominator_id != canonical_us_baseline_denominator().denominator_id:
        raise ValueError("US-A0 predecessor denominator is not the frozen US-B0 MANUAL denominator")
    candidate_count = _integer(document.get("aggregate_candidate_count"), "us_b0.candidate_count")
    valid_count = _integer(
        document.get("aggregate_valid_candidate_count"),
        "us_b0.valid_candidate_count",
    )
    if candidate_count != 8 or valid_count != candidate_count:
        raise ValueError("US-A0 requires all eight US-B0 predecessor candidates to be valid")
    return USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id=claimed_graph_id,
        us_b0_aggregate_report_id=_text(
            document.get("aggregate_report_id"),
            "us_b0.aggregate_report_id",
        ),
        us_b0_run_spec_id=_text(document.get("run_spec_id"), "us_b0.run_spec_id"),
        us_b0_denominator_id=denominator_id,
        us_b0_walk_forward_protocol_id=graph_protocol_id,
        candidate_count=candidate_count,
    )


@dataclass(frozen=True, slots=True)
class RunEvaluationLink:
    generation_run_id: str
    authoritative_evidence_id: str
    evaluated_candidate_count: int
    valid_candidate_count: int
    best_mean_rank_ic: float | None
    best_worst_fold_rank_ic: float | None
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-agent-value-run-evaluation-link.v1"

    def __post_init__(self) -> None:
        for field_name in ("generation_run_id", "authoritative_evidence_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.evaluated_candidate_count < 0:
            raise ValueError("evaluated_candidate_count must be non-negative")
        if not 0 <= self.valid_candidate_count <= self.evaluated_candidate_count:
            raise ValueError("valid_candidate_count is outside evaluated candidate count")
        for field_name in ("best_mean_rank_ic", "best_worst_fold_rank_ic"):
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite when present")

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def link_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-run-evaluation-link",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "generation_run_id": self.generation_run_id,
            "authoritative_evidence_id": self.authoritative_evidence_id,
            "evaluated_candidate_count": self.evaluated_candidate_count,
            "valid_candidate_count": self.valid_candidate_count,
            "best_mean_rank_ic": self.best_mean_rank_ic,
            "best_worst_fold_rank_ic": self.best_worst_fold_rank_ic,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "metric_authority": "copied_from_authoritative_split_bound_evidence_not_recomputed_here",
        }
        if include_id:
            payload["link_id"] = self.link_id
        return payload


@dataclass(frozen=True, slots=True)
class SearchArmResult:
    protocol_id: str
    phase: USAgentValuePhase
    arm: USAgentValueArm
    generation_runs: tuple[CandidateGenerationRun, ...]
    evaluation_links: tuple[RunEvaluationLink, ...]
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.search-arm-result.v1"

    def __post_init__(self) -> None:
        if not self.protocol_id.strip():
            raise ValueError("arm result protocol_id must be non-empty")
        if not self.generation_runs:
            raise ValueError("arm result requires generation runs")
        run_ids = tuple(run.run_id for run in self.generation_runs)
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("arm result generation run identities must be unique")
        if any(run.spec.protocol_id != self.protocol_id for run in self.generation_runs):
            raise ValueError("arm result run/protocol identity mismatch")
        if any(run.spec.phase is not self.phase for run in self.generation_runs):
            raise ValueError("arm result run phase mismatch")
        if any(run.spec.arm is not self.arm for run in self.generation_runs):
            raise ValueError("arm result contains another search arm")
        if len(self.evaluation_links) != len(self.generation_runs):
            raise ValueError("arm result requires one evaluation link per independent generation run")
        link_run_ids = tuple(link.generation_run_id for link in self.evaluation_links)
        if link_run_ids != run_ids:
            raise ValueError("evaluation links must preserve generation run order and identity")
        if len({run.spec.run_ordinal for run in self.generation_runs}) != len(self.generation_runs):
            raise ValueError("independent run ordinals must be unique within an arm")

    @property
    def passed(self) -> bool:
        return not self.blockers and all(link.passed for link in self.evaluation_links)

    @property
    def accepted_candidate_count(self) -> int:
        return sum(len(run.accepted_candidates) for run in self.generation_runs)

    @property
    def invalid_slot_count(self) -> int:
        return sum(run.invalid_slot_count for run in self.generation_runs)

    @property
    def duplicate_slot_count(self) -> int:
        return sum(run.duplicate_slot_count for run in self.generation_runs)

    @property
    def repair_count(self) -> int:
        return sum(run.repair_count for run in self.generation_runs)

    @property
    def trial_count(self) -> int:
        return sum(run.spec.candidate_budget for run in self.generation_runs)

    @property
    def valid_candidate_rate(self) -> float:
        return self.accepted_candidate_count / self.trial_count

    @property
    def invalid_rate(self) -> float:
        return self.invalid_slot_count / self.trial_count

    @property
    def duplicate_rate(self) -> float:
        return self.duplicate_slot_count / self.trial_count

    @property
    def result_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-search-arm-result",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        total_usage = {
            "llm_calls": sum(run.usage.llm_calls for run in self.generation_runs),
            "input_tokens": sum(run.usage.input_tokens for run in self.generation_runs),
            "output_tokens": sum(run.usage.output_tokens for run in self.generation_runs),
            "total_tokens": sum(run.usage.total_tokens for run in self.generation_runs),
            "latency_ms": sum(run.usage.latency_ms for run in self.generation_runs),
            "cost_usd": sum(run.usage.cost_usd for run in self.generation_runs),
        }
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "phase": self.phase.value,
            "arm": self.arm.value,
            "independent_run_count": len(self.generation_runs),
            "generation_run_ids": [run.run_id for run in self.generation_runs],
            "generation_run_spec_ids": [run.spec.run_spec_id for run in self.generation_runs],
            "evaluation_link_ids": [link.link_id for link in self.evaluation_links],
            "trial_count": self.trial_count,
            "accepted_candidate_count": self.accepted_candidate_count,
            "invalid_slot_count": self.invalid_slot_count,
            "duplicate_slot_count": self.duplicate_slot_count,
            "repair_count": self.repair_count,
            "replacement_count": 0,
            "valid_candidate_rate": self.valid_candidate_rate,
            "invalid_rate": self.invalid_rate,
            "duplicate_rate": self.duplicate_rate,
            "usage": total_usage,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "evaluation_links": [link.to_dict() for link in self.evaluation_links],
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["result_id"] = self.result_id
        return payload


def build_search_arm_result(
    protocol: USAgentValueExperimentProtocol,
    arm: USAgentValueArm,
    generation_runs: tuple[CandidateGenerationRun, ...],
    evaluation_links: tuple[RunEvaluationLink, ...],
) -> SearchArmResult:
    if len(generation_runs) < protocol.minimum_runs(arm):
        raise ValueError(f"{arm.value} does not satisfy the frozen independent-run requirement")
    if protocol.phase is USAgentValuePhase.FORMAL and arm is USAgentValueArm.PROGRAMMATIC:
        seeds = tuple(run.spec.random_seed for run in generation_runs)
        if None in seeds or len(seeds) != len(set(seeds)):
            raise ValueError("FORMAL PROGRAMMATIC runs require distinct recorded seeds")
    return SearchArmResult(
        protocol_id=protocol.protocol_id,
        phase=protocol.phase,
        arm=arm,
        generation_runs=generation_runs,
        evaluation_links=evaluation_links,
    )


@dataclass(frozen=True, slots=True)
class AgentValueExperiment:
    protocol: USAgentValueExperimentProtocol
    predecessor: USAgentValuePredecessorBinding
    arm_results: tuple[SearchArmResult, ...]
    schema_version: str = "finagent.agent-value-experiment.v1"

    def __post_init__(self) -> None:
        if self.predecessor.us_b0_walk_forward_protocol_id != (
            self.protocol.us_b0_walk_forward_protocol_id
        ):
            raise ValueError("Agent-value experiment/predecessor walk-forward identity mismatch")
        if tuple(result.arm for result in self.arm_results) != self.protocol.arms:
            raise ValueError("Agent-value experiment must contain MANUAL/PROGRAMMATIC/AGENT results in order")
        if any(result.protocol_id != self.protocol.protocol_id for result in self.arm_results):
            raise ValueError("Agent-value arm result/protocol identity mismatch")
        for result in self.arm_results:
            if len(result.generation_runs) < self.protocol.minimum_runs(result.arm):
                raise ValueError("Agent-value experiment does not satisfy independent-run requirements")

    @property
    def evidence_complete(self) -> bool:
        return all(result.passed for result in self.arm_results)

    @property
    def ready_for_agent_value_gate_review(self) -> bool:
        return self.evidence_complete

    @property
    def experiment_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-experiment",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol": self.protocol.to_dict(),
            "predecessor": self.predecessor.to_dict(),
            "arm_result_ids": [result.result_id for result in self.arm_results],
            "arm_results": [result.to_dict() for result in self.arm_results],
            "evidence_complete": self.evidence_complete,
            "ready_for_agent_value_gate_review": self.ready_for_agent_value_gate_review,
            "agent_value_gate_decision": "UNDECIDED_REQUIRES_SEPARATE_REVIEW",
            "comparison_scope": (
                "generation_efficiency_novelty_and_authoritative_split_bound_quality_evidence"
            ),
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["experiment_id"] = self.experiment_id
        return payload
