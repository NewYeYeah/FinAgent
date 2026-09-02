from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_assembly import (
    assemble_us_a0_experiment_evidence,
    parse_us_a0_run_evidence_bundle,
)
from finagent.research.us_agent_value_evaluation import (
    USAgentValueCandidateEvaluationAggregate,
    USAgentValueRunEvaluationReport,
    USAgentValueRunEvaluationStatus,
    build_run_evaluation_link,
)
from finagent.research.us_agent_value_execution import (
    USAgentValueExecutionPlan,
    USAgentValueFoldMaterializationManifest,
    USAgentValueRunEvidenceManifest,
    build_us_a0_execution_plan,
)
from finagent.research.us_agent_value_experiment import (
    RunEvaluationLink,
    USAgentValuePredecessorBinding,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRun,
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    build_candidate_generation_run,
    canonical_manual_run_spec,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baseline_materialization import USBaselineMaterializationDiagnostics
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import canonical_us_baseline_denominator


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
        "phase": protocol.phase.value,
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


def _plan() -> USAgentValueExecutionPlan:
    preregistration = _preregistration()
    return build_us_a0_execution_plan(
        canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT),
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=(1729,),
        agent_provider_id="provider-test",
        agent_model_id="model-test",
        agent_prompt_template_id="prompt-test",
    )


def _predecessor() -> USAgentValuePredecessorBinding:
    return USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id="us-b0-graph-test",
        us_b0_aggregate_report_id="us-b0-aggregate-test",
        us_b0_run_spec_id="us-b0-run-spec-test",
        us_b0_denominator_id=canonical_us_baseline_denominator().denominator_id,
        us_b0_walk_forward_protocol_id=canonical_us_b0_pilot_walk_forward().protocol_id,
        candidate_count=8,
    )


def _agent_slots(count: int) -> tuple[ProposalSlot, ...]:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    candidates = vocabulary.all_candidates()[:count]
    timestamp = datetime(2026, 9, 2, 5, 0, tzinfo=UTC)
    return tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=candidate.kind.value,
                window_bars=candidate.window_bars,
                hypothesis_summary="Synthetic structured Agent proposal for assembly regression.",
                generated_at=timestamp,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=20,
                    output_tokens=8,
                    latency_ms=50.0,
                    cost_usd=0.001,
                ),
            )
        )
        for candidate in candidates
    )


def _runs(plan: USAgentValueExecutionPlan) -> tuple[CandidateGenerationRun, ...]:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    manual_spec = canonical_manual_run_spec(protocol)
    programmatic_spec = next(
        item for item in plan.run_specs if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    agent_spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    return (
        build_candidate_generation_run(
            protocol,
            manual_spec,
            manual_proposal_slots(protocol, generated_at=datetime(2026, 9, 2, 5, 0, tzinfo=UTC)),
        ),
        build_candidate_generation_run(
            protocol,
            programmatic_spec,
            deterministic_programmatic_proposal_slots(
                protocol,
                random_seed=1729,
                generated_at=datetime(2026, 9, 2, 5, 1, tzinfo=UTC),
            ),
        ),
        build_candidate_generation_run(protocol, agent_spec, _agent_slots(16)),
    )


def _diagnostics() -> USBaselineMaterializationDiagnostics:
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
        blockers=(),
    )


def _artifacts(
    plan: USAgentValueExecutionPlan,
    predecessor: USAgentValuePredecessorBinding,
    run: CandidateGenerationRun,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    binding_id = f"evaluation-binding-{run.run_id}"
    denominator_id = f"denominator-{run.run_id}"
    statistical_run_spec_id = f"statistical-run-spec-{run.run_id}"
    candidates = tuple(
        USAgentValueCandidateEvaluationAggregate(
            candidate_id=candidate.candidate_id,
            feature_id=candidate.compile_feature_spec().feature_id,
            feature_spec_id=candidate.compile_feature_spec().spec_id,
            fold_count=3,
            valid_fold_count=3,
            mean_rank_ic=0.01 + index / 10000.0,
            worst_fold_rank_ic=0.005 + index / 10000.0,
            mean_gross_return=0.001,
            worst_fold_gross_return=-0.001,
            mean_one_way_turnover=0.25,
            maximum_one_way_turnover=0.4,
            mean_feature_coverage=1.0,
            invalid_reasons=(),
        )
        for index, candidate in enumerate(run.accepted_candidates)
    )
    fold_evaluation_ids = tuple(f"fold-evaluation-{run.run_id}-{index}" for index in (1, 2, 3))
    report = USAgentValueRunEvaluationReport(
        evaluation_binding_id=binding_id,
        generation_run_id=run.run_id,
        arm=run.spec.arm,
        denominator_id=denominator_id,
        run_spec_id=statistical_run_spec_id,
        status=USAgentValueRunEvaluationStatus.EVALUATED,
        fold_evaluation_report_ids=fold_evaluation_ids,
        candidates=candidates,
    )
    link = build_run_evaluation_link(run, report)
    fold_manifests = tuple(
        USAgentValueFoldMaterializationManifest(
            execution_plan_id=plan.plan_id,
            preregistration_bundle_id=plan.preregistration_bundle_id,
            generation_run_id=run.run_id,
            evaluation_binding_id=binding_id,
            fold_execution_spec_id=f"fold-execution-{run.run_id}-{index}",
            fold_ordinal=index,
            input_plan_id=f"input-plan-{run.run_id}-{index}",
            input_materialization_id=f"input-materialization-{run.run_id}-{index}",
            observation_artifact_id=f"observations-{run.run_id}-{index}",
            diagnostics=_diagnostics(),
            fold_evaluation_report_id=fold_evaluation_ids[index - 1],
            engineering_asset_count=20,
        )
        for index in (1, 2, 3)
    )
    manifest = USAgentValueRunEvidenceManifest(
        execution_plan_id=plan.plan_id,
        preregistration_bundle_id=plan.preregistration_bundle_id,
        predecessor_binding_id=predecessor.binding_id,
        generation_run_id=run.run_id,
        generation_run_spec_id=run.spec.run_spec_id,
        evaluation_binding_id=binding_id,
        arm=run.spec.arm,
        phase=run.spec.phase,
        fold_manifests=fold_manifests,
        run_evaluation_report_id=report.report_id,
        run_evaluation_link_id=link.link_id,
        run_evaluation_status=report.status,
    )
    return run.to_dict(), report.to_dict(), link.to_dict(), manifest.to_dict()


def test_three_arm_experiment_assembly_preserves_exact_execution_plan() -> None:
    plan = _plan()
    predecessor = _predecessor()
    parsed = tuple(
        parse_us_a0_run_evidence_bundle(
            execution_plan=plan,
            predecessor=predecessor,
            generation_document=generation,
            run_evaluation_document=evaluation,
            evaluation_link_document=link,
            run_manifest_document=manifest,
        )
        for generation, evaluation, link, manifest in (
            _artifacts(plan, predecessor, run) for run in _runs(plan)
        )
    )

    arms, experiment, comparison, graph = assemble_us_a0_experiment_evidence(
        protocol=canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT),
        execution_plan=plan,
        predecessor=predecessor,
        run_evidence=parsed,
    )

    assert tuple(item.arm for item in arms) == (
        USAgentValueArm.MANUAL,
        USAgentValueArm.PROGRAMMATIC,
        USAgentValueArm.AGENT,
    )
    assert experiment.evidence_complete
    assert experiment.ready_for_agent_value_gate_review
    assert comparison.to_dict()["agent_value_gate_decision"] == "UNDECIDED_REQUIRES_SEPARATE_REVIEW"
    assert graph.evidence_complete
    assert graph.ready_for_agent_value_gate_review
    assert len(graph.generation_run_ids) == 3
    assert graph.to_dict()["agent_value_gate_authority"] is False


def test_experiment_assembly_rejects_missing_planned_run() -> None:
    plan = _plan()
    predecessor = _predecessor()
    runs = _runs(plan)
    parsed = tuple(
        parse_us_a0_run_evidence_bundle(
            execution_plan=plan,
            predecessor=predecessor,
            generation_document=generation,
            run_evaluation_document=evaluation,
            evaluation_link_document=link,
            run_manifest_document=manifest,
        )
        for generation, evaluation, link, manifest in (
            _artifacts(plan, predecessor, run) for run in runs[:2]
        )
    )

    with pytest.raises(ValueError, match="does not match execution plan"):
        assemble_us_a0_experiment_evidence(
            protocol=canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT),
            execution_plan=plan,
            predecessor=predecessor,
            run_evidence=parsed,
        )


def test_run_evidence_parser_rejects_semantically_forged_valid_candidate_summary() -> None:
    plan = _plan()
    predecessor = _predecessor()
    run = _runs(plan)[0]
    generation, evaluation, _, manifest_document = _artifacts(plan, predecessor, run)

    evaluation["valid_candidate_count"] = 0
    report_payload = dict(evaluation)
    report_payload.pop("report_id")
    forged_report_id = _hash(report_payload, "us-agent-value-run-evaluation")
    evaluation["report_id"] = forged_report_id
    forged_link = RunEvaluationLink(
        generation_run_id=run.run_id,
        authoritative_evidence_id=forged_report_id,
        evaluated_candidate_count=len(run.accepted_candidates),
        valid_candidate_count=0,
        best_mean_rank_ic=float(evaluation["best_mean_rank_ic"]),
        best_worst_fold_rank_ic=float(evaluation["best_worst_fold_rank_ic"]),
        blockers=(),
    )
    manifest_document["run_evaluation_report_id"] = forged_report_id
    manifest_document["run_evaluation_link_id"] = forged_link.link_id
    manifest_payload = dict(manifest_document)
    manifest_payload.pop("manifest_id")
    manifest_document["manifest_id"] = _hash(manifest_payload, "us-agent-value-run-evidence")

    with pytest.raises(ValueError, match="valid candidate count"):
        parse_us_a0_run_evidence_bundle(
            execution_plan=plan,
            predecessor=predecessor,
            generation_document=generation,
            run_evaluation_document=evaluation,
            evaluation_link_document=forged_link.to_dict(),
            run_manifest_document=manifest_document,
        )
