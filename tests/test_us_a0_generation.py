from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_generation import (
    CandidateGenerationUsage,
    CandidateValidationStatus,
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
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_primitive_vocabulary,
)

_NOW = datetime(2026, 9, 2, 5, 30, tzinfo=UTC)
_AGENT_USAGE = CandidateGenerationUsage(
    llm_calls=1,
    input_tokens=100,
    output_tokens=20,
    latency_ms=250.0,
    cost_usd=0.001,
)


def _agent_proposal(kind: str, window_bars: int, summary: str) -> StructuredCandidateProposal:
    return StructuredCandidateProposal(
        kind=kind,
        window_bars=window_bars,
        hypothesis_summary=summary,
        generated_at=_NOW,
        usage=_AGENT_USAGE,
    )


def test_manual_run_is_exact_preregistered_grid() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    run = build_candidate_generation_run(
        protocol,
        canonical_manual_run_spec(protocol),
        manual_proposal_slots(protocol, generated_at=_NOW),
    )

    assert len(run.accepted_candidates) == 16
    assert tuple(item.candidate_id for item in run.accepted_candidates) == protocol.manual_candidate_ids
    assert run.invalid_slot_count == 0
    assert run.duplicate_slot_count == 0
    assert run.repair_count == 0
    assert run.usage.llm_calls == 0


def test_programmatic_run_is_seeded_bounded_and_without_replacement() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    left_slots = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=11,
        generated_at=_NOW,
    )
    right_slots = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=11,
        generated_at=_NOW,
    )
    other_slots = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=12,
        generated_at=_NOW,
    )
    left = build_candidate_generation_run(
        protocol,
        programmatic_run_spec(protocol, run_ordinal=1, random_seed=11),
        left_slots,
    )

    assert [(item.initial.kind, item.initial.window_bars) for item in left_slots] == [
        (item.initial.kind, item.initial.window_bars) for item in right_slots
    ]
    assert [(item.initial.kind, item.initial.window_bars) for item in left_slots] != [
        (item.initial.kind, item.initial.window_bars) for item in other_slots
    ]
    assert len(left.accepted_candidates) == 16
    assert len({item.candidate_id for item in left.accepted_candidates}) == 16
    assert left.spec.random_seed == 11


def test_same_formula_with_different_wording_is_duplicate_and_consumes_slot() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    candidates = canonical_us_a0_primitive_vocabulary().all_candidates()
    slots: list[ProposalSlot] = [
        ProposalSlot(
            initial=_agent_proposal(
                candidates[0].kind.value,
                candidates[0].window_bars,
                "first wording",
            )
        ),
        ProposalSlot(
            initial=_agent_proposal(
                candidates[0].kind.value,
                candidates[0].window_bars,
                "completely different wording for the same formula",
            )
        ),
        ProposalSlot(initial=_agent_proposal("unsupported_magic", 2, "invalid structured kind")),
    ]
    slots.extend(
        ProposalSlot(
            initial=_agent_proposal(candidate.kind.value, candidate.window_bars, "unique proposal")
        )
        for candidate in candidates[1:14]
    )
    spec = agent_run_spec(
        protocol,
        run_ordinal=1,
        provider_id="provider-test",
        model_id="model-test",
        prompt_template_id="prompt-template-v1",
    )
    run = build_candidate_generation_run(protocol, spec, tuple(slots))

    assert len(run.events) == 16
    assert len(run.accepted_candidates) == 14
    assert run.duplicate_slot_count == 1
    assert run.invalid_slot_count == 1
    assert run.events[1].status is CandidateValidationStatus.DUPLICATE
    assert run.events[1].candidate is not None
    assert run.events[1].candidate.candidate_id == run.events[0].candidate.candidate_id  # type: ignore[union-attr]
    assert run.events[2].status is CandidateValidationStatus.INVALID
    assert run.usage.llm_calls == 16


def test_repair_stays_inside_consumed_slot_and_cannot_expand_budget() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    candidates = canonical_us_a0_primitive_vocabulary().all_candidates()
    slots: list[ProposalSlot] = [
        ProposalSlot(
            initial=_agent_proposal(candidates[0].kind.value, candidates[0].window_bars, "base")
        ),
        ProposalSlot(
            initial=_agent_proposal(candidates[0].kind.value, candidates[0].window_bars, "duplicate"),
            repair=_agent_proposal(candidates[14].kind.value, candidates[14].window_bars, "repair"),
        ),
        ProposalSlot(
            initial=_agent_proposal("unsupported_magic", 2, "invalid"),
            repair=_agent_proposal(candidates[15].kind.value, candidates[15].window_bars, "repair"),
        ),
    ]
    slots.extend(
        ProposalSlot(
            initial=_agent_proposal(candidate.kind.value, candidate.window_bars, "unique")
        )
        for candidate in candidates[1:14]
    )
    spec = agent_run_spec(
        protocol,
        run_ordinal=1,
        provider_id="provider-test",
        model_id="model-test",
        prompt_template_id="prompt-template-v1",
    )
    run = build_candidate_generation_run(protocol, spec, tuple(slots))

    assert len(run.final_events) == 16
    assert len(run.events) == 18
    assert len(run.accepted_candidates) == 16
    assert run.repair_count == 2
    assert run.to_dict()["replacement_count"] == 0
    assert run.usage.llm_calls == 18


def test_agent_attempt_requires_usage_and_manual_cannot_repair() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    candidate = canonical_us_a0_primitive_vocabulary().all_candidates()[0]
    bad_slots = list(manual_proposal_slots(protocol, generated_at=_NOW))
    bad_slots[0] = ProposalSlot(
        initial=bad_slots[0].initial,
        repair=bad_slots[1].initial,
    )
    with pytest.raises(ValueError, match="repair"):
        build_candidate_generation_run(
            protocol,
            canonical_manual_run_spec(protocol),
            tuple(bad_slots),
        )

    no_usage = StructuredCandidateProposal(
        kind=candidate.kind.value,
        window_bars=candidate.window_bars,
        hypothesis_summary="agent proposal without usage",
        generated_at=_NOW,
    )
    agent_slots = list(
        deterministic_programmatic_proposal_slots(protocol, random_seed=3, generated_at=_NOW)
    )
    agent_slots[0] = ProposalSlot(initial=no_usage)
    spec = agent_run_spec(
        protocol,
        run_ordinal=1,
        provider_id="provider-test",
        model_id="model-test",
        prompt_template_id="prompt-template-v1",
    )
    with pytest.raises(ValueError, match="exactly one LLM call"):
        build_candidate_generation_run(protocol, spec, tuple(agent_slots))
