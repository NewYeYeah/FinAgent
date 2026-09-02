from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from finagent.agents.providers import ConfiguredLLM, LLMProfile, StaticLLMProvider
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_gate import canonical_us_a0_agent_value_gate_policy
from finagent.research.us_agent_value_launch import build_us_a0_pilot_launch_artifacts
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationState,
    advance_us_a0_pilot_orchestration_checkpoint,
    parse_us_a0_pilot_orchestration_checkpoint,
    prepare_us_a0_pilot_orchestration_checkpoint,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_agent_value_runtime import (
    DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
    DEEPSEEK_V4_MAX_OUTPUT_TOKENS,
    RuntimeBoundDeepSeekStructuredAgentSlotProvider,
    build_us_a0_deepseek_runtime_policy,
)

_FIXED_AT = datetime(2026, 9, 2, 8, 14, 7, tzinfo=UTC)


def _hash(payload: object, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _preregistration() -> dict[str, object]:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    manual = canonical_us_a0_manual_candidates()[: protocol.candidate_budget_per_run]
    payload: dict[str, object] = {
        "schema_version": "finagent.us-agent-value-preregistration-bundle.v1",
        "phase": USAgentValuePhase.PILOT.value,
        "vocabulary": vocabulary.to_dict(),
        "protocol": protocol.to_dict(),
        "manual_candidates": [item.to_dict() for item in manual],
        "manual_candidate_count": len(manual),
        "scope": "pre_result_controlled_experiment_preregistration_only",
        "status_authority": False,
        "stage_exit_authority": False,
        "agent_value_gate_authority": False,
        "alpha_authority": False,
    }
    payload["bundle_id"] = _hash(payload, "us-agent-value-preregistration")
    return payload


def _profile() -> LLMProfile:
    return LLMProfile(
        name="deepseek_official_v4_flash",
        provider="deepseek",
        model="deepseek-v4-flash",
        secret_id="deepseek_official",
        base_url="https://api.deepseek.com",
        thinking=True,
        reasoning_effort="high",
        max_attempts=3,
        retry_backoff_seconds=1.0,
        timeout_seconds=900.0,
    )


def _artifacts():
    preregistration = _preregistration()
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=(1729,),
        agent_provider_id="deepseek",
        agent_model_id="deepseek-v4-flash",
        agent_prompt_template_id="us-a0-structured-candidate-v1",
    )
    gate = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT)
    launch = build_us_a0_pilot_launch_artifacts(
        preregistration_document=preregistration,
        execution_plan_document=plan.to_dict(),
        gate_policy_document=gate.to_dict(),
        control_generated_at=_FIXED_AT,
    )
    runtime = build_us_a0_deepseek_runtime_policy(
        profile=_profile(),
        execution_plan=plan,
        launch_artifacts=launch,
    )
    return protocol, plan, gate, launch, runtime


def test_runtime_policy_freezes_reasoning_budget_without_changing_execution_plan() -> None:
    _, plan, _, launch, runtime = _artifacts()

    assert plan.plan_id == "us-agent-value-execution-plan-4312941b91abba09a44c34cb"
    assert runtime.execution_plan_id == plan.plan_id
    assert runtime.launch_bundle_id == launch.launch_bundle.launch_bundle_id
    assert runtime.model_id == "deepseek-v4-flash"
    assert runtime.thinking_enabled is True
    assert runtime.reasoning_effort == "high"
    assert runtime.max_output_tokens == DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS == 65_536
    assert runtime.to_dict()["temperature"] is None
    assert runtime.to_dict()["maximum_supported_output_tokens"] == 384_000


def test_runtime_policy_rejects_budget_above_current_deepseek_v4_maximum() -> None:
    _, plan, _, launch, _ = _artifacts()

    with pytest.raises(ValueError, match="max_output_tokens"):
        build_us_a0_deepseek_runtime_policy(
            profile=_profile(),
            execution_plan=plan,
            launch_artifacts=launch,
            max_output_tokens=DEEPSEEK_V4_MAX_OUTPUT_TOKENS + 1,
        )


def test_runtime_bound_provider_injects_64k_budget_and_no_temperature() -> None:
    protocol, plan, _, _, runtime = _artifacts()
    configured = ConfiguredLLM(
        profile=_profile(),
        provider=StaticLLMProvider(
            '{"kind":"momentum","window_bars":4,"hypothesis_summary":"x"}',
            provider_name="deepseek",
            model="deepseek-v4-flash",
        ),
    )
    provider = RuntimeBoundDeepSeekStructuredAgentSlotProvider(
        configured,
        runtime_policy=runtime,
        clock=lambda: _FIXED_AT,
    )
    agent_spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)

    request = provider._request(
        protocol,
        agent_spec,
        slot_index=1,
        attempt_index=0,
        accepted_candidates=(),
        repair_reason=None,
    )

    assert request.max_output_tokens == 65_536
    assert request.temperature is None
    assert request.metadata["runtime_policy_id"] == runtime.runtime_policy_id
    assert request.metadata["max_output_tokens"] == "65536"


def test_resume_checkpoint_is_append_only_and_agent_run_cannot_be_replaced() -> None:
    _, _, _, launch, runtime = _artifacts()
    prepared = prepare_us_a0_pilot_orchestration_checkpoint(
        launch.launch_bundle,
        runtime,
    )
    generated = advance_us_a0_pilot_orchestration_checkpoint(
        prepared,
        state=USAgentValuePilotOrchestrationState.AGENT_GENERATED,
        agent_generation_run_id="agent-run-a",
    )

    assert prepared.state is USAgentValuePilotOrchestrationState.PREPARED
    assert generated.previous_checkpoint_id == prepared.checkpoint_id
    assert generated.agent_generation_run_id == "agent-run-a"
    assert parse_us_a0_pilot_orchestration_checkpoint(generated.to_dict()) == generated

    with pytest.raises(ValueError, match="cannot replace"):
        advance_us_a0_pilot_orchestration_checkpoint(
            generated,
            state=USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE,
            agent_generation_run_id="agent-run-b",
            run_evidence_manifest_ids=("manual", "programmatic", "agent"),
        )


def test_resume_checkpoint_requires_exact_one_step_progression_and_three_run_manifests() -> None:
    _, _, _, launch, runtime = _artifacts()
    prepared = prepare_us_a0_pilot_orchestration_checkpoint(
        launch.launch_bundle,
        runtime,
    )

    with pytest.raises(ValueError, match="exactly one state"):
        advance_us_a0_pilot_orchestration_checkpoint(
            prepared,
            state=USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE,
            agent_generation_run_id="agent-run-a",
            run_evidence_manifest_ids=("manual", "programmatic", "agent"),
        )

    generated = advance_us_a0_pilot_orchestration_checkpoint(
        prepared,
        state=USAgentValuePilotOrchestrationState.AGENT_GENERATED,
        agent_generation_run_id="agent-run-a",
    )
    with pytest.raises(ValueError, match="exactly three"):
        advance_us_a0_pilot_orchestration_checkpoint(
            generated,
            state=USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE,
            run_evidence_manifest_ids=("manual", "agent"),
        )
