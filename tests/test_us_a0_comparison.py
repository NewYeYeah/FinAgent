from __future__ import annotations

from datetime import UTC, datetime

from finagent.research.us_agent_value_comparison import (
    build_agent_value_comparison_snapshot,
    summarize_structural_novelty,
)
from finagent.research.us_agent_value_experiment import RunEvaluationLink, build_search_arm_result
from finagent.research.us_agent_value_generation import (
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    agent_run_spec,
    build_candidate_generation_run,
    canonical_manual_run_spec,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
    programmatic_run_spec,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
)

_NOW = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)


def _link(run_id: str, count: int) -> RunEvaluationLink:
    return RunEvaluationLink(
        generation_run_id=run_id,
        authoritative_evidence_id=f"evaluation-{run_id[-10:]}",
        evaluated_candidate_count=count,
        valid_candidate_count=count,
        best_mean_rank_ic=0.01,
        best_worst_fold_rank_ic=-0.01,
    )


def test_structural_novelty_uses_formula_ids_not_wording() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    manual_run = build_candidate_generation_run(
        protocol,
        canonical_manual_run_spec(protocol),
        manual_proposal_slots(protocol, generated_at=_NOW),
    )
    programmatic_run = build_candidate_generation_run(
        protocol,
        programmatic_run_spec(protocol, run_ordinal=1, random_seed=71),
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=71,
            generated_at=_NOW,
        ),
    )
    agent_base = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=71,
        generated_at=_NOW,
    )
    agent_slots = tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=slot.initial.kind,
                window_bars=slot.initial.window_bars,
                hypothesis_summary="Agent words differ, structural formula does not.",
                generated_at=_NOW,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=50,
                    output_tokens=10,
                    latency_ms=100.0,
                    cost_usd=0.001,
                ),
            )
        )
        for slot in agent_base
    )
    agent_run = build_candidate_generation_run(
        protocol,
        agent_run_spec(
            protocol,
            run_ordinal=1,
            provider_id="provider-test",
            model_id="model-test",
            prompt_template_id="prompt-test",
        ),
        agent_slots,
    )

    manual = build_search_arm_result(
        protocol,
        USAgentValueArm.MANUAL,
        (manual_run,),
        (_link(manual_run.run_id, len(manual_run.accepted_candidates)),),
    )
    programmatic = build_search_arm_result(
        protocol,
        USAgentValueArm.PROGRAMMATIC,
        (programmatic_run,),
        (_link(programmatic_run.run_id, len(programmatic_run.accepted_candidates)),),
    )
    agent = build_search_arm_result(
        protocol,
        USAgentValueArm.AGENT,
        (agent_run,),
        (_link(agent_run.run_id, len(agent_run.accepted_candidates)),),
    )

    novelty = summarize_structural_novelty(manual, programmatic, agent)
    snapshot = build_agent_value_comparison_snapshot(manual, programmatic, agent)

    assert novelty.agent_candidate_ids == novelty.programmatic_candidate_ids
    assert novelty.agent_programmatic_overlap == novelty.agent_candidate_ids
    assert novelty.agent_novel_vs_manual == novelty.programmatic_novel_vs_manual
    assert novelty.agent_novel_vs_manual_and_programmatic == ()
    assert snapshot.to_dict()["agent_value_gate_authority"] is False
    assert snapshot.to_dict()["agent_value_gate_decision"] == "UNDECIDED_REQUIRES_SEPARATE_REVIEW"
