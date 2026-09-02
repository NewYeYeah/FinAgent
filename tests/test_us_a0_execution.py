from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_execution import (
    USAgentValueExecutionPlan,
    USAgentValueFoldMaterializationManifest,
    build_us_a0_execution_plan,
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    build_candidate_generation_run,
    deterministic_programmatic_proposal_slots,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baseline_materialization import USBaselineMaterializationDiagnostics


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


def _plan(phase: USAgentValuePhase) -> USAgentValueExecutionPlan:
    protocol = canonical_us_a0_experiment_protocol(phase)
    seeds = (1729,) if phase is USAgentValuePhase.PILOT else (1729, 2718, 3141)
    preregistration = _preregistration(phase)
    return build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=seeds,
        agent_provider_id="provider-test",
        agent_model_id="model-test",
        agent_prompt_template_id="prompt-test",
    )


def test_execution_plan_freezes_equal_nonmanual_runs_and_distinct_programmatic_seeds() -> None:
    pilot = _plan(USAgentValuePhase.PILOT)
    formal = _plan(USAgentValuePhase.FORMAL)

    assert len(pilot.run_specs) == 3
    assert len(formal.run_specs) == 7
    assert sum(item.arm is USAgentValueArm.MANUAL for item in formal.run_specs) == 1
    assert sum(item.arm is USAgentValueArm.PROGRAMMATIC for item in formal.run_specs) == 3
    assert sum(item.arm is USAgentValueArm.AGENT for item in formal.run_specs) == 3
    assert tuple(
        item.random_seed
        for item in formal.run_specs
        if item.arm is USAgentValueArm.PROGRAMMATIC
    ) == (1729, 2718, 3141)
    assert formal.to_dict()["agent_value_gate_authority"] is False


def test_execution_plan_rejects_duplicate_programmatic_seeds() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)
    preregistration = _preregistration(USAgentValuePhase.FORMAL)

    with pytest.raises(ValueError, match="seeds must be present and unique"):
        build_us_a0_execution_plan(
            protocol,
            preregistration_bundle_id=str(preregistration["bundle_id"]),
            programmatic_seeds=(7, 7, 9),
            agent_provider_id="provider-test",
            agent_model_id="model-test",
            agent_prompt_template_id="prompt-test",
        )


def test_execution_plan_document_round_trip_binds_exact_preregistration_bundle() -> None:
    preregistration = _preregistration(USAgentValuePhase.PILOT)
    plan = _plan(USAgentValuePhase.PILOT)

    protocol, parsed = validate_us_a0_execution_plan(plan.to_dict(), preregistration)

    assert parsed.plan_id == plan.plan_id
    assert protocol.protocol_id == plan.protocol_id
    drifted = dict(plan.to_dict())
    drifted["preregistration_bundle_id"] = "different-bundle"
    with pytest.raises(ValueError, match="bundle identity mismatch"):
        validate_us_a0_execution_plan(drifted, preregistration)


def test_generation_run_parser_rehashes_nested_content_and_requires_plan_authorization() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    plan = _plan(USAgentValuePhase.PILOT)
    spec = next(
        item for item in plan.run_specs if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    assert spec.random_seed == 1729
    slots = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=1729,
        generated_at=datetime(2026, 9, 2, 5, 0, tzinfo=UTC),
    )
    run = build_candidate_generation_run(protocol, spec, slots)

    parsed = parse_candidate_generation_run(run.to_dict(), plan)
    assert parsed.run_id == run.run_id

    tampered = json.loads(json.dumps(run.to_dict()))
    tampered["events"][0]["proposal"]["hypothesis_summary"] = "tampered wording"
    with pytest.raises(ValueError, match="proposal content identity mismatch"):
        parse_candidate_generation_run(tampered, plan)

    unauthorized_spec = next(
        item
        for item in build_us_a0_execution_plan(
            protocol,
            preregistration_bundle_id=plan.preregistration_bundle_id,
            programmatic_seeds=(9999,),
            agent_provider_id="provider-test",
            agent_model_id="model-test",
            agent_prompt_template_id="prompt-test",
        ).run_specs
        if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    unauthorized_run = build_candidate_generation_run(
        protocol,
        unauthorized_spec,
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=9999,
            generated_at=datetime(2026, 9, 2, 5, 0, tzinfo=UTC),
        ),
    )
    with pytest.raises(ValueError, match="not authorized"):
        parse_candidate_generation_run(unauthorized_run.to_dict(), plan)


def test_zero_candidate_agent_run_is_valid_generation_evidence_not_replaced() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    plan = _plan(USAgentValuePhase.PILOT)
    spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    proposal = StructuredCandidateProposal(
        kind="unsupported-kind",
        window_bars=2,
        hypothesis_summary="Deliberately invalid synthetic proposal.",
        generated_at=datetime(2026, 9, 2, 5, 0, tzinfo=UTC),
        usage=CandidateGenerationUsage(
            llm_calls=1,
            input_tokens=10,
            output_tokens=5,
            latency_ms=100.0,
            cost_usd=0.001,
        ),
    )
    run = build_candidate_generation_run(
        protocol,
        spec,
        tuple(ProposalSlot(initial=proposal) for _ in range(16)),
    )

    assert run.accepted_candidates == ()
    assert run.invalid_slot_count == 16
    assert run.to_dict()["replacement_count"] == 0
    assert parse_candidate_generation_run(run.to_dict(), plan).run_id == run.run_id


def _diagnostics(*, blocker: str | None = None) -> USBaselineMaterializationDiagnostics:
    return USBaselineMaterializationDiagnostics(
        input_row_count=100,
        expected_asset_count=20,
        observed_asset_count=20,
        missing_assets=(),
        assets_without_complete_bar=(),
        complete_bar_count=100,
        incomplete_bar_count=0,
        label_anchor_missing_count=0,
        close_anchor_mismatch_count=0,
        label_available_count=100,
        target_crosses_session_count=0,
        target_minute_missing_count=0,
        candidate_checks=(),
        blockers=() if blocker is None else (blocker,),
    )


def test_fold_materialization_manifest_separates_technical_failure_from_candidate_results() -> None:
    passed = USAgentValueFoldMaterializationManifest(
        execution_plan_id="plan",
        preregistration_bundle_id="bundle",
        generation_run_id="run",
        evaluation_binding_id="binding",
        fold_execution_spec_id="fold-spec",
        fold_ordinal=1,
        input_plan_id="input-plan",
        input_materialization_id="input-materialization",
        observation_artifact_id="observation",
        diagnostics=_diagnostics(),
        fold_evaluation_report_id="evaluation",
        engineering_asset_count=20,
    )
    failed = USAgentValueFoldMaterializationManifest(
        execution_plan_id="plan",
        preregistration_bundle_id="bundle",
        generation_run_id="run",
        evaluation_binding_id="binding",
        fold_execution_spec_id="fold-spec",
        fold_ordinal=1,
        input_plan_id="input-plan",
        input_materialization_id="input-materialization",
        observation_artifact_id="observation",
        diagnostics=_diagnostics(blocker="input:label_anchor_missing_count:1"),
        fold_evaluation_report_id="evaluation",
        engineering_asset_count=20,
    )

    assert passed.technical_passed
    assert not failed.technical_passed
    assert passed.to_dict()["candidate_invalidity_is_not_a_technical_blocker"] is True
