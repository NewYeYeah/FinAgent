from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_experiment import (
    AgentValueExperiment,
    RunEvaluationLink,
    bind_us_a0_predecessor,
    build_search_arm_result,
)
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
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import canonical_us_baseline_denominator

_NOW = datetime(2026, 9, 2, 5, 45, tzinfo=UTC)


def _hash(payload: object, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _b0_graph() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "finagent.us-baseline-walk-forward-evidence-graph.v1",
        "protocol_id": canonical_us_b0_pilot_walk_forward().protocol_id,
        "run_spec_id": "us-baseline-run-spec-test",
        "denominator_id": canonical_us_baseline_denominator().denominator_id,
        "fold_count": 3,
        "fold_manifests": [],
        "fold_manifest_ids": ["fold-1", "fold-2", "fold-3"],
        "fold_execution_spec_ids": ["exec-1", "exec-2", "exec-3"],
        "fold_materialization_report_ids": ["mat-1", "mat-2", "mat-3"],
        "fold_evaluation_report_ids": ["eval-1", "eval-2", "eval-3"],
        "aggregate_report_id": "us-baseline-walk-forward-aggregate-test",
        "aggregate_candidate_count": 8,
        "aggregate_valid_candidate_count": 8,
        "passed": True,
        "ready_for_us_a0_candidate": True,
        "blockers": [],
        "scope": "split_bound_manual_baseline_evidence_graph",
        "status_authority": False,
        "stage_exit_authority": False,
        "factor_selection_authority": False,
        "alpha_authority": False,
    }
    payload["graph_id"] = _hash(payload, "us-baseline-walk-forward-evidence")
    return payload


def _agent_run(protocol: object) -> object:
    raise AssertionError("helper must be specialized below")


def _pilot_runs():
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    manual = build_candidate_generation_run(
        protocol,
        canonical_manual_run_spec(protocol),
        manual_proposal_slots(protocol, generated_at=_NOW),
    )
    programmatic = build_candidate_generation_run(
        protocol,
        programmatic_run_spec(protocol, run_ordinal=1, random_seed=17),
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=17,
            generated_at=_NOW,
        ),
    )
    base_slots = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=23,
        generated_at=_NOW,
    )
    agent_slots = tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=slot.initial.kind,
                window_bars=slot.initial.window_bars,
                hypothesis_summary="Structured Agent proposal without hidden reasoning.",
                generated_at=_NOW,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=120,
                    output_tokens=24,
                    latency_ms=300.0,
                    cost_usd=0.002,
                ),
            )
        )
        for slot in base_slots
    )
    agent = build_candidate_generation_run(
        protocol,
        agent_run_spec(
            protocol,
            run_ordinal=1,
            provider_id="provider-test",
            model_id="model-test",
            prompt_template_id="prompt-template-v1",
        ),
        agent_slots,
    )
    return protocol, manual, programmatic, agent


def _link(run_id: str, count: int) -> RunEvaluationLink:
    return RunEvaluationLink(
        generation_run_id=run_id,
        authoritative_evidence_id=f"walk-forward-evidence-{run_id[-8:]}",
        evaluated_candidate_count=count,
        valid_candidate_count=count,
        best_mean_rank_ic=0.02,
        best_worst_fold_rank_ic=-0.01,
    )


def test_predecessor_binding_requires_exact_content_addressed_b0_graph() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    graph = _b0_graph()

    binding = bind_us_a0_predecessor(graph, protocol)

    assert binding.us_b0_evidence_graph_id == graph["graph_id"]
    assert binding.candidate_count == 8
    tampered = dict(graph)
    tampered["aggregate_valid_candidate_count"] = 7
    with pytest.raises(ValueError, match="content identity mismatch"):
        bind_us_a0_predecessor(tampered, protocol)


def test_pilot_experiment_requires_all_three_arms_but_does_not_auto_decide_gate() -> None:
    protocol, manual, programmatic, agent = _pilot_runs()
    predecessor = bind_us_a0_predecessor(_b0_graph(), protocol)
    manual_result = build_search_arm_result(
        protocol,
        USAgentValueArm.MANUAL,
        (manual,),
        (_link(manual.run_id, len(manual.accepted_candidates)),),
    )
    programmatic_result = build_search_arm_result(
        protocol,
        USAgentValueArm.PROGRAMMATIC,
        (programmatic,),
        (_link(programmatic.run_id, len(programmatic.accepted_candidates)),),
    )
    agent_result = build_search_arm_result(
        protocol,
        USAgentValueArm.AGENT,
        (agent,),
        (_link(agent.run_id, len(agent.accepted_candidates)),),
    )

    experiment = AgentValueExperiment(
        protocol=protocol,
        predecessor=predecessor,
        arm_results=(manual_result, programmatic_result, agent_result),
    )

    assert experiment.evidence_complete
    assert experiment.ready_for_agent_value_gate_review
    payload = experiment.to_dict()
    assert payload["agent_value_gate_decision"] == "UNDECIDED_REQUIRES_SEPARATE_REVIEW"
    assert payload["agent_value_gate_authority"] is False
    assert payload["alpha_authority"] is False
    assert agent_result.to_dict()["usage"]["llm_calls"] == 16  # type: ignore[index]


def test_formal_programmatic_arm_requires_three_distinct_seeded_runs() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)
    run = build_candidate_generation_run(
        protocol,
        programmatic_run_spec(protocol, run_ordinal=1, random_seed=101),
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=101,
            generated_at=_NOW,
        ),
    )
    with pytest.raises(ValueError, match="independent-run requirement"):
        build_search_arm_result(
            protocol,
            USAgentValueArm.PROGRAMMATIC,
            (run,),
            (_link(run.run_id, len(run.accepted_candidates)),),
        )

    runs = tuple(
        build_candidate_generation_run(
            protocol,
            programmatic_run_spec(protocol, run_ordinal=index, random_seed=seed),
            deterministic_programmatic_proposal_slots(
                protocol,
                random_seed=seed,
                generated_at=_NOW,
            ),
        )
        for index, seed in enumerate((101, 202, 303), start=1)
    )
    result = build_search_arm_result(
        protocol,
        USAgentValueArm.PROGRAMMATIC,
        runs,
        tuple(_link(run_item.run_id, len(run_item.accepted_candidates)) for run_item in runs),
    )
    assert result.passed
    assert len(result.generation_runs) == 3
