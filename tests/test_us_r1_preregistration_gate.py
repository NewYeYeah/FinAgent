from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.domain.market_bars import BarInterval
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
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
)
from finagent.research.us_r1_authority import (
    bind_authorized_us_r1_candidate_denominator,
    require_us_r1_stage_authority,
)
from finagent.research.us_r1_gate import (
    USR1FamilyEvidence,
    canonical_us_r1_alpha_gate_policy,
    assess_us_r1_alpha_gate,
    build_us_r1_family_evidence,
    build_us_r1_raw_candidate_evidence,
    finalize_us_r1_alpha_gate_review,
)
from finagent.research.us_r1_inference import USR1FoldSeries, USR1PeriodMetricPoint
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    USR1Terminal,
    build_us_r1_candidate_denominator,
    canonical_us_r1_research_protocol,
)

_NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def _agent_slots(protocol: USAgentValueExperimentProtocol, seed: int) -> tuple[ProposalSlot, ...]:
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
                hypothesis_summary="Structured Agent proposal for US-R1 predecessor regression.",
                generated_at=_NOW,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=100,
                    output_tokens=20,
                    latency_ms=200.0,
                    cost_usd=0.001,
                ),
            )
        )
        for slot in base
    )


def _link(run_id: str, count: int, *, robust: float, mean: float) -> RunEvaluationLink:
    return RunEvaluationLink(
        generation_run_id=run_id,
        authoritative_evidence_id=f"eval-{run_id[-12:]}",
        evaluated_candidate_count=count,
        valid_candidate_count=count,
        best_mean_rank_ic=mean,
        best_worst_fold_rank_ic=robust,
    )


def _pilot_experiment(*, agent_wins: bool):
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id="pilot-bundle-r1-test",
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
        manual_proposal_slots(protocol, generated_at=_NOW),
    )
    programmatic_run = build_candidate_generation_run(
        protocol,
        programmatic_spec,
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=1729,
            generated_at=_NOW,
        ),
    )
    agent_run = build_candidate_generation_run(
        protocol,
        agent_spec,
        _agent_slots(protocol, 8128),
    )
    manual_link = _link(manual_run.run_id, len(manual_run.accepted_candidates), robust=0.010, mean=0.020)
    programmatic_link = _link(
        programmatic_run.run_id,
        len(programmatic_run.accepted_candidates),
        robust=0.012,
        mean=0.022,
    )
    agent_link = _link(
        agent_run.run_id,
        len(agent_run.accepted_candidates),
        robust=0.032 if agent_wins else 0.009,
        mean=0.042 if agent_wins else 0.019,
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
        (programmatic_run,),
        (programmatic_link,),
    )
    agent_result = build_search_arm_result(
        protocol,
        USAgentValueArm.AGENT,
        (agent_run,),
        (agent_link,),
    )
    predecessor = USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id="b0-graph-r1-test",
        us_b0_aggregate_report_id="b0-aggregate-r1-test",
        us_b0_run_spec_id="b0-run-r1-test",
        us_b0_denominator_id="b0-denominator-r1-test",
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
    runs = tuple(run for result in ordered_results for run in result.generation_runs)
    links = tuple(link for result in ordered_results for link in result.evaluation_links)
    graph = AgentValueExperimentEvidenceGraph(
        execution_plan_id=plan.plan_id,
        preregistration_bundle_id=plan.preregistration_bundle_id,
        predecessor_binding_id=predecessor.binding_id,
        experiment_id=experiment.experiment_id,
        comparison_snapshot_id=comparison.snapshot_id,
        arm_result_ids=tuple(result.result_id for result in ordered_results),
        generation_run_ids=tuple(run.run_id for run in runs),
        run_evidence_manifest_ids=tuple(f"manifest-{index}" for index in range(len(runs))),
        run_evaluation_report_ids=tuple(link.authoritative_evidence_id for link in links),
        run_evaluation_link_ids=tuple(link.link_id for link in links),
        evidence_complete=True,
        ready_for_agent_value_gate_review=True,
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
        reviewer_id="r1-predecessor-reviewer",
        reviewed_at=_NOW,
        review_notes="A0 predecessor review is accepted under the preregistered Agent Value rules.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        alpha_gate_separation_attested=True,
        stage_authority_separation_attested=True,
    )
    return experiment, graph, review


def _fold(fold_id: str, start: datetime, *, weak: bool = False) -> USR1FoldSeries:
    points: list[USR1PeriodMetricPoint] = []
    for session_index in range(12):
        session_start = start + timedelta(days=session_index)
        for period_index in range(4):
            wiggle = ((session_index + period_index) % 5 - 2) * 0.001
            rank_ic = (0.004 if weak else 0.035) + wiggle
            points.append(
                USR1PeriodMetricPoint(
                    event_time=session_start + timedelta(minutes=15 * period_index),
                    session_id=f"{fold_id}-session-{session_index:02d}",
                    rank_ic=rank_ic,
                    long_short_return_bps=0.3 if weak else 3.0 + 10.0 * wiggle,
                    one_way_turnover=0.45,
                    coverage=0.95,
                    quantile_monotonicity=0.55,
                )
            )
    return USR1FoldSeries(fold_id=fold_id, points=tuple(points))


def _single_candidate_denominator() -> USR1CandidateDenominator:
    experiment, _, review = _pilot_experiment(agent_wins=False)
    full = build_us_r1_candidate_denominator(experiment, review)
    first = full.candidates[0]
    return USR1CandidateDenominator(
        protocol_id=full.protocol_id,
        a0_phase=full.a0_phase,
        a0_experiment_id=full.a0_experiment_id,
        a0_gate_review_id=full.a0_gate_review_id,
        a0_gate_decision=full.a0_gate_decision,
        agent_scope=full.agent_scope,
        candidates=(
            USR1CandidateProvenance(
                candidate=first.candidate,
                source_arms=first.source_arms,
                source_run_ids=first.source_run_ids,
            ),
        ),
    )


def _raw_candidate(denominator: USR1CandidateDenominator, *, weak: bool = False):
    candidate_id = denominator.candidates[0].candidate.candidate_id
    return build_us_r1_raw_candidate_evidence(
        candidate_id=candidate_id,
        dominant_direction=1,
        primary_folds=(
            _fold("fold-1", _NOW, weak=weak),
            _fold("fold-2", _NOW + timedelta(days=20), weak=weak),
            _fold("fold-3", _NOW + timedelta(days=40), weak=weak),
        ),
        robustness_rank_ic={
            BarInterval.MINUTE_5: 0.028 if not weak else -0.002,
            BarInterval.MINUTE_30: 0.022 if not weak else 0.001,
        },
        decay_rank_ic={
            30: 0.030 if not weak else 0.003,
            120: 0.018 if not weak else -0.001,
        },
    )


def test_us_r1_protocol_freezes_intraday_dependence_semantics() -> None:
    protocol = canonical_us_r1_research_protocol()
    assert protocol.primary_interval is BarInterval.MINUTE_15
    assert protocol.robustness_intervals == (BarInterval.MINUTE_5, BarInterval.MINUTE_30)
    assert protocol.label_horizon_trading_minutes == 60
    assert protocol.decay_horizon_trading_minutes == (30, 120)
    assert protocol.purge_trading_minutes == 60
    assert protocol.embargo_trading_minutes == 60
    assert protocol.hac_lags(BarInterval.MINUTE_5) == 12
    assert protocol.hac_lags(BarInterval.MINUTE_15) == 4
    assert protocol.hac_lags(BarInterval.MINUTE_30) == 2
    assert protocol.bootstrap_block_sessions == 5
    assert protocol.to_dict()["annualization_semantics"] == (
        "presentation_only_frequency_aware_never_used_as_statistical_sample_size"
    )


def test_us_r1_denominator_keeps_agent_candidates_even_when_agent_scope_contracts() -> None:
    experiment, _, review = _pilot_experiment(agent_wins=False)
    assert review.decision is USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL
    denominator = build_us_r1_candidate_denominator(experiment, review)
    assert denominator.agent_scope is USR1AgentScope.CONTRACTED
    agent_ids = {
        candidate.candidate_id
        for result in experiment.arm_results
        if result.arm is USAgentValueArm.AGENT
        for run in result.generation_runs
        for candidate in run.accepted_candidates
    }
    admitted_ids = {item.candidate.candidate_id for item in denominator.candidates}
    assert agent_ids <= admitted_ids
    assert denominator.to_dict()["performance_filter_applied"] is False


def test_us_r1_rejects_nonterminal_pilot_review() -> None:
    experiment, _, review = _pilot_experiment(agent_wins=True)
    assert review.decision is USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL
    with pytest.raises(ValueError, match="requires FORMAL continuation"):
        build_us_r1_candidate_denominator(experiment, review)


def test_us_r1_stage_authority_binds_exact_a0_terminal_evidence() -> None:
    experiment, graph, review = _pilot_experiment(agent_wins=False)
    status = {
        "current_stage": "US-R1",
        "stage": {
            "us_a0": {
                "status": "accepted",
                "stage_exit_gate_passed": True,
                "terminal_gate_review_id": review.review_id,
                "experiment_id": experiment.experiment_id,
                "evidence_graph_id": graph.graph_id,
            }
        },
    }
    authority = require_us_r1_stage_authority(status)
    assert authority.a0_terminal_gate_review_id == review.review_id
    denominator = bind_authorized_us_r1_candidate_denominator(status, experiment, review)
    assert denominator.a0_gate_review_id == review.review_id
    drifted = {**status, "current_stage": "US-A0"}
    with pytest.raises(ValueError, match="current_stage=US-R1"):
        require_us_r1_stage_authority(drifted)


def test_us_r1_alpha_gate_supports_robust_family_with_dependence_and_multiplicity() -> None:
    denominator = _single_candidate_denominator()
    raw = _raw_candidate(denominator, weak=False)
    family = build_us_r1_family_evidence(denominator, (raw,))
    policy = canonical_us_r1_alpha_gate_policy()
    assessment = assess_us_r1_alpha_gate(family, policy)
    assert assessment.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY
    assert assessment.robust_candidate_ids == (denominator.candidates[0].candidate.candidate_id,)
    assert family.candidates[0].holm_adjusted_pvalue <= policy.max_holm_adjusted_pvalue
    assert raw.session_bootstrap_ci_lower > 0.0
    review = finalize_us_r1_alpha_gate_review(
        assessment,
        reviewer_id="alpha-reviewer",
        reviewed_at=_NOW,
        review_notes="The preregistered robust Alpha assessment and complete evidence lineage are accepted.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        agent_value_gate_separation_attested=True,
        execution_gate_separation_attested=True,
        live_capital_separation_attested=True,
    )
    assert review.alpha_authority
    assert review.supports_us_x0_progression
    assert review.to_dict()["order_authority"] is False
    assert review.to_dict()["live_capital_authority"] is False


def test_us_r1_alpha_gate_returns_no_robust_family_for_weak_complete_evidence() -> None:
    denominator = _single_candidate_denominator()
    family = build_us_r1_family_evidence(denominator, (_raw_candidate(denominator, weak=True),))
    assessment = assess_us_r1_alpha_gate(family)
    assert assessment.terminal is USR1Terminal.NO_ROBUST_FACTOR_FAMILY
    assert not assessment.robust_candidate_ids
    assert assessment.candidates[0].reasons


def test_us_r1_system_failure_is_not_relabelled_as_no_alpha() -> None:
    denominator = _single_candidate_denominator()
    raw = _raw_candidate(denominator, weak=False)
    complete = build_us_r1_family_evidence(denominator, (raw,))
    family = USR1FamilyEvidence(
        protocol_id=complete.protocol_id,
        denominator_id=complete.denominator_id,
        candidates=complete.candidates,
        technical_blockers=("missing_frequency_materialization",),
    )
    assessment = assess_us_r1_alpha_gate(family)
    assert assessment.terminal is USR1Terminal.SYSTEM_FAILURE
    assert assessment.technical_blockers == ("missing_frequency_materialization",)


def test_us_r1_review_cannot_upgrade_no_robust_family() -> None:
    denominator = _single_candidate_denominator()
    family = build_us_r1_family_evidence(denominator, (_raw_candidate(denominator, weak=True),))
    assessment = assess_us_r1_alpha_gate(family)
    assert assessment.terminal is USR1Terminal.NO_ROBUST_FACTOR_FAMILY
    with pytest.raises(ValueError, match="accept the assessment or downgrade to SYSTEM_FAILURE"):
        finalize_us_r1_alpha_gate_review(
            assessment,
            reviewer_id="alpha-reviewer",
            reviewed_at=_NOW,
            review_notes="Unsupported review upgrade must be rejected.",
            terminal=USR1Terminal.ROBUST_FACTOR_FAMILY,
            thresholds_unchanged_attested=True,
            evidence_lineage_attested=True,
            agent_value_gate_separation_attested=True,
            execution_gate_separation_attested=True,
            live_capital_separation_attested=True,
        )
