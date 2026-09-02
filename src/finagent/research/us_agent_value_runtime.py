from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from finagent.agents.providers import ConfiguredLLM, LLMCallStore, LLMProfile, LLMRequest
from finagent.research.us_agent_value_deepseek import (
    DEEPSEEK_V4_PRICING_POLICY_ID,
    US_A0_STRUCTURED_PROMPT_TEMPLATE_ID,
    DeepSeekStructuredAgentSlotProvider,
)
from finagent.research.us_agent_value_execution import (
    USAgentValueExecutionPlan,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_generation import CandidateGenerationRunSpec
from finagent.research.us_agent_value_launch import (
    USAgentValuePilotLaunchArtifacts,
    validate_us_a0_pilot_launch_bundle,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
)

DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS = 65_536
DEEPSEEK_V4_MAX_OUTPUT_TOKENS = 384_000
DEEPSEEK_V4_RUNTIME_POLICY_SCHEMA = "finagent.us-agent-value-deepseek-runtime-policy.v1"


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
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class USAgentValueDeepSeekRuntimePolicy:
    execution_plan_id: str
    launch_bundle_id: str
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
    pricing_policy_id: str = DEEPSEEK_V4_PRICING_POLICY_ID
    phase: USAgentValuePhase = USAgentValuePhase.PILOT
    schema_version: str = DEEPSEEK_V4_RUNTIME_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.phase is not USAgentValuePhase.PILOT:
            raise ValueError("DeepSeek runtime policy v1 is PILOT-only")
        for field_name in (
            "execution_plan_id",
            "launch_bundle_id",
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
            raise ValueError("US-A0 runtime policy v1 requires provider_id=deepseek")
        if self.model_id not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
            raise ValueError("US-A0 runtime policy supports DeepSeek V4 Flash/Pro only")
        if self.prompt_template_id != US_A0_STRUCTURED_PROMPT_TEMPLATE_ID:
            raise ValueError("US-A0 runtime policy prompt-template identity mismatch")
        if self.thinking_enabled is not True:
            raise ValueError("US-A0 DeepSeek runtime policy requires thinking mode enabled")
        if self.reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("reasoning_effort must be low, high or max")
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
            prefix="us-agent-value-deepseek-runtime-policy",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "execution_plan_id": self.execution_plan_id,
            "launch_bundle_id": self.launch_bundle_id,
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
            "research_trial_semantics": (
                "transport_retries_do_not_expand_candidate_slots_or_in_slot_repair_count"
            ),
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["runtime_policy_id"] = self.runtime_policy_id
        return payload


def build_us_a0_deepseek_runtime_policy(
    *,
    profile: LLMProfile,
    execution_plan: USAgentValueExecutionPlan,
    launch_artifacts: USAgentValuePilotLaunchArtifacts,
    max_output_tokens: int = DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
) -> USAgentValueDeepSeekRuntimePolicy:
    if execution_plan.plan_id != launch_artifacts.execution_plan.plan_id:
        raise ValueError("runtime policy execution-plan/launch identity mismatch")
    launch = launch_artifacts.launch_bundle
    if profile.provider != launch.agent_provider_id or profile.model != launch.agent_model_id:
        raise ValueError("runtime policy LLM profile differs from frozen launch provider identity")
    if launch.agent_prompt_template_id != US_A0_STRUCTURED_PROMPT_TEMPLATE_ID:
        raise ValueError("runtime policy launch prompt-template identity mismatch")
    if profile.thinking is not True:
        raise ValueError("selected DeepSeek profile must explicitly enable thinking")
    effort = profile.reasoning_effort or "high"
    return USAgentValueDeepSeekRuntimePolicy(
        execution_plan_id=execution_plan.plan_id,
        launch_bundle_id=launch.launch_bundle_id,
        protocol_id=execution_plan.protocol_id,
        provider_id=profile.provider,
        model_id=profile.model,
        prompt_template_id=launch.agent_prompt_template_id,
        thinking_enabled=True,
        reasoning_effort=effort,
        max_output_tokens=max_output_tokens,
        transport_max_attempts=profile.max_attempts,
        transport_retry_backoff_seconds=profile.retry_backoff_seconds,
        transport_timeout_seconds=profile.timeout_seconds,
    )


def validate_us_a0_deepseek_runtime_policy(
    document: Mapping[str, object],
    *,
    profile: LLMProfile,
    preregistration_document: Mapping[str, object],
    execution_plan_document: Mapping[str, object],
    gate_policy_document: Mapping[str, object],
    launch_bundle_document: Mapping[str, object],
) -> tuple[USAgentValuePilotLaunchArtifacts, USAgentValueDeepSeekRuntimePolicy]:
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration_document,
    )
    if protocol.phase is not USAgentValuePhase.PILOT:
        raise ValueError("DeepSeek runtime policy v1 requires PILOT protocol")
    launch_artifacts = validate_us_a0_pilot_launch_bundle(
        launch_bundle_document,
        preregistration_document=preregistration_document,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
    )
    policy = build_us_a0_deepseek_runtime_policy(
        profile=profile,
        execution_plan=execution_plan,
        launch_artifacts=launch_artifacts,
        max_output_tokens=_integer(document.get("max_output_tokens"), "runtime.max_output_tokens"),
    )
    if dict(document) != policy.to_dict():
        raise ValueError("US-A0 DeepSeek runtime policy content identity mismatch")
    return launch_artifacts, policy


class RuntimeBoundDeepSeekStructuredAgentSlotProvider(DeepSeekStructuredAgentSlotProvider):
    """Bind the shared DeepSeek transport to the preregistered A0 runtime policy."""

    def __init__(
        self,
        configured_llm: ConfiguredLLM,
        *,
        runtime_policy: USAgentValueDeepSeekRuntimePolicy,
        call_store: LLMCallStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if configured_llm.profile.provider != runtime_policy.provider_id:
            raise ValueError("runtime-bound provider/profile provider identity mismatch")
        if configured_llm.profile.model != runtime_policy.model_id:
            raise ValueError("runtime-bound provider/profile model identity mismatch")
        if configured_llm.profile.thinking is not runtime_policy.thinking_enabled:
            raise ValueError("runtime-bound provider thinking identity mismatch")
        if (configured_llm.profile.reasoning_effort or "high") != runtime_policy.reasoning_effort:
            raise ValueError("runtime-bound provider reasoning-effort identity mismatch")
        super().__init__(configured_llm, call_store=call_store, clock=clock)
        self.runtime_policy = runtime_policy

    def _request(
        self,
        protocol: USAgentValueExperimentProtocol,
        run_spec: CandidateGenerationRunSpec,
        *,
        slot_index: int,
        attempt_index: int,
        accepted_candidates: tuple,
        repair_reason: str | None,
    ) -> LLMRequest:
        request = super()._request(
            protocol,
            run_spec,
            slot_index=slot_index,
            attempt_index=attempt_index,
            accepted_candidates=accepted_candidates,
            repair_reason=repair_reason,
        )
        return replace(
            request,
            max_output_tokens=self.runtime_policy.max_output_tokens,
            temperature=None,
            metadata={
                **dict(request.metadata),
                "runtime_policy_id": self.runtime_policy.runtime_policy_id,
                "reasoning_effort": self.runtime_policy.reasoning_effort,
                "max_output_tokens": str(self.runtime_policy.max_output_tokens),
            },
        )


def configured_runtime_bound_deepseek_provider(
    configured_llm: ConfiguredLLM,
    *,
    runtime_policy: USAgentValueDeepSeekRuntimePolicy,
    call_store: LLMCallStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RuntimeBoundDeepSeekStructuredAgentSlotProvider:
    return RuntimeBoundDeepSeekStructuredAgentSlotProvider(
        configured_llm,
        runtime_policy=runtime_policy,
        call_store=call_store,
        clock=clock,
    )
