from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_assembly import ParsedUSAgentValueRunEvidence
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_experiment import (
    RunEvaluationLink,
    USAgentValuePredecessorBinding,
)
from finagent.research.us_agent_value_formal_postrun import (
    build_us_a0_formal_experiment_artifacts,
    build_us_a0_formal_gate_reviewed_checkpoint,
    parse_us_a0_formal_experiment_assembly_manifest,
    validate_us_a0_formal_gate_review_document,
)
from finagent.research.us_agent_value_formal_run_orchestration import (
    advance_us_a0_formal_run_progress,
    build_formal_run_evidence_complete_checkpoint,
    parse_us_a0_formal_run_progress,
)
from finagent.research.us_agent_value_formal_runtime import (
    USAgentValueFormalOrchestrationCheckpoint,
    USAgentValueFormalOrchestrationState,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    canonical_us_a0_agent_value_gate_policy,
    finalize_us_a0_agent_value_gate_review,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRun,
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    build_candidate_generation_run,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
)

_NOW = datetime(2026, 9, 2, 11, 30, tzinfo=UTC)


def _agent_slots(seed: int) -> tuple[ProposalSlot, ...]:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)
    base = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=seed,
        generated_at=_NOW,
    )
    return tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=slot.initial.kind,
                window_bars=slot.initial.window_bars,
                hypothesis_summary="Synthetic FORMAL Agent proposal for orchestration regression.",
                generated_at=_NOW,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=100,
                    output_tokens=20,
                    latency_ms=200.0,
                    cost_usd=0.002,
                ),
            )
        )
        for slot in base
    )


def _context():
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id="formal-bundle-test",
        programmatic_seeds=(1729, 2718, 3141),
        agent_provider_id="deepseek",
        agent_model_id="deepseek-v4-flash",
        agent_prompt_template_id="us-a0-structured-candidate-v1",
    )
    runs: list[CandidateGenerationRun] = []
    for spec in plan.run_specs:
        if spec.arm is USAgentValueArm.MANUAL:
            slots = manual_proposal_slots(protocol, generated_at=_NOW)
        elif spec.arm is USAgentValueArm.PROGRAMMATIC:
            assert spec.random_seed is not None
            slots = deterministic_programmatic_proposal_slots(
                protocol,
                random_seed=spec.random_seed,
                generated_at=_NOW,
            )
        else:
            slots = _agent_slots(700 + spec.run_ordinal)
        runs.append(build_candidate_generation_run(protocol, spec, slots))
    predecessor = USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id="b0-graph-test",
        us_b0_aggregate_report_id="b0-aggregate-test",
        us_b0_run_spec_id="b0-run-spec-test",
        us_b0_denominator_id="b0-denominator-test",
        us_b0_walk_forward_protocol_id=protocol.us_b0_walk_forward_protocol_id,
        candidate_count=8,
    )
    agent_runs = tuple(run for run in runs if run.spec.arm is USAgentValueArm.AGENT)
    checkpoint = USAgentValueFormalOrchestrationCheckpoint(
        launch_bundle_id="formal-launch-test",
        runtime_policy_id="formal-runtime-test",
        execution_plan_id=plan.plan_id,
        pilot_gate_review_id="pilot-review-test",
        agent_run_spec_ids=tuple(run.spec.run_spec_id for run in agent_runs),
        state=USAgentValueFormalOrchestrationState.AGENT_GENERATION_COMPLETE,
        checkpoint_ordinal=1,
        previous_checkpoint_id="formal-prepared-test",
        agent_generation_run_ids=tuple(run.run_id for run in agent_runs),
    )
    robust = (0.010, 0.012, 0.011, 0.013, 0.030, 0.031, 0.015)
    mean = (0.020, 0.022, 0.021, 0.023, 0.040, 0.041, 0.025)
    parsed: list[ParsedUSAgentValueRunEvidence] = []
    for index, run in enumerate(runs):
        link = RunEvaluationLink(
            generation_run_id=run.run_id,
            authoritative_evidence_id=f"run-evaluation-{index + 1}",
            evaluated_candidate_count=len(run.accepted_candidates),
            valid_candidate_count=len(run.accepted_candidates),
            best_mean_rank_ic=mean[index],
            best_worst_fold_rank_ic=robust[index],
        )
        parsed.append(
            ParsedUSAgentValueRunEvidence(
                generation_run=run,
                evaluation_link=link,
                run_evaluation_report_id=link.authoritative_evidence_id,
                run_evaluation_status="EVALUATED",
                run_evidence_manifest_id=f"run-manifest-{index + 1}",
                evaluation_binding_id=f"binding-{index + 1}",
                predecessor_binding_id=predecessor.binding_id,
                fold_materialization_manifest_ids=(
                    f"fold-{index + 1}-1",
                    f"fold-{index + 1}-2",
                    f"fold-{index + 1}-3",
                ),
            )
        )
    return protocol, plan, predecessor, checkpoint, tuple(parsed)


def _complete_progress():
    protocol, plan, predecessor, checkpoint, parsed = _context()
    progress = None
    for item in parsed:
        progress = advance_us_a0_formal_run_progress(
            previous=progress,
            execution_plan=plan,
            agent_checkpoint=checkpoint,
            predecessor=predecessor,
            parsed_run=item,
        )
    assert progress is not None
    checkpoint2 = build_formal_run_evidence_complete_checkpoint(
        agent_checkpoint=checkpoint,
        execution_plan=plan,
        progress=progress,
    )
    return protocol, plan, predecessor, checkpoint, parsed, progress, checkpoint2


def test_formal_financial_progress_commits_exact_seven_run_prefix() -> None:
    _, plan, _, checkpoint, parsed, progress, checkpoint2 = _complete_progress()

    assert progress.progress_ordinal == 7
    assert tuple(item.run_spec_id for item in progress.completed_runs) == tuple(
        spec.run_spec_id for spec in plan.run_specs
    )
    assert parse_us_a0_formal_run_progress(progress.to_dict()) == progress
    assert checkpoint2.state is USAgentValueFormalOrchestrationState.RUN_EVIDENCE_COMPLETE
    assert checkpoint2.previous_checkpoint_id == checkpoint.checkpoint_id
    assert checkpoint2.run_evidence_manifest_ids == tuple(
        item.run_evidence_manifest_id for item in parsed
    )


def test_formal_financial_progress_rejects_replacement_agent_sample() -> None:
    protocol, plan, predecessor, checkpoint, parsed = _context()
    progress = None
    for item in parsed[:4]:
        progress = advance_us_a0_formal_run_progress(
            previous=progress,
            execution_plan=plan,
            agent_checkpoint=checkpoint,
            predecessor=predecessor,
            parsed_run=item,
        )
    assert progress is not None
    original = parsed[4]
    replacement_run = build_candidate_generation_run(
        protocol,
        original.generation_run.spec,
        _agent_slots(999),
    )
    replacement = ParsedUSAgentValueRunEvidence(
        generation_run=replacement_run,
        evaluation_link=RunEvaluationLink(
            generation_run_id=replacement_run.run_id,
            authoritative_evidence_id="replacement-evaluation",
            evaluated_candidate_count=len(replacement_run.accepted_candidates),
            valid_candidate_count=len(replacement_run.accepted_candidates),
            best_mean_rank_ic=0.9,
            best_worst_fold_rank_ic=0.9,
        ),
        run_evaluation_report_id="replacement-evaluation",
        run_evaluation_status="EVALUATED",
        run_evidence_manifest_id="replacement-manifest",
        evaluation_binding_id="replacement-binding",
        predecessor_binding_id=predecessor.binding_id,
        fold_materialization_manifest_ids=("r1", "r2", "r3"),
    )

    with pytest.raises(ValueError, match="frozen generation checkpoint"):
        advance_us_a0_formal_run_progress(
            previous=progress,
            execution_plan=plan,
            agent_checkpoint=checkpoint,
            predecessor=predecessor,
            parsed_run=replacement,
        )


def test_formal_postrun_reuses_existing_gate_two_of_three_rule() -> None:
    protocol, plan, predecessor, _, parsed, progress, checkpoint2 = _complete_progress()
    policy = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL)
    artifacts = build_us_a0_formal_experiment_artifacts(
        protocol=protocol,
        execution_plan=plan,
        predecessor=predecessor,
        run_evidence=parsed,
        gate_policy=policy,
        run_checkpoint=checkpoint2,
        run_progress=progress,
    )

    assert artifacts.checkpoint.state is USAgentValueFormalOrchestrationState.EXPERIMENT_ASSEMBLED
    assert artifacts.assessment.required_paired_quality_win_count == 2
    assert artifacts.assessment.paired_quality_win_count == 2
    assert artifacts.assessment.decision is USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED
    assert artifacts.assembly_manifest.evidence_graph_id == artifacts.evidence_graph.graph_id
    assert (
        parse_us_a0_formal_experiment_assembly_manifest(
            artifacts.assembly_manifest.to_dict()
        )
        == artifacts.assembly_manifest
    )


def test_formal_review_has_agent_value_authority_but_not_alpha_authority() -> None:
    protocol, plan, predecessor, _, parsed, progress, checkpoint2 = _complete_progress()
    artifacts = build_us_a0_formal_experiment_artifacts(
        protocol=protocol,
        execution_plan=plan,
        predecessor=predecessor,
        run_evidence=parsed,
        gate_policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL),
        run_checkpoint=checkpoint2,
        run_progress=progress,
    )
    review = finalize_us_a0_agent_value_gate_review(
        artifacts.assessment,
        reviewer_id="formal-reviewer",
        reviewed_at=_NOW,
        review_notes="FORMAL evidence and frozen thresholds were independently reviewed.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        alpha_gate_separation_attested=True,
        stage_authority_separation_attested=True,
    )
    assert validate_us_a0_formal_gate_review_document(
        review.to_dict(),
        assessment=artifacts.assessment,
    ) == review
    checkpoint4 = build_us_a0_formal_gate_reviewed_checkpoint(
        experiment_checkpoint=artifacts.checkpoint,
        assembly_manifest=artifacts.assembly_manifest,
        review=review,
    )

    assert checkpoint4.state is USAgentValueFormalOrchestrationState.GATE_REVIEWED
    assert review.agent_value_gate_authority is True
    assert review.supports_agent_retention_for_us_r1 is True
    assert review.to_dict()["alpha_authority"] is False
    assert checkpoint4.to_dict()["alpha_authority"] is False


def test_formal_postrun_rejects_progress_from_different_agent_checkpoint() -> None:
    protocol, plan, predecessor, _, parsed, progress, checkpoint2 = _complete_progress()
    drifted = USAgentValueFormalRunProgress(
        launch_bundle_id=progress.launch_bundle_id,
        runtime_policy_id=progress.runtime_policy_id,
        execution_plan_id=progress.execution_plan_id,
        pilot_gate_review_id=progress.pilot_gate_review_id,
        agent_generation_checkpoint_id="different-agent-checkpoint",
        predecessor_binding_id=progress.predecessor_binding_id,
        completed_runs=progress.completed_runs,
        previous_progress_id=progress.previous_progress_id,
    )

    with pytest.raises(ValueError, match="checkpoint_01"):
        build_us_a0_formal_experiment_artifacts(
            protocol=protocol,
            execution_plan=plan,
            predecessor=predecessor,
            run_evidence=parsed,
            gate_policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL),
            run_checkpoint=checkpoint2,
            run_progress=drifted,
        )
