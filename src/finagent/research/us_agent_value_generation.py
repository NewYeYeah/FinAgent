from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueCandidateSpec,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
    USAgentValuePrimitiveVocabulary,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baselines import USBaselineFeatureKind


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class CandidateValidationStatus(StrEnum):
    VALID_UNIQUE = "VALID_UNIQUE"
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class CandidateGenerationUsage:
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    schema_version: str = "finagent.us-agent-value-generation-usage.v1"

    def __post_init__(self) -> None:
        if self.llm_calls < 0 or self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("generation usage counts must be non-negative")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        if not math.isfinite(self.cost_usd) or self.cost_usd < 0:
            raise ValueError("cost_usd must be finite and non-negative")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True, slots=True)
class StructuredCandidateProposal:
    kind: str
    window_bars: int
    hypothesis_summary: str
    generated_at: datetime
    usage: CandidateGenerationUsage = CandidateGenerationUsage()
    parent_candidate_id: str | None = None
    schema_version: str = "finagent.us-agent-value-structured-proposal.v1"

    def __post_init__(self) -> None:
        kind = self.kind.strip().lower()
        if not kind:
            raise ValueError("proposal kind must be non-empty")
        object.__setattr__(self, "kind", kind)
        summary = self.hypothesis_summary.strip()
        if not summary or len(summary) > 280:
            raise ValueError("hypothesis_summary must contain 1..280 characters")
        object.__setattr__(self, "hypothesis_summary", summary)
        object.__setattr__(self, "generated_at", _aware_utc(self.generated_at, "generated_at"))
        if self.parent_candidate_id is not None:
            parent = self.parent_candidate_id.strip()
            if not parent:
                raise ValueError("parent_candidate_id must be non-empty when present")
            object.__setattr__(self, "parent_candidate_id", parent)

    @property
    def proposal_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-proposal",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "window_bars": self.window_bars,
            "hypothesis_summary": self.hypothesis_summary,
            "generated_at": self.generated_at.isoformat(),
            "usage": self.usage.to_dict(),
            "parent_candidate_id": self.parent_candidate_id,
            "stored_reasoning_scope": "structured_formula_and_short_hypothesis_only_no_chain_of_thought",
        }
        if include_id:
            payload["proposal_id"] = self.proposal_id
        return payload


@dataclass(frozen=True, slots=True)
class CandidateGenerationRunSpec:
    protocol_id: str
    phase: USAgentValuePhase
    arm: USAgentValueArm
    run_ordinal: int
    candidate_budget: int
    generator_id: str
    random_seed: int | None = None
    provider_id: str | None = None
    model_id: str | None = None
    prompt_template_id: str | None = None
    schema_version: str = "finagent.us-agent-value-generation-run-spec.v1"

    def __post_init__(self) -> None:
        for field_name in ("protocol_id", "generator_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.run_ordinal < 1:
            raise ValueError("run_ordinal must be >= 1")
        if self.candidate_budget < 1:
            raise ValueError("candidate_budget must be positive")
        provider = self.provider_id.strip() if self.provider_id is not None else None
        model = self.model_id.strip() if self.model_id is not None else None
        prompt = self.prompt_template_id.strip() if self.prompt_template_id is not None else None
        if any(value == "" for value in (provider, model, prompt) if value is not None):
            raise ValueError("provider/model/prompt identities must be non-empty when present")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "model_id", model)
        object.__setattr__(self, "prompt_template_id", prompt)

        if self.arm is USAgentValueArm.MANUAL:
            if self.random_seed is not None or any((provider, model, prompt)):
                raise ValueError("MANUAL run cannot carry random or LLM generator identity")
        elif self.arm is USAgentValueArm.PROGRAMMATIC:
            if self.random_seed is None:
                raise ValueError("PROGRAMMATIC run requires a recorded random seed")
            if any((provider, model, prompt)):
                raise ValueError("PROGRAMMATIC run cannot carry LLM provider/model/prompt identity")
        else:
            if provider is None or model is None or prompt is None:
                raise ValueError("AGENT run requires provider/model/prompt-template identities")

    @property
    def run_spec_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-generation-run-spec",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "phase": self.phase.value,
            "arm": self.arm.value,
            "run_ordinal": self.run_ordinal,
            "candidate_budget": self.candidate_budget,
            "generator_id": self.generator_id,
            "random_seed": self.random_seed,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_template_id": self.prompt_template_id,
        }
        if include_id:
            payload["run_spec_id"] = self.run_spec_id
        return payload


@dataclass(frozen=True, slots=True)
class ProposalSlot:
    initial: StructuredCandidateProposal
    repair: StructuredCandidateProposal | None = None


@dataclass(frozen=True, slots=True)
class CandidateGenerationEvent:
    run_spec_id: str
    arm: USAgentValueArm
    slot_index: int
    attempt_index: int
    proposal: StructuredCandidateProposal
    status: CandidateValidationStatus
    candidate: USAgentValueCandidateSpec | None
    validation_reason: str | None
    duplicate_of_candidate_id: str | None
    schema_version: str = "finagent.candidate-generation-event.v1"

    def __post_init__(self) -> None:
        if not self.run_spec_id.strip():
            raise ValueError("event run_spec_id must be non-empty")
        if self.slot_index < 1:
            raise ValueError("slot_index must be >= 1")
        if self.attempt_index not in (0, 1):
            raise ValueError("US-A0 v1 event attempt_index must be 0 or 1")
        if self.status is CandidateValidationStatus.INVALID:
            if self.candidate is not None or not self.validation_reason:
                raise ValueError("INVALID event requires a reason and no candidate")
            if self.duplicate_of_candidate_id is not None:
                raise ValueError("INVALID event cannot carry duplicate identity")
        elif self.status is CandidateValidationStatus.DUPLICATE:
            if self.candidate is None or self.duplicate_of_candidate_id != self.candidate.candidate_id:
                raise ValueError("DUPLICATE event must identify the duplicated structural candidate")
            if self.validation_reason != "duplicate_candidate":
                raise ValueError("DUPLICATE event must use the frozen duplicate reason")
        else:
            if self.candidate is None:
                raise ValueError("VALID_UNIQUE event requires a structural candidate")
            if self.validation_reason is not None or self.duplicate_of_candidate_id is not None:
                raise ValueError("VALID_UNIQUE event cannot carry invalid/duplicate diagnostics")

    @property
    def round_id(self) -> str:
        return _canonical_hash(
            {"run_spec_id": self.run_spec_id, "slot_index": self.slot_index},
            prefix="us-agent-value-round",
        )

    @property
    def event_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-generation-event",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_spec_id": self.run_spec_id,
            "round_id": self.round_id,
            "arm": self.arm.value,
            "slot_index": self.slot_index,
            "attempt_index": self.attempt_index,
            "proposal": self.proposal.to_dict(),
            "candidate": self.candidate.to_dict() if self.candidate is not None else None,
            "candidate_id": self.candidate.candidate_id if self.candidate is not None else None,
            "parent_candidate_id": self.proposal.parent_candidate_id,
            "status": self.status.value,
            "validation_reason": self.validation_reason,
            "duplicate_of_candidate_id": self.duplicate_of_candidate_id,
            "repair_attempt": self.attempt_index == 1,
            "replacement_attempt": False,
        }
        if include_id:
            payload["event_id"] = self.event_id
        return payload


@dataclass(frozen=True, slots=True)
class CandidateGenerationRun:
    spec: CandidateGenerationRunSpec
    events: tuple[CandidateGenerationEvent, ...]
    schema_version: str = "finagent.candidate-generation-run.v1"

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("candidate generation run requires events")
        if any(event.run_spec_id != self.spec.run_spec_id for event in self.events):
            raise ValueError("generation event/run-spec identity mismatch")
        if any(event.arm is not self.spec.arm for event in self.events):
            raise ValueError("generation event arm mismatch")
        slots: dict[int, list[CandidateGenerationEvent]] = {}
        for event in self.events:
            slots.setdefault(event.slot_index, []).append(event)
        if tuple(sorted(slots)) != tuple(range(1, self.spec.candidate_budget + 1)):
            raise ValueError("generation run must consume every frozen candidate slot exactly once")
        accepted: set[str] = set()
        for slot_index in range(1, self.spec.candidate_budget + 1):
            slot_events = sorted(slots[slot_index], key=lambda item: item.attempt_index)
            attempts = tuple(event.attempt_index for event in slot_events)
            if attempts not in ((0,), (0, 1)):
                raise ValueError("each slot must contain one initial proposal and at most one repair")
            if len(slot_events) == 2 and slot_events[0].status is CandidateValidationStatus.VALID_UNIQUE:
                raise ValueError("a valid unique initial proposal cannot receive a repair attempt")
            final = slot_events[-1]
            if final.status is CandidateValidationStatus.VALID_UNIQUE:
                assert final.candidate is not None
                if final.candidate.candidate_id in accepted:
                    raise ValueError("run final accepted candidates must remain unique")
                accepted.add(final.candidate.candidate_id)

    @property
    def run_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-generation-run",
        )

    @property
    def final_events(self) -> tuple[CandidateGenerationEvent, ...]:
        by_slot: dict[int, CandidateGenerationEvent] = {}
        for event in self.events:
            current = by_slot.get(event.slot_index)
            if current is None or event.attempt_index > current.attempt_index:
                by_slot[event.slot_index] = event
        return tuple(by_slot[index] for index in sorted(by_slot))

    @property
    def accepted_candidates(self) -> tuple[USAgentValueCandidateSpec, ...]:
        return tuple(
            event.candidate
            for event in self.final_events
            if event.status is CandidateValidationStatus.VALID_UNIQUE and event.candidate is not None
        )

    @property
    def invalid_slot_count(self) -> int:
        return sum(event.status is CandidateValidationStatus.INVALID for event in self.final_events)

    @property
    def duplicate_slot_count(self) -> int:
        return sum(event.status is CandidateValidationStatus.DUPLICATE for event in self.final_events)

    @property
    def repair_count(self) -> int:
        return sum(event.attempt_index == 1 for event in self.events)

    @property
    def usage(self) -> CandidateGenerationUsage:
        return CandidateGenerationUsage(
            llm_calls=sum(event.proposal.usage.llm_calls for event in self.events),
            input_tokens=sum(event.proposal.usage.input_tokens for event in self.events),
            output_tokens=sum(event.proposal.usage.output_tokens for event in self.events),
            latency_ms=sum(event.proposal.usage.latency_ms for event in self.events),
            cost_usd=sum(event.proposal.usage.cost_usd for event in self.events),
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "spec": self.spec.to_dict(),
            "event_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
            "candidate_budget": self.spec.candidate_budget,
            "accepted_candidate_count": len(self.accepted_candidates),
            "accepted_candidate_ids": [item.candidate_id for item in self.accepted_candidates],
            "invalid_slot_count": self.invalid_slot_count,
            "duplicate_slot_count": self.duplicate_slot_count,
            "repair_count": self.repair_count,
            "replacement_count": 0,
            "usage": self.usage.to_dict(),
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["run_id"] = self.run_id
        return payload


def _validate_run_spec(
    protocol: USAgentValueExperimentProtocol,
    spec: CandidateGenerationRunSpec,
) -> None:
    if spec.protocol_id != protocol.protocol_id:
        raise ValueError("generation run spec does not bind the supplied US-A0 protocol")
    if spec.phase is not protocol.phase:
        raise ValueError("generation run phase/protocol mismatch")
    if spec.candidate_budget != protocol.candidate_budget_per_run:
        raise ValueError("all US-A0 arms must consume the same per-run candidate budget")


def _validate_usage(arm: USAgentValueArm, proposal: StructuredCandidateProposal) -> None:
    usage = proposal.usage
    if arm is USAgentValueArm.AGENT:
        if usage.llm_calls != 1:
            raise ValueError("each AGENT proposal/repair attempt must record exactly one LLM call")
    elif usage != CandidateGenerationUsage():
        raise ValueError("MANUAL/PROGRAMMATIC structured proposals cannot claim LLM usage")


def _candidate_from_proposal(
    vocabulary: USAgentValuePrimitiveVocabulary,
    proposal: StructuredCandidateProposal,
) -> tuple[USAgentValueCandidateSpec | None, str | None]:
    try:
        kind = USBaselineFeatureKind(proposal.kind)
    except ValueError:
        return None, "unsupported_kind"
    try:
        return vocabulary.candidate(kind, proposal.window_bars), None
    except ValueError:
        return None, "window_outside_vocabulary"


def _build_event(
    *,
    spec: CandidateGenerationRunSpec,
    slot_index: int,
    attempt_index: int,
    proposal: StructuredCandidateProposal,
    vocabulary: USAgentValuePrimitiveVocabulary,
    accepted_ids: set[str],
) -> CandidateGenerationEvent:
    _validate_usage(spec.arm, proposal)
    if proposal.parent_candidate_id is not None and proposal.parent_candidate_id not in accepted_ids:
        return CandidateGenerationEvent(
            run_spec_id=spec.run_spec_id,
            arm=spec.arm,
            slot_index=slot_index,
            attempt_index=attempt_index,
            proposal=proposal,
            status=CandidateValidationStatus.INVALID,
            candidate=None,
            validation_reason="parent_candidate_not_previously_accepted",
            duplicate_of_candidate_id=None,
        )
    candidate, error = _candidate_from_proposal(vocabulary, proposal)
    if candidate is None:
        return CandidateGenerationEvent(
            run_spec_id=spec.run_spec_id,
            arm=spec.arm,
            slot_index=slot_index,
            attempt_index=attempt_index,
            proposal=proposal,
            status=CandidateValidationStatus.INVALID,
            candidate=None,
            validation_reason=error,
            duplicate_of_candidate_id=None,
        )
    if candidate.candidate_id in accepted_ids:
        return CandidateGenerationEvent(
            run_spec_id=spec.run_spec_id,
            arm=spec.arm,
            slot_index=slot_index,
            attempt_index=attempt_index,
            proposal=proposal,
            status=CandidateValidationStatus.DUPLICATE,
            candidate=candidate,
            validation_reason="duplicate_candidate",
            duplicate_of_candidate_id=candidate.candidate_id,
        )
    return CandidateGenerationEvent(
        run_spec_id=spec.run_spec_id,
        arm=spec.arm,
        slot_index=slot_index,
        attempt_index=attempt_index,
        proposal=proposal,
        status=CandidateValidationStatus.VALID_UNIQUE,
        candidate=candidate,
        validation_reason=None,
        duplicate_of_candidate_id=None,
    )


def build_candidate_generation_run(
    protocol: USAgentValueExperimentProtocol,
    spec: CandidateGenerationRunSpec,
    slots: tuple[ProposalSlot, ...],
    *,
    vocabulary: USAgentValuePrimitiveVocabulary | None = None,
) -> CandidateGenerationRun:
    _validate_run_spec(protocol, spec)
    active_vocabulary = vocabulary or canonical_us_a0_primitive_vocabulary()
    if active_vocabulary.vocabulary_id != protocol.vocabulary_id:
        raise ValueError("generation vocabulary/protocol identity mismatch")
    if len(slots) != protocol.candidate_budget_per_run:
        raise ValueError("generation input must contain exactly the frozen number of slots")

    events: list[CandidateGenerationEvent] = []
    accepted_ids: set[str] = set()
    for slot_index, slot in enumerate(slots, start=1):
        initial = _build_event(
            spec=spec,
            slot_index=slot_index,
            attempt_index=0,
            proposal=slot.initial,
            vocabulary=active_vocabulary,
            accepted_ids=accepted_ids,
        )
        events.append(initial)
        final = initial
        if slot.repair is not None:
            if initial.status is CandidateValidationStatus.VALID_UNIQUE:
                raise ValueError("repair is forbidden after a valid unique initial proposal")
            final = _build_event(
                spec=spec,
                slot_index=slot_index,
                attempt_index=1,
                proposal=slot.repair,
                vocabulary=active_vocabulary,
                accepted_ids=accepted_ids,
            )
            events.append(final)
        if final.status is CandidateValidationStatus.VALID_UNIQUE:
            assert final.candidate is not None
            accepted_ids.add(final.candidate.candidate_id)

    run = CandidateGenerationRun(spec=spec, events=tuple(events))
    if spec.arm is USAgentValueArm.MANUAL:
        if any(slot.repair is not None for slot in slots):
            raise ValueError("frozen MANUAL arm cannot repair or replace proposals")
        if tuple(item.candidate_id for item in run.accepted_candidates) != protocol.manual_candidate_ids:
            raise ValueError("MANUAL run must equal the exact preregistered candidate grid")
        if len(run.accepted_candidates) != protocol.candidate_budget_per_run:
            raise ValueError("MANUAL run must fill every preregistered slot")
    return run


def manual_proposal_slots(
    protocol: USAgentValueExperimentProtocol,
    *,
    generated_at: datetime,
) -> tuple[ProposalSlot, ...]:
    timestamp = _aware_utc(generated_at, "generated_at")
    manual = canonical_us_a0_manual_candidates()[: protocol.candidate_budget_per_run]
    if tuple(item.candidate_id for item in manual) != protocol.manual_candidate_ids:
        raise RuntimeError("manual proposal grid/protocol identity mismatch")
    return tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=candidate.kind.value,
                window_bars=candidate.window_bars,
                hypothesis_summary="Pre-registered MANUAL structural candidate; not performance-selected.",
                generated_at=timestamp,
            )
        )
        for candidate in manual
    )


def deterministic_programmatic_proposal_slots(
    protocol: USAgentValueExperimentProtocol,
    *,
    random_seed: int,
    generated_at: datetime,
) -> tuple[ProposalSlot, ...]:
    timestamp = _aware_utc(generated_at, "generated_at")
    vocabulary = canonical_us_a0_primitive_vocabulary()
    if vocabulary.vocabulary_id != protocol.vocabulary_id:
        raise RuntimeError("programmatic vocabulary/protocol identity mismatch")
    candidates = list(vocabulary.all_candidates())
    if protocol.candidate_budget_per_run > len(candidates):
        raise ValueError("candidate budget exceeds frozen vocabulary size")
    selected = random.Random(random_seed).sample(candidates, protocol.candidate_budget_per_run)
    return tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=candidate.kind.value,
                window_bars=candidate.window_bars,
                hypothesis_summary="Seeded bounded search over the same frozen structural vocabulary.",
                generated_at=timestamp,
            )
        )
        for candidate in selected
    )


def canonical_manual_run_spec(
    protocol: USAgentValueExperimentProtocol,
) -> CandidateGenerationRunSpec:
    return CandidateGenerationRunSpec(
        protocol_id=protocol.protocol_id,
        phase=protocol.phase,
        arm=USAgentValueArm.MANUAL,
        run_ordinal=1,
        candidate_budget=protocol.candidate_budget_per_run,
        generator_id="us_a0_manual_grid_v1",
    )


def programmatic_run_spec(
    protocol: USAgentValueExperimentProtocol,
    *,
    run_ordinal: int,
    random_seed: int,
) -> CandidateGenerationRunSpec:
    return CandidateGenerationRunSpec(
        protocol_id=protocol.protocol_id,
        phase=protocol.phase,
        arm=USAgentValueArm.PROGRAMMATIC,
        run_ordinal=run_ordinal,
        candidate_budget=protocol.candidate_budget_per_run,
        generator_id="us_a0_seeded_uniform_without_replacement_v1",
        random_seed=random_seed,
    )


def agent_run_spec(
    protocol: USAgentValueExperimentProtocol,
    *,
    run_ordinal: int,
    provider_id: str,
    model_id: str,
    prompt_template_id: str,
    generator_id: str = "us_a0_structured_agent_generator_v1",
) -> CandidateGenerationRunSpec:
    return CandidateGenerationRunSpec(
        protocol_id=protocol.protocol_id,
        phase=protocol.phase,
        arm=USAgentValueArm.AGENT,
        run_ordinal=run_ordinal,
        candidate_budget=protocol.candidate_budget_per_run,
        generator_id=generator_id,
        provider_id=provider_id,
        model_id=model_id,
        prompt_template_id=prompt_template_id,
    )
