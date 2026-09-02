from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_assembly import AgentValueExperimentEvidenceGraph
from finagent.research.us_agent_value_comparison import build_agent_value_comparison_snapshot
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_experiment import (
    AgentValueExperiment,
    RunEvaluationLink,
    USAgentValuePredecessorBinding,
    build_search_arm_result,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    assess_us_a0_agent_value_gate,
    canonical_us_a0_agent_value_gate_policy,
    finalize_us_a0_agent_value_gate_review,
    validate_pilot_gate_review_for_formal_progression,
    validate_us_a0_agent_value_gate_policy,
)
from finagent.research.us_agent_value_generation import (
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

_NOW = datetime(2026, 9, 2, 6, 30, tzinfo=UTC)


def _agent_slots(protocol: object, seed: int) -> tuple[ProposalSlot, ...]:
    base = deterministic_programmatic_proposal_slots(  # type: ignore[arg-type]
        protocol,
        random_seed=seed,
        generated_at=_NOW,
    )
    return tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=slot.initial.kind,
                window_bars=slot.initial.window_bars,
                hypothesis_summary="Structured Agent proposal for Gate regression.",
                generated_at=_NOW,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=100,
                    output_tokens=20,
                    latency_ms=250.0,
                    cost_usd=0.002,
                ),
            )
        )
        for slot in base
    )


def _link(run_id: str, count: int, *, robust: float, mean: float) -> RunEvaluationLink:
    return RunEvaluationLink(
        generation_run_id=run_id,
        authoritative_evidence_id=f"run-evaluation-{run_id[-12:]}",
        evaluated_candidate_count=count,
        valid_candidate_count=count,
        best_mean_rank_ic=mean,
        best_worst_fold_rank_ic=robust,
    )


def _experiment_context(
    phase: USAgentValuePhase,
    *,
    manual_metrics: tuple[float, float],
    programmatic_metrics: tuple[tuple[float, float], ...],
    agent_metrics: tuple[tuple[float, float], ...],
):
    protocol = canonical_us_a0_experiment_protocol(phase)
    seeds = tuple(100 + index for index in range(1, len(programmatic_metrics) + 1))
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=f"bundle-{phase.value.lower()}-test",
        programmatic_seeds=seeds,
        agent_provider_id="provider-test",
        agent_model_id="model-test",
        agent_prompt_template_id="prompt-test",
    )
    manual_spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.MANUAL)
    manual_run = build_candidate_generation_run(
        protocol,
        manual_spec,
        manual_proposal_slots(protocol, generated_at=_NOW),
    )
    programmatic_specs = tuple(
        item for item in plan.run_specs if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    agent_specs = tuple(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    programmatic_runs = tuple(
        build_candidate_generation_run(
            protocol,
            spec,
            deterministic_programmatic_proposal_slots(
                protocol,
                random_seed=int(spec.random_seed),
                generated_at=_NOW,
            ),
        )
        for spec in programmatic_specs
    )
    agent_runs = tuple(
        build_candidate_generation_run(
            protocol,
            spec,
            _agent_slots(protocol, 700 + index),
        )
        for index, spec in enumerate(agent_specs, start=1)
    )

    manual_link = _link(
        manual_run.run_id,
        len(manual_run.accepted_candidates),
        robust=manual_metrics[0],
        mean=manual_metrics[1],
    )
    programmatic_links = tuple(
        _link(
            run.run_id,
            len(run.accepted_candidates),
            robust=metrics[0],
            mean=metrics[1],
        )
        for run, metrics in zip(programmatic_runs, programmatic_metrics, strict=True)
    )
    agent_links = tuple(
        _link(
            run.run_id,
            len(run.accepted_candidates),
            robust=metrics[0],
            mean=metrics[1],
        )
        for run, metrics in zip(agent_runs, agent_metrics, strict=True)
    )
    manual_result = build_search_arm_result(
        protocol,
        USAgentValueArm.MANUAL,
        (manual_run,),
        (manual_link,),
    )
    programmatic_result = build_search_arm_result(
        protocol,
        USAgentValueArm.PROGRAMMATIC,
        programmatic_runs,
        programmatic_links,
    )
    agent_result = build_search_arm_result(
        protocol,
        USAgentValueArm.AGENT,
        agent_runs,
        agent_links,
    )
    predecessor = USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id="b0-graph-test",
        us_b0_aggregate_report_id="b0-aggregate-test",
        us_b0_run_spec_id="b0-run-spec-test",
        us_b0_denominator_id="b0-denominator-test",
        us_b0_walk_forward_protocol_id=protocol.us_b0_walk_forward_protocol_id,
        candidate_count=8,
    )
    experiment = AgentValueExperiment(
        protocol=protocol,
        predecessor=predecessor,
        arm_results=(manual_result, programmatic_result, agent_result),
    )
    comparison = build_agent_value_comparison_snapshot(
        manual_result,
        programmatic_result,
        agent_result,
    )
    ordered_results = experiment.arm_results
    generation_runs = tuple(run for result in ordered_results for run in result.generation_runs)
    links = tuple(link for result in ordered_results for link in result.evaluation_links)
    graph = AgentValueExperimentEvidenceGraph(
        execution_plan_id=plan.plan_id,
        preregistration_bundle_id=plan.preregistration_bundle_id,
        predecessor_binding_id=predecessor.binding_id,
        experiment_id=experiment.experiment_id,
        comparison_snapshot_id=comparison.snapshot_id,
        arm_result_ids=tuple(result.result_id for result in ordered_results),
        generation_run_ids=tuple(run.run_id for run in generation_runs),
        run_evidence_manifest_ids=tuple(
            f"run-manifest-{index}-{run.run_id[-8:]}"
            for index, run in enumerate(generation_runs, start=1)
        ),
        run_evaluation_report_ids=tuple(link.authoritative_evidence_id for link in links),
        run_evaluation_link_ids=tuple(link.link_id for link in links),
        evidence_complete=True,
        ready_for_agent_value_gate_review=True,
    )
    return plan, experiment, comparison, graph


def test_gate_policy_is_frozen_before_results_and_separate_from_alpha() -> None:
    pilot = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT)
    formal = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL)

    assert pilot.practical_rank_ic_margin == 0.01
    assert pilot.required_agent_run_wins(1) == 1
    assert formal.required_agent_run_wins(3) == 2
    assert pilot.to_dict()["agent_value_gate_authority"] is False
    assert formal.to_dict()["alpha_authority"] is False
    assert validate_us_a0_agent_value_gate_policy(pilot.to_dict(), USAgentValuePhase.PILOT) == pilot

    drifted = dict(pilot.to_dict())
    drifted["practical_rank_ic_margin"] = 0.0
    with pytest.raises(ValueError, match="exact frozen canonical policy"):
        validate_us_a0_agent_value_gate_policy(drifted, USAgentValuePhase.PILOT)


def test_pilot_positive_rule_allows_formal_but_does_not_claim_agent_value() -> None:
    plan, experiment, comparison, graph = _experiment_context(
        USAgentValuePhase.PILOT,
        manual_metrics=(0.010, 0.020),
        programmatic_metrics=((0.012, 0.022),),
        agent_metrics=((0.030, 0.040),),
    )
    assert len(comparison.novelty.agent_novel_vs_manual_and_programmatic) >= 1
    policy = canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT)

    assessment = assess_us_a0_agent_value_gate(
        policy=policy,
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )

    assert assessment.decision is USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL
    assert assessment.positive_rule_passed
    assert assessment.paired_quality_win_count == 1
    assert assessment.to_dict()["agent_value_gate_authority"] is False


def test_pilot_clear_non_superiority_does_not_proceed_to_formal() -> None:
    plan, experiment, comparison, graph = _experiment_context(
        USAgentValuePhase.PILOT,
        manual_metrics=(0.010, 0.020),
        programmatic_metrics=((0.012, 0.022),),
        agent_metrics=((0.009, 0.019),),
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT),
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )

    assert assessment.decision is USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL
    assert assessment.quality_not_better
    assert not assessment.meaningful_efficiency_advantage


def test_pilot_small_unpreregistered_effect_is_inconclusive_not_a_win() -> None:
    plan, experiment, comparison, graph = _experiment_context(
        USAgentValuePhase.PILOT,
        manual_metrics=(0.010, 0.020),
        programmatic_metrics=((0.012, 0.022),),
        agent_metrics=((0.017, 0.027),),
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT),
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )

    assert assessment.decision is USAgentValueGateDecision.INCONCLUSIVE
    assert not assessment.positive_rule_passed
    assert not assessment.quality_not_better


def test_formal_requires_repeatable_two_of_three_quality_wins() -> None:
    plan, experiment, comparison, graph = _experiment_context(
        USAgentValuePhase.FORMAL,
        manual_metrics=(0.010, 0.020),
        programmatic_metrics=((0.012, 0.022), (0.011, 0.021), (0.013, 0.023)),
        agent_metrics=((0.030, 0.040), (0.031, 0.041), (0.015, 0.025)),
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL),
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )

    assert assessment.required_paired_quality_win_count == 2
    assert assessment.paired_quality_win_count == 2
    assert assessment.decision is USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED


def test_formal_clear_non_superiority_is_no_incremental_value() -> None:
    plan, experiment, comparison, graph = _experiment_context(
        USAgentValuePhase.FORMAL,
        manual_metrics=(0.010, 0.020),
        programmatic_metrics=((0.012, 0.022), (0.011, 0.021), (0.013, 0.023)),
        agent_metrics=((0.010, 0.020), (0.009, 0.019), (0.011, 0.021)),
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL),
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )

    assert assessment.decision is USAgentValueGateDecision.FORMAL_NO_INCREMENTAL_VALUE
    assert assessment.quality_not_better


def test_review_cannot_upgrade_machine_assessment_and_keeps_alpha_separate() -> None:
    plan, experiment, comparison, graph = _experiment_context(
        USAgentValuePhase.FORMAL,
        manual_metrics=(0.010, 0.020),
        programmatic_metrics=((0.012, 0.022), (0.011, 0.021), (0.013, 0.023)),
        agent_metrics=((0.010, 0.020), (0.009, 0.019), (0.011, 0.021)),
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.FORMAL),
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )

    with pytest.raises(ValueError, match="downgrade it to INCONCLUSIVE only"):
        finalize_us_a0_agent_value_gate_review(
            assessment,
            reviewer_id="reviewer-test",
            reviewed_at=_NOW,
            review_notes="Attempted unsupported upgrade should fail.",
            decision=USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED,
            thresholds_unchanged_attested=True,
            evidence_lineage_attested=True,
            alpha_gate_separation_attested=True,
            stage_authority_separation_attested=True,
        )

    review = finalize_us_a0_agent_value_gate_review(
        assessment,
        reviewer_id="reviewer-test",
        reviewed_at=_NOW,
        review_notes="The preregistered assessment is accepted without changing thresholds.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        alpha_gate_separation_attested=True,
        stage_authority_separation_attested=True,
    )
    assert review.agent_value_gate_authority
    assert review.supports_agent_scope_contraction
    assert review.to_dict()["alpha_authority"] is False
    assert review.to_dict()["stage_exit_authority"] is False


def test_pilot_review_authorizes_formal_only_when_status_binds_exact_review_id() -> None:
    plan, experiment, comparison, graph = _experiment_context(
        USAgentValuePhase.PILOT,
        manual_metrics=(0.010, 0.020),
        programmatic_metrics=((0.012, 0.022),),
        agent_metrics=((0.030, 0.040),),
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT),
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )
    review = finalize_us_a0_agent_value_gate_review(
        assessment,
        reviewer_id="reviewer-test",
        reviewed_at=_NOW,
        review_notes="PILOT evidence meets the preregistered practical-value criteria for FORMAL.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        alpha_gate_separation_attested=True,
        stage_authority_separation_attested=True,
    )

    assert review.formal_progression_authority
    assert not review.agent_value_gate_authority
    assert validate_pilot_gate_review_for_formal_progression(
        review.to_dict(),
        expected_review_id=review.review_id,
    ) == review.review_id
    with pytest.raises(ValueError, match="docs/status.toml authority"):
        validate_pilot_gate_review_for_formal_progression(
            review.to_dict(),
            expected_review_id="different-review-id",
        )
