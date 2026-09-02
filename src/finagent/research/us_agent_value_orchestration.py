from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from finagent.research.us_agent_value_launch import USAgentValuePilotLaunchBundle
from finagent.research.us_agent_value_runtime import USAgentValueDeepSeekRuntimePolicy


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


class USAgentValuePilotOrchestrationState(StrEnum):
    PREPARED = "PREPARED"
    AGENT_GENERATED = "AGENT_GENERATED"
    RUN_EVIDENCE_COMPLETE = "RUN_EVIDENCE_COMPLETE"
    EXPERIMENT_ASSEMBLED = "EXPERIMENT_ASSEMBLED"
    GATE_REVIEWED = "GATE_REVIEWED"


_STATE_ORDINAL = {
    USAgentValuePilotOrchestrationState.PREPARED: 0,
    USAgentValuePilotOrchestrationState.AGENT_GENERATED: 1,
    USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE: 2,
    USAgentValuePilotOrchestrationState.EXPERIMENT_ASSEMBLED: 3,
    USAgentValuePilotOrchestrationState.GATE_REVIEWED: 4,
}


@dataclass(frozen=True, slots=True)
class USAgentValuePilotOrchestrationCheckpoint:
    launch_bundle_id: str
    runtime_policy_id: str
    execution_plan_id: str
    agent_run_spec_id: str
    state: USAgentValuePilotOrchestrationState
    checkpoint_ordinal: int
    previous_checkpoint_id: str | None = None
    agent_generation_run_id: str | None = None
    run_evidence_manifest_ids: tuple[str, ...] = ()
    experiment_evidence_graph_id: str | None = None
    gate_review_id: str | None = None
    schema_version: str = "finagent.us-agent-value-pilot-orchestration-checkpoint.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "launch_bundle_id",
            "runtime_policy_id",
            "execution_plan_id",
            "agent_run_spec_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.checkpoint_ordinal != _STATE_ORDINAL[self.state]:
            raise ValueError("PILOT checkpoint ordinal/state mismatch")
        if self.previous_checkpoint_id is not None and not self.previous_checkpoint_id.strip():
            raise ValueError("previous_checkpoint_id must be non-empty when present")
        if self.agent_generation_run_id is not None and not self.agent_generation_run_id.strip():
            raise ValueError("agent_generation_run_id must be non-empty when present")
        if any(not value.strip() for value in self.run_evidence_manifest_ids):
            raise ValueError("run evidence manifest IDs must be non-empty")
        if len(self.run_evidence_manifest_ids) != len(set(self.run_evidence_manifest_ids)):
            raise ValueError("run evidence manifest IDs must be unique")
        if self.experiment_evidence_graph_id is not None and not self.experiment_evidence_graph_id.strip():
            raise ValueError("experiment_evidence_graph_id must be non-empty when present")
        if self.gate_review_id is not None and not self.gate_review_id.strip():
            raise ValueError("gate_review_id must be non-empty when present")

        if self.state is USAgentValuePilotOrchestrationState.PREPARED:
            if self.previous_checkpoint_id is not None:
                raise ValueError("PREPARED checkpoint cannot have a predecessor")
            if any(
                (
                    self.agent_generation_run_id is not None,
                    bool(self.run_evidence_manifest_ids),
                    self.experiment_evidence_graph_id is not None,
                    self.gate_review_id is not None,
                )
            ):
                raise ValueError("PREPARED checkpoint cannot contain result evidence")
        else:
            if self.previous_checkpoint_id is None:
                raise ValueError("advanced PILOT checkpoint requires previous_checkpoint_id")
            if self.agent_generation_run_id is None:
                raise ValueError("advanced PILOT checkpoint requires fixed AGENT generation-run ID")

        if self.state is USAgentValuePilotOrchestrationState.AGENT_GENERATED:
            if self.run_evidence_manifest_ids or self.experiment_evidence_graph_id or self.gate_review_id:
                raise ValueError("AGENT_GENERATED checkpoint cannot contain later evidence")
        elif self.state is USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE:
            if len(self.run_evidence_manifest_ids) != 3:
                raise ValueError("PILOT requires exactly three run evidence manifests")
            if self.experiment_evidence_graph_id is not None or self.gate_review_id is not None:
                raise ValueError("RUN_EVIDENCE_COMPLETE cannot contain experiment/Gate evidence")
        elif self.state is USAgentValuePilotOrchestrationState.EXPERIMENT_ASSEMBLED:
            if len(self.run_evidence_manifest_ids) != 3:
                raise ValueError("EXPERIMENT_ASSEMBLED requires the three frozen run manifests")
            if self.experiment_evidence_graph_id is None:
                raise ValueError("EXPERIMENT_ASSEMBLED requires experiment evidence graph")
            if self.gate_review_id is not None:
                raise ValueError("EXPERIMENT_ASSEMBLED cannot contain Gate review")
        elif self.state is USAgentValuePilotOrchestrationState.GATE_REVIEWED:
            if len(self.run_evidence_manifest_ids) != 3:
                raise ValueError("GATE_REVIEWED requires the three frozen run manifests")
            if self.experiment_evidence_graph_id is None or self.gate_review_id is None:
                raise ValueError("GATE_REVIEWED requires experiment graph and Gate review")

    @property
    def checkpoint_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-pilot-checkpoint",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "launch_bundle_id": self.launch_bundle_id,
            "runtime_policy_id": self.runtime_policy_id,
            "execution_plan_id": self.execution_plan_id,
            "agent_run_spec_id": self.agent_run_spec_id,
            "state": self.state.value,
            "checkpoint_ordinal": self.checkpoint_ordinal,
            "previous_checkpoint_id": self.previous_checkpoint_id,
            "agent_generation_run_id": self.agent_generation_run_id,
            "run_evidence_manifest_ids": list(self.run_evidence_manifest_ids),
            "experiment_evidence_graph_id": self.experiment_evidence_graph_id,
            "gate_review_id": self.gate_review_id,
            "resume_semantics": "reuse_existing_frozen_evidence_never_rerun_to_cherry_pick",
            "mutation_semantics": "append_only_checkpoint_chain",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["checkpoint_id"] = self.checkpoint_id
        return payload


def prepare_us_a0_pilot_orchestration_checkpoint(
    launch_bundle: USAgentValuePilotLaunchBundle,
    runtime_policy: USAgentValueDeepSeekRuntimePolicy,
) -> USAgentValuePilotOrchestrationCheckpoint:
    if runtime_policy.launch_bundle_id != launch_bundle.launch_bundle_id:
        raise ValueError("orchestration runtime-policy/launch identity mismatch")
    if runtime_policy.execution_plan_id != launch_bundle.execution_plan_id:
        raise ValueError("orchestration runtime-policy/execution-plan identity mismatch")
    if len(launch_bundle.agent_run_spec_ids) != 1:
        raise ValueError("PILOT orchestration requires one AGENT run spec")
    return USAgentValuePilotOrchestrationCheckpoint(
        launch_bundle_id=launch_bundle.launch_bundle_id,
        runtime_policy_id=runtime_policy.runtime_policy_id,
        execution_plan_id=launch_bundle.execution_plan_id,
        agent_run_spec_id=launch_bundle.agent_run_spec_ids[0],
        state=USAgentValuePilotOrchestrationState.PREPARED,
        checkpoint_ordinal=0,
    )


def advance_us_a0_pilot_orchestration_checkpoint(
    previous: USAgentValuePilotOrchestrationCheckpoint,
    *,
    state: USAgentValuePilotOrchestrationState,
    agent_generation_run_id: str | None = None,
    run_evidence_manifest_ids: tuple[str, ...] | None = None,
    experiment_evidence_graph_id: str | None = None,
    gate_review_id: str | None = None,
) -> USAgentValuePilotOrchestrationCheckpoint:
    expected_ordinal = previous.checkpoint_ordinal + 1
    if _STATE_ORDINAL[state] != expected_ordinal:
        raise ValueError("PILOT orchestration transitions must advance exactly one state")
    fixed_agent_run = previous.agent_generation_run_id
    if fixed_agent_run is not None:
        if agent_generation_run_id is not None and agent_generation_run_id != fixed_agent_run:
            raise ValueError("PILOT orchestration cannot replace a frozen AGENT generation run")
        agent_generation_run_id = fixed_agent_run
    if agent_generation_run_id is None:
        raise ValueError("PILOT orchestration transition requires AGENT generation-run identity")

    fixed_manifests = previous.run_evidence_manifest_ids
    if fixed_manifests:
        if run_evidence_manifest_ids is not None and run_evidence_manifest_ids != fixed_manifests:
            raise ValueError("PILOT orchestration cannot replace frozen run evidence manifests")
        run_evidence_manifest_ids = fixed_manifests
    if run_evidence_manifest_ids is None:
        run_evidence_manifest_ids = ()

    fixed_graph = previous.experiment_evidence_graph_id
    if fixed_graph is not None:
        if experiment_evidence_graph_id is not None and experiment_evidence_graph_id != fixed_graph:
            raise ValueError("PILOT orchestration cannot replace frozen experiment evidence graph")
        experiment_evidence_graph_id = fixed_graph

    fixed_review = previous.gate_review_id
    if fixed_review is not None:
        if gate_review_id is not None and gate_review_id != fixed_review:
            raise ValueError("PILOT orchestration cannot replace frozen Gate review")
        gate_review_id = fixed_review

    return USAgentValuePilotOrchestrationCheckpoint(
        launch_bundle_id=previous.launch_bundle_id,
        runtime_policy_id=previous.runtime_policy_id,
        execution_plan_id=previous.execution_plan_id,
        agent_run_spec_id=previous.agent_run_spec_id,
        state=state,
        checkpoint_ordinal=expected_ordinal,
        previous_checkpoint_id=previous.checkpoint_id,
        agent_generation_run_id=agent_generation_run_id,
        run_evidence_manifest_ids=run_evidence_manifest_ids,
        experiment_evidence_graph_id=experiment_evidence_graph_id,
        gate_review_id=gate_review_id,
    )


def parse_us_a0_pilot_orchestration_checkpoint(
    document: Mapping[str, object],
) -> USAgentValuePilotOrchestrationCheckpoint:
    raw_manifests = document.get("run_evidence_manifest_ids")
    if not isinstance(raw_manifests, list) or any(not isinstance(value, str) for value in raw_manifests):
        raise TypeError("checkpoint.run_evidence_manifest_ids must be a list of strings")
    raw_ordinal = document.get("checkpoint_ordinal")
    if isinstance(raw_ordinal, bool) or not isinstance(raw_ordinal, int):
        raise TypeError("checkpoint.checkpoint_ordinal must be an integer")
    checkpoint = USAgentValuePilotOrchestrationCheckpoint(
        launch_bundle_id=_text(document.get("launch_bundle_id"), "checkpoint.launch_bundle_id"),
        runtime_policy_id=_text(document.get("runtime_policy_id"), "checkpoint.runtime_policy_id"),
        execution_plan_id=_text(document.get("execution_plan_id"), "checkpoint.execution_plan_id"),
        agent_run_spec_id=_text(document.get("agent_run_spec_id"), "checkpoint.agent_run_spec_id"),
        state=USAgentValuePilotOrchestrationState(
            _text(document.get("state"), "checkpoint.state")
        ),
        checkpoint_ordinal=raw_ordinal,
        previous_checkpoint_id=_optional_text(
            document.get("previous_checkpoint_id"), "checkpoint.previous_checkpoint_id"
        ),
        agent_generation_run_id=_optional_text(
            document.get("agent_generation_run_id"), "checkpoint.agent_generation_run_id"
        ),
        run_evidence_manifest_ids=tuple(raw_manifests),
        experiment_evidence_graph_id=_optional_text(
            document.get("experiment_evidence_graph_id"),
            "checkpoint.experiment_evidence_graph_id",
        ),
        gate_review_id=_optional_text(document.get("gate_review_id"), "checkpoint.gate_review_id"),
    )
    if dict(document) != checkpoint.to_dict():
        raise ValueError("US-A0 PILOT orchestration checkpoint content identity mismatch")
    return checkpoint
