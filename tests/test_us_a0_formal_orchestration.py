from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from finagent.agents.providers import ConfiguredLLM, LLMProfile, StaticLLMProvider
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_formal_generation import (
    USAgentValueFormalAgentAttemptEvidence,
    USAgentValueFormalAgentSlotEvidence,
    advance_us_a0_formal_agent_run_progress,
    build_us_a0_formal_agent_generation_run,
    validate_us_a0_formal_slot_sequence,
)
from finagent.research.us_agent_value_formal_launch import build_us_a0_formal_launch_artifacts
from finagent.research.us_agent_value_formal_provider import (
    FormalRuntimeBoundDeepSeekAttemptProvider,
)
from finagent.research.us_agent_value_formal_runtime import (
    USAgentValueFormalOrchestrationState,
    advance_us_a0_formal_orchestration_checkpoint,
    build_us_a0_formal_deepseek_runtime_policy,
    prepare_us_a0_formal_orchestration_checkpoint,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    canonical_us_a0_agent_value_gate_policy,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationUsage,
    CandidateValidationStatus,
    StructuredCandidateProposal,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)

_FIXED_AT = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


def _hash(payload: object, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _preregistration(phase: USAgentValuePhase) -> dict[str, object]:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    protocol = canonical_us_a0_experiment_protocol(phase)
    manual = canonical_us_a0_manual_candidates()[: protocol.candidate_budget_per_run]
    payload: dict[str, object] = {
        "schema_version": "finagent.us-agent-value-preregistration-bundle.v1",
        "phase": phase.value,
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


def _pilot_review() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "finagent.us-agent-value-gate-review.v1",
        "assessment": {"synthetic_test_only": True},
        "assessment_id": "synthetic-pilot-assessment",
        "policy_id": "synthetic-pilot-policy",
        "phase": "PILOT",
        "reviewer_id": "test-reviewer",
        "reviewed_at": _FIXED_AT.isoformat(),
        "decision": USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL.value,
        "review_notes": "Synthetic accepted PILOT review used only for FORMAL contract regression.",
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


def _status(review_id: str, *, stage: str = "US-A0") -> dict[str, object]:
    return {
        "current_stage": stage,
        "stage": {
            "us_a0": {
                "pilot_gate_review_status": "accepted",
                "pilot_gate_review_id": review_id,
                "pilot_formal_progression_approved": True,
            }
        },
    }


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


def _formal_artifacts():
    preregistration = _preregistration(USAgentValuePhase.FORMAL)
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=(1729, 2718, 3141),
        agent_provider_id="deepseek",
        agent_model_id="deepseek-v4-flash",
        agent_prompt_template_id="us-a0-structured-candidate-v1",
    )
    review = _pilot_review()
    status = _status(str(review["review_id"]))
    gate = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL)
    launch = build_us_a0_formal_launch_artifacts(
        preregistration_document=preregistration,
        execution_plan_document=plan.to_dict(),
        gate_policy_document=gate.to_dict(),
        status_document=status,
        pilot_gate_review_document=review,
        control_generated_at=_FIXED_AT,
    )
    runtime = build_us_a0_formal_deepseek_runtime_policy(
        profile=_profile(),
        launch_artifacts=launch,
    )
    prepared = prepare_us_a0_formal_orchestration_checkpoint(launch, runtime)
    return preregistration, protocol, plan, review, status, gate, launch, runtime, prepared


def test_formal_launch_freezes_exact_seven_run_plan_after_pilot_review() -> None:
    _, protocol, plan, review, _, _, launch, runtime, prepared = _formal_artifacts()

    assert protocol.candidate_budget_per_run == 32
    assert len(plan.run_specs) == 7
    assert tuple(spec.arm for spec in plan.run_specs) == (
        USAgentValueArm.MANUAL,
        USAgentValueArm.PROGRAMMATIC,
        USAgentValueArm.PROGRAMMATIC,
        USAgentValueArm.PROGRAMMATIC,
        USAgentValueArm.AGENT,
        USAgentValueArm.AGENT,
        USAgentValueArm.AGENT,
    )
    assert tuple(spec.random_seed for spec in plan.run_specs[1:4]) == (1729, 2718, 3141)
    assert len(launch.control_runs) == 4
    assert len(launch.launch_bundle.agent_run_spec_ids) == 3
    assert launch.launch_bundle.pilot_gate_review_id == review["review_id"]
    assert runtime.max_output_tokens == 65_536
    assert prepared.state is USAgentValueFormalOrchestrationState.PREPARED
    assert prepared.agent_run_spec_ids == launch.launch_bundle.agent_run_spec_ids


def test_formal_launch_fails_closed_without_us_a0_pilot_review_authority() -> None:
    preregistration = _preregistration(USAgentValuePhase.FORMAL)
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=(1729, 2718, 3141),
        agent_provider_id="deepseek",
        agent_model_id="deepseek-v4-flash",
        agent_prompt_template_id="us-a0-structured-candidate-v1",
    )
    review = _pilot_review()
    gate = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL)

    with pytest.raises(ValueError, match="current_stage=US-A0"):
        build_us_a0_formal_launch_artifacts(
            preregistration_document=preregistration,
            execution_plan_document=plan.to_dict(),
            gate_policy_document=gate.to_dict(),
            status_document=_status(str(review["review_id"]), stage="US-D3"),
            pilot_gate_review_document=review,
            control_generated_at=_FIXED_AT,
        )


def _attempt(
    *,
    plan_id: str,
    launch_id: str,
    runtime_id: str,
    spec_id: str,
    run_ordinal: int,
    slot_index: int,
    attempt_index: int,
    kind: str,
    window: int,
    status: CandidateValidationStatus,
    candidate_id: str | None,
    reason: str | None,
) -> USAgentValueFormalAgentAttemptEvidence:
    return USAgentValueFormalAgentAttemptEvidence(
        execution_plan_id=plan_id,
        launch_bundle_id=launch_id,
        runtime_policy_id=runtime_id,
        run_spec_id=spec_id,
        run_ordinal=run_ordinal,
        slot_index=slot_index,
        attempt_index=attempt_index,
        request_id=f"us-a0-{spec_id[-12:]}-slot-{slot_index:02d}-attempt-{attempt_index}",
        proposal=StructuredCandidateProposal(
            kind=kind,
            window_bars=window,
            hypothesis_summary="Synthetic FORMAL slot proposal.",
            generated_at=_FIXED_AT,
            usage=CandidateGenerationUsage(
                llm_calls=1,
                input_tokens=20,
                output_tokens=8,
                latency_ms=50.0,
                cost_usd=0.001,
            ),
        ),
        status=status,
        candidate_id=candidate_id,
        classification_reason=reason,
        provider_parse_error=None,
    )


def test_formal_slot_sequence_preserves_duplicate_then_single_repair_semantics() -> None:
    _, protocol, plan, _, _, _, launch, runtime, _ = _formal_artifacts()
    spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    candidates = canonical_us_a0_primitive_vocabulary().all_candidates()
    first, second = candidates[0], candidates[1]
    slot1 = USAgentValueFormalAgentSlotEvidence(
        execution_plan_id=plan.plan_id,
        launch_bundle_id=launch.launch_bundle.launch_bundle_id,
        runtime_policy_id=runtime.runtime_policy_id,
        run_spec_id=spec.run_spec_id,
        run_ordinal=spec.run_ordinal,
        slot_index=1,
        initial=_attempt(
            plan_id=plan.plan_id,
            launch_id=launch.launch_bundle.launch_bundle_id,
            runtime_id=runtime.runtime_policy_id,
            spec_id=spec.run_spec_id,
            run_ordinal=spec.run_ordinal,
            slot_index=1,
            attempt_index=0,
            kind=first.kind.value,
            window=first.window_bars,
            status=CandidateValidationStatus.VALID_UNIQUE,
            candidate_id=first.candidate_id,
            reason=None,
        ),
    )
    slot2 = USAgentValueFormalAgentSlotEvidence(
        execution_plan_id=plan.plan_id,
        launch_bundle_id=launch.launch_bundle.launch_bundle_id,
        runtime_policy_id=runtime.runtime_policy_id,
        run_spec_id=spec.run_spec_id,
        run_ordinal=spec.run_ordinal,
        slot_index=2,
        initial=_attempt(
            plan_id=plan.plan_id,
            launch_id=launch.launch_bundle.launch_bundle_id,
            runtime_id=runtime.runtime_policy_id,
            spec_id=spec.run_spec_id,
            run_ordinal=spec.run_ordinal,
            slot_index=2,
            attempt_index=0,
            kind=first.kind.value,
            window=first.window_bars,
            status=CandidateValidationStatus.DUPLICATE,
            candidate_id=first.candidate_id,
            reason="duplicate_candidate",
        ),
        repair=_attempt(
            plan_id=plan.plan_id,
            launch_id=launch.launch_bundle.launch_bundle_id,
            runtime_id=runtime.runtime_policy_id,
            spec_id=spec.run_spec_id,
            run_ordinal=spec.run_ordinal,
            slot_index=2,
            attempt_index=1,
            kind=second.kind.value,
            window=second.window_bars,
            status=CandidateValidationStatus.VALID_UNIQUE,
            candidate_id=second.candidate_id,
            reason=None,
        ),
    )

    accepted = validate_us_a0_formal_slot_sequence(protocol, spec, (slot1, slot2))
    assert tuple(item.candidate_id for item in accepted) == (
        first.candidate_id,
        second.candidate_id,
    )
    progress1 = advance_us_a0_formal_agent_run_progress(
        previous=None,
        execution_plan=plan,
        spec=spec,
        slot=slot1,
    )
    progress2 = advance_us_a0_formal_agent_run_progress(
        previous=progress1,
        execution_plan=plan,
        spec=spec,
        slot=slot2,
    )
    assert progress2.completed_slot_count == 2
    assert progress2.previous_progress_id == progress1.progress_id


def test_formal_32_slots_compile_through_existing_candidate_generation_run() -> None:
    _, protocol, plan, _, _, _, launch, runtime, _ = _formal_artifacts()
    spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    candidates = canonical_us_a0_primitive_vocabulary().all_candidates()[:32]
    slots = tuple(
        USAgentValueFormalAgentSlotEvidence(
            execution_plan_id=plan.plan_id,
            launch_bundle_id=launch.launch_bundle.launch_bundle_id,
            runtime_policy_id=runtime.runtime_policy_id,
            run_spec_id=spec.run_spec_id,
            run_ordinal=spec.run_ordinal,
            slot_index=index,
            initial=_attempt(
                plan_id=plan.plan_id,
                launch_id=launch.launch_bundle.launch_bundle_id,
                runtime_id=runtime.runtime_policy_id,
                spec_id=spec.run_spec_id,
                run_ordinal=spec.run_ordinal,
                slot_index=index,
                attempt_index=0,
                kind=candidate.kind.value,
                window=candidate.window_bars,
                status=CandidateValidationStatus.VALID_UNIQUE,
                candidate_id=candidate.candidate_id,
                reason=None,
            ),
        )
        for index, candidate in enumerate(candidates, start=1)
    )

    run = build_us_a0_formal_agent_generation_run(protocol, spec, slots)
    assert len(run.events) == 32
    assert len(run.accepted_candidates) == 32
    assert run.spec == spec


def test_formal_runtime_provider_injects_frozen_64k_budget() -> None:
    _, protocol, plan, _, _, _, _, runtime, _ = _formal_artifacts()
    configured = ConfiguredLLM(
        profile=_profile(),
        provider=StaticLLMProvider(
            '{"kind":"momentum","window_bars":4,"hypothesis_summary":"x"}',
            provider_name="deepseek",
            model="deepseek-v4-flash",
        ),
    )
    provider = FormalRuntimeBoundDeepSeekAttemptProvider(
        configured,
        runtime_policy=runtime,
        clock=lambda: _FIXED_AT,
    )
    spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    request = provider._request(
        protocol,
        spec,
        slot_index=1,
        attempt_index=0,
        accepted_candidates=(),
        repair_reason=None,
    )
    assert request.max_output_tokens == 65_536
    assert request.temperature is None
    assert request.metadata["formal_runtime_policy_id"] == runtime.runtime_policy_id


def test_formal_major_checkpoint_requires_three_agent_runs_and_is_append_only() -> None:
    _, _, _, _, _, _, _, _, prepared = _formal_artifacts()
    completed = advance_us_a0_formal_orchestration_checkpoint(
        prepared,
        state=USAgentValueFormalOrchestrationState.AGENT_GENERATION_COMPLETE,
        agent_generation_run_ids=("agent-run-1", "agent-run-2", "agent-run-3"),
    )
    assert completed.previous_checkpoint_id == prepared.checkpoint_id
    with pytest.raises(ValueError, match="cannot replace"):
        advance_us_a0_formal_orchestration_checkpoint(
            completed,
            state=USAgentValueFormalOrchestrationState.RUN_EVIDENCE_COMPLETE,
            agent_generation_run_ids=("agent-run-1", "agent-run-2", "other"),
            run_evidence_manifest_ids=tuple(f"manifest-{index}" for index in range(7)),
        )
