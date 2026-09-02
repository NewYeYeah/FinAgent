from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_gate import canonical_us_a0_agent_value_gate_policy
from finagent.research.us_agent_value_launch import (
    assess_us_a0_pilot_launch_readiness,
    build_us_a0_pilot_launch_artifacts,
    validate_us_a0_pilot_control_documents,
    validate_us_a0_pilot_launch_bundle,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)

_FIXED_AT = datetime(2026, 9, 2, 7, 30, tzinfo=UTC)


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
    phase = USAgentValuePhase.PILOT
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


def _plan_document() -> dict[str, object]:
    preregistration = _preregistration()
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    return build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=(1729,),
        agent_provider_id="deepseek",
        agent_model_id="deepseek-v4-flash",
        agent_prompt_template_id="us-a0-structured-candidate-v1",
    ).to_dict()


def _gate_document() -> dict[str, object]:
    return canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT).to_dict()


def _artifacts(at: datetime = _FIXED_AT):
    return build_us_a0_pilot_launch_artifacts(
        preregistration_document=_preregistration(),
        execution_plan_document=_plan_document(),
        gate_policy_document=_gate_document(),
        control_generated_at=at,
    )


def test_user_frozen_v4_flash_pilot_execution_plan_identity_is_canonical() -> None:
    plan = _plan_document()

    assert plan["plan_id"] == "us-agent-value-execution-plan-4312941b91abba09a44c34cb"
    assert plan["run_spec_ids"] == [
        "us-agent-value-generation-run-spec-9ec81b3df00991810108275e",
        "us-agent-value-generation-run-spec-18eb9cec17aa2b88a2af935e",
        "us-agent-value-generation-run-spec-90d98b3925764c799c35e08c",
    ]


def test_pilot_launch_freezes_exact_control_runs_and_only_agent_run_spec() -> None:
    artifacts = _artifacts()
    launch = artifacts.launch_bundle

    assert launch.execution_plan_id == "us-agent-value-execution-plan-4312941b91abba09a44c34cb"
    assert launch.agent_model_id == "deepseek-v4-flash"
    assert launch.agent_provider_id == "deepseek"
    assert launch.agent_prompt_template_id == "us-a0-structured-candidate-v1"
    assert launch.agent_run_spec_ids == (
        "us-agent-value-generation-run-spec-90d98b3925764c799c35e08c",
    )
    assert launch.frozen_control_run_ids == (
        artifacts.manual_run.run_id,
        artifacts.programmatic_runs[0].run_id,
    )
    assert len(artifacts.manual_run.accepted_candidates) == 16
    assert len(artifacts.programmatic_runs[0].accepted_candidates) == 16
    assert artifacts.manual_run.spec.arm is USAgentValueArm.MANUAL
    assert artifacts.programmatic_runs[0].spec.arm is USAgentValueArm.PROGRAMMATIC
    assert launch.to_dict()["agent_generation_scope"] == (
        "run_spec_frozen_real_run_id_pending_external_execution"
    )
    assert launch.to_dict()["agent_value_gate_authority"] is False


def test_launch_rebuild_is_stable_at_same_timestamp_and_changes_with_control_time() -> None:
    first = _artifacts(_FIXED_AT)
    second = _artifacts(_FIXED_AT)
    shifted = _artifacts(_FIXED_AT + timedelta(seconds=1))

    assert first.launch_bundle.launch_bundle_id == second.launch_bundle.launch_bundle_id
    assert first.launch_bundle.frozen_control_run_ids == second.launch_bundle.frozen_control_run_ids
    assert first.launch_bundle.launch_bundle_id != shifted.launch_bundle.launch_bundle_id
    assert first.launch_bundle.frozen_control_run_ids != shifted.launch_bundle.frozen_control_run_ids


def test_launch_bundle_and_control_documents_fail_closed_on_tampering() -> None:
    artifacts = _artifacts()
    launch_document = artifacts.launch_bundle.to_dict()

    parsed = validate_us_a0_pilot_launch_bundle(
        launch_document,
        preregistration_document=_preregistration(),
        execution_plan_document=_plan_document(),
        gate_policy_document=_gate_document(),
    )
    controls = validate_us_a0_pilot_control_documents(
        parsed,
        tuple(run.to_dict() for run in artifacts.control_runs),
    )
    assert tuple(run.run_id for run in controls) == artifacts.launch_bundle.frozen_control_run_ids

    tampered_launch = dict(launch_document)
    tampered_launch["manual_generation_run_id"] = "tampered-control"
    with pytest.raises(ValueError, match="launch bundle content identity mismatch"):
        validate_us_a0_pilot_launch_bundle(
            tampered_launch,
            preregistration_document=_preregistration(),
            execution_plan_document=_plan_document(),
            gate_policy_document=_gate_document(),
        )

    tampered_control = json.loads(json.dumps(artifacts.manual_run.to_dict()))
    tampered_control["events"][0]["proposal"]["hypothesis_summary"] = "tampered"
    with pytest.raises(ValueError, match="proposal content identity mismatch"):
        validate_us_a0_pilot_control_documents(
            artifacts,
            (tampered_control, artifacts.programmatic_runs[0].to_dict()),
        )


def test_launch_readiness_is_diagnostic_and_stage_bound() -> None:
    launch = _artifacts().launch_bundle
    pending = assess_us_a0_pilot_launch_readiness(
        {
            "current_stage": "US-D3",
            "stage": {},
        },
        launch,
    )
    assert pending.ready_for_external_agent_generation is False
    assert pending.blockers == ("us_a0_stage_authority_not_ready",)
    assert pending.to_dict()["research_authority"] is False

    ready = assess_us_a0_pilot_launch_readiness(
        {
            "current_stage": "US-A0",
            "stage": {
                "us_b0": {
                    "status": "accepted",
                    "stage_exit_gate_passed": True,
                    "walk_forward_evidence_graph_id": "b0-graph",
                    "walk_forward_aggregate_report_id": "b0-aggregate",
                }
            },
        },
        launch,
    )
    assert ready.ready_for_external_agent_generation is True
    assert ready.blockers == ()


def test_launch_requires_exact_frozen_gate_policy() -> None:
    drifted = _gate_document()
    drifted["practical_rank_ic_margin"] = 0.005

    with pytest.raises(ValueError, match="exact frozen canonical policy"):
        build_us_a0_pilot_launch_artifacts(
            preregistration_document=_preregistration(),
            execution_plan_document=_plan_document(),
            gate_policy_document=drifted,
            control_generated_at=_FIXED_AT,
        )
