from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_assembly import ParsedUSAgentValueRunEvidence
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_experiment import (
    RunEvaluationLink,
    USAgentValuePredecessorBinding,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    canonical_us_a0_agent_value_gate_policy,
    finalize_us_a0_agent_value_gate_review,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    build_candidate_generation_run,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
)
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationCheckpoint,
    USAgentValuePilotOrchestrationState,
)
from finagent.research.us_agent_value_postrun_orchestration import (
    build_us_a0_pilot_experiment_artifacts,
    build_us_a0_pilot_gate_reviewed_checkpoint,
    parse_us_a0_pilot_experiment_assembly_manifest,
    validate_us_a0_pilot_experiment_documents,
    validate_us_a0_pilot_gate_review_document,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_agent_value_run_orchestration import (
    USAgentValuePilotRunProgress,
    committed_run_from_parsed_evidence,
)
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import canonical_us_baseline_denominator

_FIXED_AT = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def _predecessor() -> USAgentValuePredecessorBinding:
    return USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id="us-b0-graph-test",
        us_b0_aggregate_report_id="us-b0-aggregate-test",
        us_b0_run_spec_id="us-b0-run-spec-test",
        us_b0_denominator_id=canonical_us_baseline_denominator().denominator_id,
        us_b0_walk_forward_protocol_id=canonical_us_b0_pilot_walk_forward().protocol_id,
        candidate_count=8,
    )


def _fixture():
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id="pilot-preregistration-test",
        programmatic_seeds=(1729,),
        agent_provider_id="deepseek",
        agent_model_id="deepseek-v4-flash",
        agent_prompt_template_id="us-a0-structured-candidate-v1",
    )
    manual_spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.MANUAL)
    programmatic_spec = next(
        item for item in plan.run_specs if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    agent_spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    manual_run = build_candidate_generation_run(
        protocol,
        manual_spec,
        manual_proposal_slots(protocol, generated_at=_FIXED_AT),
    )
    programmatic_run = build_candidate_generation_run(
        protocol,
        programmatic_spec,
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=1729,
            generated_at=_FIXED_AT,
        ),
    )
    used_ids = {
        candidate.candidate_id
        for run in (manual_run, programmatic_run)
        for candidate in run.accepted_candidates
    }
    available = tuple(
        candidate
        for candidate in canonical_us_a0_primitive_vocabulary().all_candidates()
        if candidate.candidate_id not in used_ids
    )
    assert len(available) >= protocol.candidate_budget_per_run
    agent_slots = tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=candidate.kind.value,
                window_bars=candidate.window_bars,
                hypothesis_summary="Synthetic novel Agent candidate for post-run orchestration.",
                generated_at=_FIXED_AT,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=40,
                    output_tokens=20,
                    latency_ms=100.0,
                    cost_usd=0.001,
                ),
            )
        )
        for candidate in available[: protocol.candidate_budget_per_run]
    )
    agent_run = build_candidate_generation_run(protocol, agent_spec, agent_slots)

    metric_by_arm = {
        USAgentValueArm.MANUAL: (0.015, 0.010),
        USAgentValueArm.PROGRAMMATIC: (0.020, 0.015),
        USAgentValueArm.AGENT: (0.045, 0.040),
    }
    predecessor = _predecessor()
    parsed: list[ParsedUSAgentValueRunEvidence] = []
    for index, run in enumerate((manual_run, programmatic_run, agent_run), start=1):
        best_mean, best_worst = metric_by_arm[run.spec.arm]
        link = RunEvaluationLink(
            generation_run_id=run.run_id,
            authoritative_evidence_id=f"run-evaluation-{index}",
            evaluated_candidate_count=len(run.accepted_candidates),
            valid_candidate_count=len(run.accepted_candidates),
            best_mean_rank_ic=best_mean,
            best_worst_fold_rank_ic=best_worst,
            blockers=(),
        )
        parsed.append(
            ParsedUSAgentValueRunEvidence(
                generation_run=run,
                evaluation_link=link,
                run_evaluation_report_id=link.authoritative_evidence_id,
                run_evaluation_status="EVALUATED",
                run_evidence_manifest_id=f"run-manifest-{index}",
                evaluation_binding_id=f"evaluation-binding-{index}",
                predecessor_binding_id=predecessor.binding_id,
                fold_materialization_manifest_ids=(
                    f"fold-manifest-{index}-1",
                    f"fold-manifest-{index}-2",
                    f"fold-manifest-{index}-3",
                ),
            )
        )
    parsed_tuple = tuple(parsed)
    completed = tuple(
        committed_run_from_parsed_evidence(item, run_order=index)
        for index, item in enumerate(parsed_tuple, start=1)
    )
    progress = USAgentValuePilotRunProgress(
        launch_bundle_id="launch-test",
        runtime_policy_id="runtime-test",
        execution_plan_id=plan.plan_id,
        agent_generated_checkpoint_id="checkpoint-agent-generated",
        predecessor_binding_id=predecessor.binding_id,
        completed_runs=completed,
        previous_progress_id="progress-02",
    )
    run_checkpoint = USAgentValuePilotOrchestrationCheckpoint(
        launch_bundle_id="launch-test",
        runtime_policy_id="runtime-test",
        execution_plan_id=plan.plan_id,
        agent_run_spec_id=agent_spec.run_spec_id,
        state=USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE,
        checkpoint_ordinal=2,
        previous_checkpoint_id="checkpoint-agent-generated",
        agent_generation_run_id=agent_run.run_id,
        run_evidence_manifest_ids=tuple(item.run_evidence_manifest_id for item in parsed_tuple),
    )
    policy = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT)
    return protocol, plan, predecessor, parsed_tuple, progress, run_checkpoint, policy


def test_postrun_assembly_builds_assessment_manifest_and_experiment_checkpoint() -> None:
    protocol, plan, predecessor, parsed, progress, checkpoint, policy = _fixture()

    artifacts = build_us_a0_pilot_experiment_artifacts(
        protocol=protocol,
        execution_plan=plan,
        predecessor=predecessor,
        run_evidence=parsed,
        gate_policy=policy,
        run_checkpoint=checkpoint,
        run_progress=progress,
    )

    assert artifacts.checkpoint.state is USAgentValuePilotOrchestrationState.EXPERIMENT_ASSEMBLED
    assert artifacts.checkpoint.previous_checkpoint_id == checkpoint.checkpoint_id
    assert artifacts.checkpoint.experiment_evidence_graph_id == artifacts.evidence_graph.graph_id
    assert artifacts.assessment.decision is USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL
    assert artifacts.assembly_manifest.gate_assessment_id == artifacts.assessment.assessment_id
    assert artifacts.assembly_manifest.run_progress_id == progress.progress_id
    assert artifacts.assembly_manifest.to_dict()["agent_value_gate_authority"] is False
    assert (
        parse_us_a0_pilot_experiment_assembly_manifest(
            artifacts.assembly_manifest.to_dict()
        )
        == artifacts.assembly_manifest
    )


def test_postrun_assembly_rejects_progress_from_different_agent_checkpoint() -> None:
    protocol, plan, predecessor, parsed, progress, checkpoint, policy = _fixture()
    drifted = replace(progress, agent_generated_checkpoint_id="other-agent-checkpoint")

    with pytest.raises(ValueError, match="Agent checkpoint lineage"):
        build_us_a0_pilot_experiment_artifacts(
            protocol=protocol,
            execution_plan=plan,
            predecessor=predecessor,
            run_evidence=parsed,
            gate_policy=policy,
            run_checkpoint=checkpoint,
            run_progress=drifted,
        )


def test_stored_experiment_documents_fail_closed_on_graph_tamper() -> None:
    protocol, plan, predecessor, parsed, progress, checkpoint, policy = _fixture()
    artifacts = build_us_a0_pilot_experiment_artifacts(
        protocol=protocol,
        execution_plan=plan,
        predecessor=predecessor,
        run_evidence=parsed,
        gate_policy=policy,
        run_checkpoint=checkpoint,
        run_progress=progress,
    )
    graph_document = dict(artifacts.evidence_graph.to_dict())
    graph_document["evidence_complete"] = False

    with pytest.raises(ValueError, match="evidence graph"):
        validate_us_a0_pilot_experiment_documents(
            artifacts,
            arm_documents=tuple(result.to_dict() for result in artifacts.arm_results),
            experiment_document=artifacts.experiment.to_dict(),
            comparison_document=artifacts.comparison.to_dict(),
            graph_document=graph_document,
            assessment_document=artifacts.assessment.to_dict(),
            manifest_document=artifacts.assembly_manifest.to_dict(),
            checkpoint_document=artifacts.checkpoint.to_dict(),
        )


def test_independent_review_round_trip_and_gate_reviewed_checkpoint() -> None:
    protocol, plan, predecessor, parsed, progress, checkpoint, policy = _fixture()
    artifacts = build_us_a0_pilot_experiment_artifacts(
        protocol=protocol,
        execution_plan=plan,
        predecessor=predecessor,
        run_evidence=parsed,
        gate_policy=policy,
        run_checkpoint=checkpoint,
        run_progress=progress,
    )
    review = finalize_us_a0_agent_value_gate_review(
        artifacts.assessment,
        reviewer_id="reviewer-test",
        reviewed_at=_FIXED_AT,
        review_notes="Independent review accepts the preregistered deterministic PILOT assessment.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        alpha_gate_separation_attested=True,
        stage_authority_separation_attested=True,
    )

    parsed_review = validate_us_a0_pilot_gate_review_document(
        review.to_dict(),
        assessment=artifacts.assessment,
    )
    reviewed_checkpoint = build_us_a0_pilot_gate_reviewed_checkpoint(
        experiment_checkpoint=artifacts.checkpoint,
        assembly_manifest=artifacts.assembly_manifest,
        review=parsed_review,
    )

    assert parsed_review.review_id == review.review_id
    assert parsed_review.formal_progression_authority is True
    assert parsed_review.agent_value_gate_authority is False
    assert reviewed_checkpoint.state is USAgentValuePilotOrchestrationState.GATE_REVIEWED
    assert reviewed_checkpoint.previous_checkpoint_id == artifacts.checkpoint.checkpoint_id
    assert reviewed_checkpoint.gate_review_id == review.review_id
    assert reviewed_checkpoint.experiment_evidence_graph_id == artifacts.evidence_graph.graph_id


def test_gate_review_document_rejects_reviewer_tamper_even_if_assessment_is_unchanged() -> None:
    protocol, plan, predecessor, parsed, progress, checkpoint, policy = _fixture()
    artifacts = build_us_a0_pilot_experiment_artifacts(
        protocol=protocol,
        execution_plan=plan,
        predecessor=predecessor,
        run_evidence=parsed,
        gate_policy=policy,
        run_checkpoint=checkpoint,
        run_progress=progress,
    )
    review = finalize_us_a0_agent_value_gate_review(
        artifacts.assessment,
        reviewer_id="reviewer-test",
        reviewed_at=_FIXED_AT,
        review_notes="Independent review accepts the preregistered deterministic PILOT assessment.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        alpha_gate_separation_attested=True,
        stage_authority_separation_attested=True,
    )
    tampered = dict(review.to_dict())
    tampered["reviewer_id"] = "other-reviewer"

    with pytest.raises(ValueError, match="content identity mismatch"):
        validate_us_a0_pilot_gate_review_document(
            tampered,
            assessment=artifacts.assessment,
        )
