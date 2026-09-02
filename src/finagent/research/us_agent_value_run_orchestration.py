from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from finagent.research.us_agent_value_assembly import ParsedUSAgentValueRunEvidence
from finagent.research.us_agent_value_execution import USAgentValueExecutionPlan
from finagent.research.us_agent_value_experiment import USAgentValuePredecessorBinding
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationCheckpoint,
    USAgentValuePilotOrchestrationState,
    advance_us_a0_pilot_orchestration_checkpoint,
)
from finagent.research.us_agent_value_protocol import USAgentValueArm


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


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


@dataclass(frozen=True, slots=True)
class USAgentValuePilotCommittedRun:
    run_order: int
    arm: USAgentValueArm
    run_spec_id: str
    generation_run_id: str
    run_evidence_manifest_id: str
    run_evaluation_report_id: str
    run_evaluation_link_id: str
    schema_version: str = "finagent.us-agent-value-pilot-committed-run.v1"

    def __post_init__(self) -> None:
        if self.run_order not in (1, 2, 3):
            raise ValueError("PILOT committed run_order must be 1, 2 or 3")
        for field_name in (
            "run_spec_id",
            "generation_run_id",
            "run_evidence_manifest_id",
            "run_evaluation_report_id",
            "run_evaluation_link_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)

    @property
    def commit_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-pilot-run-commit",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_order": self.run_order,
            "arm": self.arm.value,
            "run_spec_id": self.run_spec_id,
            "generation_run_id": self.generation_run_id,
            "run_evidence_manifest_id": self.run_evidence_manifest_id,
            "run_evaluation_report_id": self.run_evaluation_report_id,
            "run_evaluation_link_id": self.run_evaluation_link_id,
            "technical_passed": True,
            "commit_semantics": "validated_authoritative_run_evidence_never_overwrite",
        }
        if include_id:
            payload["commit_id"] = self.commit_id
        return payload


@dataclass(frozen=True, slots=True)
class USAgentValuePilotRunProgress:
    launch_bundle_id: str
    runtime_policy_id: str
    execution_plan_id: str
    agent_generated_checkpoint_id: str
    predecessor_binding_id: str
    completed_runs: tuple[USAgentValuePilotCommittedRun, ...]
    previous_progress_id: str | None = None
    schema_version: str = "finagent.us-agent-value-pilot-run-progress.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "launch_bundle_id",
            "runtime_policy_id",
            "execution_plan_id",
            "agent_generated_checkpoint_id",
            "predecessor_binding_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if not 1 <= len(self.completed_runs) <= 3:
            raise ValueError("PILOT run progress must contain 1..3 completed runs")
        if tuple(item.run_order for item in self.completed_runs) != tuple(
            range(1, len(self.completed_runs) + 1)
        ):
            raise ValueError("PILOT completed runs must form an ordered prefix from run 1")
        for values in (
            tuple(item.commit_id for item in self.completed_runs),
            tuple(item.run_spec_id for item in self.completed_runs),
            tuple(item.generation_run_id for item in self.completed_runs),
            tuple(item.run_evidence_manifest_id for item in self.completed_runs),
        ):
            if len(values) != len(set(values)):
                raise ValueError("PILOT run progress identities must be unique")
        if len(self.completed_runs) == 1:
            if self.previous_progress_id is not None:
                raise ValueError("first PILOT run progress cannot have previous_progress_id")
        elif self.previous_progress_id is None or not self.previous_progress_id.strip():
            raise ValueError("advanced PILOT run progress requires previous_progress_id")

    @property
    def progress_ordinal(self) -> int:
        return len(self.completed_runs)

    @property
    def progress_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-pilot-run-progress",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "progress_ordinal": self.progress_ordinal,
            "launch_bundle_id": self.launch_bundle_id,
            "runtime_policy_id": self.runtime_policy_id,
            "execution_plan_id": self.execution_plan_id,
            "agent_generated_checkpoint_id": self.agent_generated_checkpoint_id,
            "predecessor_binding_id": self.predecessor_binding_id,
            "previous_progress_id": self.previous_progress_id,
            "completed_run_ids": [item.generation_run_id for item in self.completed_runs],
            "completed_run_manifest_ids": [
                item.run_evidence_manifest_id for item in self.completed_runs
            ],
            "completed_runs": [item.to_dict() for item in self.completed_runs],
            "resume_semantics": "ordered_prefix_resume_without_replacing_committed_run_evidence",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["progress_id"] = self.progress_id
        return payload


@dataclass(frozen=True, slots=True)
class USAgentValuePilotRunPromotionIntent:
    execution_plan_id: str
    run_spec_id: str
    generation_run_id: str
    run_evidence_manifest_id: str
    run_evaluation_report_id: str
    run_evaluation_link_id: str
    schema_version: str = "finagent.us-agent-value-pilot-run-promotion-intent.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_plan_id",
            "run_spec_id",
            "generation_run_id",
            "run_evidence_manifest_id",
            "run_evaluation_report_id",
            "run_evaluation_link_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)

    @property
    def intent_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-pilot-run-promotion",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "run_spec_id": self.run_spec_id,
            "generation_run_id": self.generation_run_id,
            "run_evidence_manifest_id": self.run_evidence_manifest_id,
            "run_evaluation_report_id": self.run_evaluation_report_id,
            "run_evaluation_link_id": self.run_evaluation_link_id,
            "promotion_semantics": "staged_evidence_validated_before_canonical_commit",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["intent_id"] = self.intent_id
        return payload


def committed_run_from_parsed_evidence(
    parsed: ParsedUSAgentValueRunEvidence,
    *,
    run_order: int,
) -> USAgentValuePilotCommittedRun:
    return USAgentValuePilotCommittedRun(
        run_order=run_order,
        arm=parsed.generation_run.spec.arm,
        run_spec_id=parsed.run_spec_id,
        generation_run_id=parsed.run_id,
        run_evidence_manifest_id=parsed.run_evidence_manifest_id,
        run_evaluation_report_id=parsed.run_evaluation_report_id,
        run_evaluation_link_id=parsed.evaluation_link.link_id,
    )


def promotion_intent_from_parsed_evidence(
    parsed: ParsedUSAgentValueRunEvidence,
    *,
    execution_plan: USAgentValueExecutionPlan,
) -> USAgentValuePilotRunPromotionIntent:
    return USAgentValuePilotRunPromotionIntent(
        execution_plan_id=execution_plan.plan_id,
        run_spec_id=parsed.run_spec_id,
        generation_run_id=parsed.run_id,
        run_evidence_manifest_id=parsed.run_evidence_manifest_id,
        run_evaluation_report_id=parsed.run_evaluation_report_id,
        run_evaluation_link_id=parsed.evaluation_link.link_id,
    )


def advance_us_a0_pilot_run_progress(
    *,
    previous: USAgentValuePilotRunProgress | None,
    execution_plan: USAgentValueExecutionPlan,
    agent_checkpoint: USAgentValuePilotOrchestrationCheckpoint,
    predecessor: USAgentValuePredecessorBinding,
    parsed_run: ParsedUSAgentValueRunEvidence,
) -> USAgentValuePilotRunProgress:
    if agent_checkpoint.state is not USAgentValuePilotOrchestrationState.AGENT_GENERATED:
        raise ValueError("PILOT run evidence requires AGENT_GENERATED orchestration checkpoint")
    if agent_checkpoint.execution_plan_id != execution_plan.plan_id:
        raise ValueError("PILOT run progress execution-plan/checkpoint identity mismatch")
    if parsed_run.predecessor_binding_id != predecessor.binding_id:
        raise ValueError("PILOT run progress predecessor identity mismatch")
    completed = () if previous is None else previous.completed_runs
    next_order = len(completed) + 1
    if next_order > len(execution_plan.run_specs):
        raise ValueError("PILOT run progress is already complete")
    expected_spec = execution_plan.run_specs[next_order - 1]
    if parsed_run.run_spec_id != expected_spec.run_spec_id:
        raise ValueError("PILOT run evidence must commit in exact ExecutionPlan run order")
    if parsed_run.generation_run.spec != expected_spec:
        raise ValueError("PILOT run evidence generation spec differs from ExecutionPlan")

    if previous is not None:
        if previous.launch_bundle_id != agent_checkpoint.launch_bundle_id:
            raise ValueError("PILOT run progress launch identity drift")
        if previous.runtime_policy_id != agent_checkpoint.runtime_policy_id:
            raise ValueError("PILOT run progress runtime-policy identity drift")
        if previous.execution_plan_id != execution_plan.plan_id:
            raise ValueError("PILOT run progress execution-plan identity drift")
        if previous.agent_generated_checkpoint_id != agent_checkpoint.checkpoint_id:
            raise ValueError("PILOT run progress Agent checkpoint identity drift")
        if previous.predecessor_binding_id != predecessor.binding_id:
            raise ValueError("PILOT run progress predecessor identity drift")

    committed = committed_run_from_parsed_evidence(parsed_run, run_order=next_order)
    return USAgentValuePilotRunProgress(
        launch_bundle_id=agent_checkpoint.launch_bundle_id,
        runtime_policy_id=agent_checkpoint.runtime_policy_id,
        execution_plan_id=execution_plan.plan_id,
        agent_generated_checkpoint_id=agent_checkpoint.checkpoint_id,
        predecessor_binding_id=predecessor.binding_id,
        completed_runs=(*completed, committed),
        previous_progress_id=(None if previous is None else previous.progress_id),
    )


def build_run_evidence_complete_checkpoint(
    *,
    agent_checkpoint: USAgentValuePilotOrchestrationCheckpoint,
    execution_plan: USAgentValueExecutionPlan,
    progress: USAgentValuePilotRunProgress,
) -> USAgentValuePilotOrchestrationCheckpoint:
    if len(progress.completed_runs) != len(execution_plan.run_specs) or len(progress.completed_runs) != 3:
        raise ValueError("PILOT RUN_EVIDENCE_COMPLETE requires all three planned runs")
    if progress.agent_generated_checkpoint_id != agent_checkpoint.checkpoint_id:
        raise ValueError("PILOT completed run progress does not descend from Agent checkpoint")
    expected_specs = tuple(spec.run_spec_id for spec in execution_plan.run_specs)
    if tuple(item.run_spec_id for item in progress.completed_runs) != expected_specs:
        raise ValueError("PILOT completed run progress differs from ExecutionPlan order")
    return advance_us_a0_pilot_orchestration_checkpoint(
        agent_checkpoint,
        state=USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE,
        run_evidence_manifest_ids=tuple(
            item.run_evidence_manifest_id for item in progress.completed_runs
        ),
    )


def parse_us_a0_pilot_committed_run(document: Mapping[str, object]) -> USAgentValuePilotCommittedRun:
    committed = USAgentValuePilotCommittedRun(
        run_order=_integer(document.get("run_order"), "committed_run.run_order"),
        arm=USAgentValueArm(_text(document.get("arm"), "committed_run.arm")),
        run_spec_id=_text(document.get("run_spec_id"), "committed_run.run_spec_id"),
        generation_run_id=_text(
            document.get("generation_run_id"), "committed_run.generation_run_id"
        ),
        run_evidence_manifest_id=_text(
            document.get("run_evidence_manifest_id"),
            "committed_run.run_evidence_manifest_id",
        ),
        run_evaluation_report_id=_text(
            document.get("run_evaluation_report_id"),
            "committed_run.run_evaluation_report_id",
        ),
        run_evaluation_link_id=_text(
            document.get("run_evaluation_link_id"),
            "committed_run.run_evaluation_link_id",
        ),
    )
    if dict(document) != committed.to_dict():
        raise ValueError("US-A0 PILOT committed-run content identity mismatch")
    return committed


def parse_us_a0_pilot_run_progress(document: Mapping[str, object]) -> USAgentValuePilotRunProgress:
    raw_completed = _sequence(document.get("completed_runs"), "run_progress.completed_runs")
    progress = USAgentValuePilotRunProgress(
        launch_bundle_id=_text(document.get("launch_bundle_id"), "run_progress.launch_bundle_id"),
        runtime_policy_id=_text(document.get("runtime_policy_id"), "run_progress.runtime_policy_id"),
        execution_plan_id=_text(
            document.get("execution_plan_id"), "run_progress.execution_plan_id"
        ),
        agent_generated_checkpoint_id=_text(
            document.get("agent_generated_checkpoint_id"),
            "run_progress.agent_generated_checkpoint_id",
        ),
        predecessor_binding_id=_text(
            document.get("predecessor_binding_id"),
            "run_progress.predecessor_binding_id",
        ),
        completed_runs=tuple(
            parse_us_a0_pilot_committed_run(item)
            for item in raw_completed
            if isinstance(item, Mapping)
        ),
        previous_progress_id=_optional_text(
            document.get("previous_progress_id"), "run_progress.previous_progress_id"
        ),
    )
    if len(progress.completed_runs) != len(raw_completed):
        raise TypeError("run_progress.completed_runs must contain mappings")
    if dict(document) != progress.to_dict():
        raise ValueError("US-A0 PILOT run-progress content identity mismatch")
    return progress


def parse_us_a0_pilot_run_promotion_intent(
    document: Mapping[str, object],
) -> USAgentValuePilotRunPromotionIntent:
    intent = USAgentValuePilotRunPromotionIntent(
        execution_plan_id=_text(
            document.get("execution_plan_id"), "promotion.execution_plan_id"
        ),
        run_spec_id=_text(document.get("run_spec_id"), "promotion.run_spec_id"),
        generation_run_id=_text(
            document.get("generation_run_id"), "promotion.generation_run_id"
        ),
        run_evidence_manifest_id=_text(
            document.get("run_evidence_manifest_id"),
            "promotion.run_evidence_manifest_id",
        ),
        run_evaluation_report_id=_text(
            document.get("run_evaluation_report_id"),
            "promotion.run_evaluation_report_id",
        ),
        run_evaluation_link_id=_text(
            document.get("run_evaluation_link_id"),
            "promotion.run_evaluation_link_id",
        ),
    )
    if dict(document) != intent.to_dict():
        raise ValueError("US-A0 PILOT promotion-intent content identity mismatch")
    return intent
