from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from finagent.agents.providers import LLMProfile
from finagent.research.us_agent_value_formal_launch import USAgentValueFormalLaunchArtifacts
from finagent.research.us_agent_value_protocol import USAgentValuePhase
from finagent.research.us_agent_value_runtime import (
    DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
    DEEPSEEK_V4_MAX_OUTPUT_TOKENS,
)


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
class USAgentValueFormalDeepSeekRuntimePolicy:
    execution_plan_id: str
    launch_bundle_id: str
    pilot_gate_review_id: str
    protocol_id: str
    provider_id: str
    model_id: str
    prompt_template_id: str
    thinking_enabled: bool
    reasoning_effort: str
    max_output_tokens: int
    transport_max_attempts: int
    transport_retry_backoff_seconds: float
    transport_timeout_seconds: float
    api_surface: str = "openai_chat_completions_json_object_v1"
    structured_schema_name: str = "finagent_us_a0_structured_candidate_v1"
    pricing_policy_id: str = "deepseek-v4-pricing-2026-08-17-v1"
    phase: USAgentValuePhase = USAgentValuePhase.FORMAL
    schema_version: str = "finagent.us-agent-value-formal-deepseek-runtime-policy.v1"

    def __post_init__(self) -> None:
        if self.phase is not USAgentValuePhase.FORMAL:
            raise ValueError("FORMAL DeepSeek runtime policy requires FORMAL phase")
        for field_name in (
            "execution_plan_id",
            "launch_bundle_id",
            "pilot_gate_review_id",
            "protocol_id",
            "provider_id",
            "model_id",
            "prompt_template_id",
            "reasoning_effort",
            "api_surface",
            "structured_schema_name",
            "pricing_policy_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.provider_id != "deepseek":
            raise ValueError("FORMAL runtime policy requires provider_id=deepseek")
        if self.model_id not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
            raise ValueError("FORMAL runtime policy supports DeepSeek V4 Flash/Pro only")
        if self.thinking_enabled is not True:
            raise ValueError("FORMAL DeepSeek runtime requires thinking mode enabled")
        if self.reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("FORMAL reasoning_effort must be low, high or max")
        if not 1 <= self.max_output_tokens <= DEEPSEEK_V4_MAX_OUTPUT_TOKENS:
            raise ValueError(
                f"max_output_tokens must be in [1,{DEEPSEEK_V4_MAX_OUTPUT_TOKENS}]"
            )
        if self.transport_max_attempts < 1:
            raise ValueError("transport_max_attempts must be positive")
        if self.transport_retry_backoff_seconds < 0:
            raise ValueError("transport_retry_backoff_seconds must be non-negative")
        if self.transport_timeout_seconds <= 0:
            raise ValueError("transport_timeout_seconds must be positive")

    @property
    def runtime_policy_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-formal-deepseek-runtime-policy",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "execution_plan_id": self.execution_plan_id,
            "launch_bundle_id": self.launch_bundle_id,
            "pilot_gate_review_id": self.pilot_gate_review_id,
            "protocol_id": self.protocol_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_template_id": self.prompt_template_id,
            "thinking_enabled": self.thinking_enabled,
            "reasoning_effort": self.reasoning_effort,
            "max_output_tokens": self.max_output_tokens,
            "maximum_supported_output_tokens": DEEPSEEK_V4_MAX_OUTPUT_TOKENS,
            "temperature": None,
            "api_surface": self.api_surface,
            "structured_schema_name": self.structured_schema_name,
            "transport_max_attempts": self.transport_max_attempts,
            "transport_retry_backoff_seconds": self.transport_retry_backoff_seconds,
            "transport_timeout_seconds": self.transport_timeout_seconds,
            "pricing_policy_id": self.pricing_policy_id,
            "reasoning_budget_semantics": (
                "reasoning_content_and_final_content_share_the_completion_token_budget"
            ),
            "independent_run_semantics": "three_agent_runs_share_runtime_policy_but_never_prompt_context",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["runtime_policy_id"] = self.runtime_policy_id
        return payload


def build_us_a0_formal_deepseek_runtime_policy(
    *,
    profile: LLMProfile,
    launch_artifacts: USAgentValueFormalLaunchArtifacts,
    max_output_tokens: int = DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
) -> USAgentValueFormalDeepSeekRuntimePolicy:
    launch = launch_artifacts.launch_bundle
    if profile.provider != launch.agent_provider_id or profile.model != launch.agent_model_id:
        raise ValueError("FORMAL runtime LLM profile differs from frozen launch provider identity")
    if launch.agent_prompt_template_id != "us-a0-structured-candidate-v1":
        raise ValueError("FORMAL runtime launch prompt-template identity mismatch")
    if profile.thinking is not True:
        raise ValueError("FORMAL DeepSeek profile must explicitly enable thinking")
    return USAgentValueFormalDeepSeekRuntimePolicy(
        execution_plan_id=launch.execution_plan_id,
        launch_bundle_id=launch.launch_bundle_id,
        pilot_gate_review_id=launch.pilot_gate_review_id,
        protocol_id=launch.protocol_id,
        provider_id=profile.provider,
        model_id=profile.model,
        prompt_template_id=launch.agent_prompt_template_id,
        thinking_enabled=True,
        reasoning_effort=profile.reasoning_effort or "high",
        max_output_tokens=max_output_tokens,
        transport_max_attempts=profile.max_attempts,
        transport_retry_backoff_seconds=profile.retry_backoff_seconds,
        transport_timeout_seconds=profile.timeout_seconds,
    )


def validate_us_a0_formal_deepseek_runtime_policy(
    document: Mapping[str, object],
    *,
    profile: LLMProfile,
    launch_artifacts: USAgentValueFormalLaunchArtifacts,
) -> USAgentValueFormalDeepSeekRuntimePolicy:
    policy = build_us_a0_formal_deepseek_runtime_policy(
        profile=profile,
        launch_artifacts=launch_artifacts,
        max_output_tokens=_integer(document.get("max_output_tokens"), "formal_runtime.max_output_tokens"),
    )
    if dict(document) != policy.to_dict():
        raise ValueError("US-A0 FORMAL DeepSeek runtime policy content identity mismatch")
    return policy


class USAgentValueFormalOrchestrationState(StrEnum):
    PREPARED = "PREPARED"
    AGENT_GENERATION_COMPLETE = "AGENT_GENERATION_COMPLETE"
    RUN_EVIDENCE_COMPLETE = "RUN_EVIDENCE_COMPLETE"
    EXPERIMENT_ASSEMBLED = "EXPERIMENT_ASSEMBLED"
    GATE_REVIEWED = "GATE_REVIEWED"


_FORMAL_STATE_ORDINAL = {
    USAgentValueFormalOrchestrationState.PREPARED: 0,
    USAgentValueFormalOrchestrationState.AGENT_GENERATION_COMPLETE: 1,
    USAgentValueFormalOrchestrationState.RUN_EVIDENCE_COMPLETE: 2,
    USAgentValueFormalOrchestrationState.EXPERIMENT_ASSEMBLED: 3,
    USAgentValueFormalOrchestrationState.GATE_REVIEWED: 4,
}


@dataclass(frozen=True, slots=True)
class USAgentValueFormalOrchestrationCheckpoint:
    launch_bundle_id: str
    runtime_policy_id: str
    execution_plan_id: str
    pilot_gate_review_id: str
    agent_run_spec_ids: tuple[str, ...]
    state: USAgentValueFormalOrchestrationState
    checkpoint_ordinal: int
    previous_checkpoint_id: str | None = None
    agent_generation_run_ids: tuple[str, ...] = ()
    run_evidence_manifest_ids: tuple[str, ...] = ()
    experiment_evidence_graph_id: str | None = None
    gate_review_id: str | None = None
    schema_version: str = "finagent.us-agent-value-formal-orchestration-checkpoint.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "launch_bundle_id",
            "runtime_policy_id",
            "execution_plan_id",
            "pilot_gate_review_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if len(self.agent_run_spec_ids) != 3 or len(set(self.agent_run_spec_ids)) != 3:
            raise ValueError("FORMAL checkpoint requires three unique AGENT run-spec IDs")
        if self.checkpoint_ordinal != _FORMAL_STATE_ORDINAL[self.state]:
            raise ValueError("FORMAL checkpoint ordinal/state mismatch")
        if self.previous_checkpoint_id is not None and not self.previous_checkpoint_id.strip():
            raise ValueError("previous_checkpoint_id must be non-empty when present")
        for values, label in (
            (self.agent_generation_run_ids, "AGENT generation-run"),
            (self.run_evidence_manifest_ids, "run-evidence manifest"),
        ):
            if any(not value.strip() for value in values) or len(values) != len(set(values)):
                raise ValueError(f"FORMAL {label} identities must be unique and non-empty")

        if self.state is USAgentValueFormalOrchestrationState.PREPARED:
            if self.previous_checkpoint_id is not None:
                raise ValueError("FORMAL PREPARED checkpoint cannot have a predecessor")
            if self.agent_generation_run_ids or self.run_evidence_manifest_ids:
                raise ValueError("FORMAL PREPARED checkpoint cannot contain result evidence")
            if self.experiment_evidence_graph_id is not None or self.gate_review_id is not None:
                raise ValueError("FORMAL PREPARED checkpoint cannot contain later evidence")
        else:
            if self.previous_checkpoint_id is None:
                raise ValueError("advanced FORMAL checkpoint requires previous_checkpoint_id")
            if len(self.agent_generation_run_ids) != 3:
                raise ValueError("advanced FORMAL checkpoint requires three frozen AGENT run IDs")

        if self.state is USAgentValueFormalOrchestrationState.AGENT_GENERATION_COMPLETE:
            if self.run_evidence_manifest_ids or self.experiment_evidence_graph_id or self.gate_review_id:
                raise ValueError("AGENT_GENERATION_COMPLETE cannot contain later evidence")
        elif self.state is USAgentValueFormalOrchestrationState.RUN_EVIDENCE_COMPLETE:
            if len(self.run_evidence_manifest_ids) != 7:
                raise ValueError("FORMAL RUN_EVIDENCE_COMPLETE requires seven run manifests")
            if self.experiment_evidence_graph_id is not None or self.gate_review_id is not None:
                raise ValueError("RUN_EVIDENCE_COMPLETE cannot contain experiment/Gate evidence")
        elif self.state is USAgentValueFormalOrchestrationState.EXPERIMENT_ASSEMBLED:
            if len(self.run_evidence_manifest_ids) != 7:
                raise ValueError("FORMAL EXPERIMENT_ASSEMBLED requires seven run manifests")
            if self.experiment_evidence_graph_id is None or self.gate_review_id is not None:
                raise ValueError("EXPERIMENT_ASSEMBLED requires graph and no Gate review")
        elif self.state is USAgentValueFormalOrchestrationState.GATE_REVIEWED:
            if len(self.run_evidence_manifest_ids) != 7:
                raise ValueError("FORMAL GATE_REVIEWED requires seven run manifests")
            if self.experiment_evidence_graph_id is None or self.gate_review_id is None:
                raise ValueError("GATE_REVIEWED requires graph and review")

    @property
    def checkpoint_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-formal-checkpoint",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "launch_bundle_id": self.launch_bundle_id,
            "runtime_policy_id": self.runtime_policy_id,
            "execution_plan_id": self.execution_plan_id,
            "pilot_gate_review_id": self.pilot_gate_review_id,
            "agent_run_spec_ids": list(self.agent_run_spec_ids),
            "state": self.state.value,
            "checkpoint_ordinal": self.checkpoint_ordinal,
            "previous_checkpoint_id": self.previous_checkpoint_id,
            "agent_generation_run_ids": list(self.agent_generation_run_ids),
            "run_evidence_manifest_ids": list(self.run_evidence_manifest_ids),
            "experiment_evidence_graph_id": self.experiment_evidence_graph_id,
            "gate_review_id": self.gate_review_id,
            "resume_semantics": "append_only_formal_checkpoint_chain",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["checkpoint_id"] = self.checkpoint_id
        return payload


def prepare_us_a0_formal_orchestration_checkpoint(
    launch_artifacts: USAgentValueFormalLaunchArtifacts,
    runtime_policy: USAgentValueFormalDeepSeekRuntimePolicy,
) -> USAgentValueFormalOrchestrationCheckpoint:
    launch = launch_artifacts.launch_bundle
    if runtime_policy.launch_bundle_id != launch.launch_bundle_id:
        raise ValueError("FORMAL orchestration runtime-policy/launch identity mismatch")
    if runtime_policy.execution_plan_id != launch.execution_plan_id:
        raise ValueError("FORMAL orchestration runtime-policy/execution-plan identity mismatch")
    if runtime_policy.pilot_gate_review_id != launch.pilot_gate_review_id:
        raise ValueError("FORMAL orchestration runtime-policy/PILOT-review identity mismatch")
    return USAgentValueFormalOrchestrationCheckpoint(
        launch_bundle_id=launch.launch_bundle_id,
        runtime_policy_id=runtime_policy.runtime_policy_id,
        execution_plan_id=launch.execution_plan_id,
        pilot_gate_review_id=launch.pilot_gate_review_id,
        agent_run_spec_ids=launch.agent_run_spec_ids,
        state=USAgentValueFormalOrchestrationState.PREPARED,
        checkpoint_ordinal=0,
    )


def advance_us_a0_formal_orchestration_checkpoint(
    previous: USAgentValueFormalOrchestrationCheckpoint,
    *,
    state: USAgentValueFormalOrchestrationState,
    agent_generation_run_ids: tuple[str, ...] | None = None,
    run_evidence_manifest_ids: tuple[str, ...] | None = None,
    experiment_evidence_graph_id: str | None = None,
    gate_review_id: str | None = None,
) -> USAgentValueFormalOrchestrationCheckpoint:
    if _FORMAL_STATE_ORDINAL[state] != previous.checkpoint_ordinal + 1:
        raise ValueError("FORMAL orchestration transitions must advance exactly one state")
    if previous.agent_generation_run_ids:
        if (
            agent_generation_run_ids is not None
            and agent_generation_run_ids != previous.agent_generation_run_ids
        ):
            raise ValueError("FORMAL orchestration cannot replace frozen AGENT generation runs")
        agent_generation_run_ids = previous.agent_generation_run_ids
    if agent_generation_run_ids is None:
        agent_generation_run_ids = ()
    if previous.run_evidence_manifest_ids:
        if (
            run_evidence_manifest_ids is not None
            and run_evidence_manifest_ids != previous.run_evidence_manifest_ids
        ):
            raise ValueError("FORMAL orchestration cannot replace frozen run evidence manifests")
        run_evidence_manifest_ids = previous.run_evidence_manifest_ids
    if run_evidence_manifest_ids is None:
        run_evidence_manifest_ids = ()
    if previous.experiment_evidence_graph_id is not None:
        if (
            experiment_evidence_graph_id is not None
            and experiment_evidence_graph_id != previous.experiment_evidence_graph_id
        ):
            raise ValueError("FORMAL orchestration cannot replace frozen experiment graph")
        experiment_evidence_graph_id = previous.experiment_evidence_graph_id
    if previous.gate_review_id is not None:
        if gate_review_id is not None and gate_review_id != previous.gate_review_id:
            raise ValueError("FORMAL orchestration cannot replace frozen Gate review")
        gate_review_id = previous.gate_review_id
    return USAgentValueFormalOrchestrationCheckpoint(
        launch_bundle_id=previous.launch_bundle_id,
        runtime_policy_id=previous.runtime_policy_id,
        execution_plan_id=previous.execution_plan_id,
        pilot_gate_review_id=previous.pilot_gate_review_id,
        agent_run_spec_ids=previous.agent_run_spec_ids,
        state=state,
        checkpoint_ordinal=previous.checkpoint_ordinal + 1,
        previous_checkpoint_id=previous.checkpoint_id,
        agent_generation_run_ids=agent_generation_run_ids,
        run_evidence_manifest_ids=run_evidence_manifest_ids,
        experiment_evidence_graph_id=experiment_evidence_graph_id,
        gate_review_id=gate_review_id,
    )


def parse_us_a0_formal_orchestration_checkpoint(
    document: Mapping[str, object],
) -> USAgentValueFormalOrchestrationCheckpoint:
    raw_specs = _sequence(document.get("agent_run_spec_ids"), "formal_checkpoint.agent_run_spec_ids")
    raw_runs = _sequence(
        document.get("agent_generation_run_ids"),
        "formal_checkpoint.agent_generation_run_ids",
    )
    raw_manifests = _sequence(
        document.get("run_evidence_manifest_ids"),
        "formal_checkpoint.run_evidence_manifest_ids",
    )
    if any(not isinstance(item, str) for item in (*raw_specs, *raw_runs, *raw_manifests)):
        raise TypeError("FORMAL checkpoint identity arrays must contain strings")
    checkpoint = USAgentValueFormalOrchestrationCheckpoint(
        launch_bundle_id=_text(document.get("launch_bundle_id"), "formal_checkpoint.launch_bundle_id"),
        runtime_policy_id=_text(
            document.get("runtime_policy_id"), "formal_checkpoint.runtime_policy_id"
        ),
        execution_plan_id=_text(
            document.get("execution_plan_id"), "formal_checkpoint.execution_plan_id"
        ),
        pilot_gate_review_id=_text(
            document.get("pilot_gate_review_id"), "formal_checkpoint.pilot_gate_review_id"
        ),
        agent_run_spec_ids=tuple(str(item) for item in raw_specs),
        state=USAgentValueFormalOrchestrationState(
            _text(document.get("state"), "formal_checkpoint.state")
        ),
        checkpoint_ordinal=_integer(
            document.get("checkpoint_ordinal"), "formal_checkpoint.checkpoint_ordinal"
        ),
        previous_checkpoint_id=_optional_text(
            document.get("previous_checkpoint_id"), "formal_checkpoint.previous_checkpoint_id"
        ),
        agent_generation_run_ids=tuple(str(item) for item in raw_runs),
        run_evidence_manifest_ids=tuple(str(item) for item in raw_manifests),
        experiment_evidence_graph_id=_optional_text(
            document.get("experiment_evidence_graph_id"),
            "formal_checkpoint.experiment_evidence_graph_id",
        ),
        gate_review_id=_optional_text(
            document.get("gate_review_id"), "formal_checkpoint.gate_review_id"
        ),
    )
    if dict(document) != checkpoint.to_dict():
        raise ValueError("US-A0 FORMAL orchestration checkpoint content identity mismatch")
    return checkpoint
