from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from finagent.research.us_agent_value_execution import USAgentValueExecutionPlan
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRun,
    CandidateGenerationRunSpec,
    CandidateGenerationUsage,
    CandidateValidationStatus,
    ProposalSlot,
    StructuredCandidateProposal,
    build_candidate_generation_run,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueCandidateSpec,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def formal_agent_request_id(
    run_spec_id: str,
    *,
    slot_index: int,
    attempt_index: int,
) -> str:
    if slot_index < 1:
        raise ValueError("slot_index must be >= 1")
    if attempt_index not in (0, 1):
        raise ValueError("attempt_index must be 0 or 1")
    return f"us-a0-{run_spec_id[-12:]}-slot-{slot_index:02d}-attempt-{attempt_index}"


def _parse_usage(document: Mapping[str, object]) -> CandidateGenerationUsage:
    usage = CandidateGenerationUsage(
        llm_calls=_integer(document.get("llm_calls"), "usage.llm_calls"),
        input_tokens=_integer(document.get("input_tokens"), "usage.input_tokens"),
        output_tokens=_integer(document.get("output_tokens"), "usage.output_tokens"),
        latency_ms=_number(document.get("latency_ms"), "usage.latency_ms"),
        cost_usd=_number(document.get("cost_usd"), "usage.cost_usd"),
    )
    if dict(document) != usage.to_dict():
        raise ValueError("FORMAL attempt usage content mismatch")
    return usage


def _parse_proposal(document: Mapping[str, object]) -> StructuredCandidateProposal:
    proposal = StructuredCandidateProposal(
        kind=_text(document.get("kind"), "proposal.kind"),
        window_bars=_integer(document.get("window_bars"), "proposal.window_bars"),
        hypothesis_summary=_text(
            document.get("hypothesis_summary"), "proposal.hypothesis_summary"
        ),
        generated_at=datetime.fromisoformat(
            _text(document.get("generated_at"), "proposal.generated_at")
        ),
        usage=_parse_usage(_mapping(document.get("usage"), "proposal.usage")),
        parent_candidate_id=_optional_text(
            document.get("parent_candidate_id"), "proposal.parent_candidate_id"
        ),
    )
    if dict(document) != proposal.to_dict():
        raise ValueError("FORMAL structured proposal content identity mismatch")
    return proposal


@dataclass(frozen=True, slots=True)
class USAgentValueFormalAgentAttemptEvidence:
    execution_plan_id: str
    launch_bundle_id: str
    runtime_policy_id: str
    run_spec_id: str
    run_ordinal: int
    slot_index: int
    attempt_index: int
    request_id: str
    proposal: StructuredCandidateProposal
    status: CandidateValidationStatus
    candidate_id: str | None
    classification_reason: str | None
    provider_parse_error: str | None
    schema_version: str = "finagent.us-agent-value-formal-agent-attempt.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_plan_id",
            "launch_bundle_id",
            "runtime_policy_id",
            "run_spec_id",
            "request_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.run_ordinal not in (1, 2, 3):
            raise ValueError("FORMAL AGENT run ordinal must be 1, 2 or 3")
        if self.slot_index < 1 or self.slot_index > 32:
            raise ValueError("FORMAL slot_index must be in 1..32")
        if self.attempt_index not in (0, 1):
            raise ValueError("FORMAL attempt_index must be 0 or 1")
        expected_request = formal_agent_request_id(
            self.run_spec_id,
            slot_index=self.slot_index,
            attempt_index=self.attempt_index,
        )
        if self.request_id != expected_request:
            raise ValueError("FORMAL attempt request identity mismatch")
        if self.status is CandidateValidationStatus.VALID_UNIQUE and self.candidate_id is None:
            raise ValueError("VALID_UNIQUE FORMAL attempt requires candidate_id")
        if self.status is CandidateValidationStatus.INVALID and self.candidate_id is not None:
            raise ValueError("INVALID FORMAL attempt cannot carry candidate_id")
        if self.status is CandidateValidationStatus.DUPLICATE and self.candidate_id is None:
            raise ValueError("DUPLICATE FORMAL attempt requires candidate_id")

    @property
    def attempt_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-formal-agent-attempt",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "launch_bundle_id": self.launch_bundle_id,
            "runtime_policy_id": self.runtime_policy_id,
            "run_spec_id": self.run_spec_id,
            "run_ordinal": self.run_ordinal,
            "slot_index": self.slot_index,
            "attempt_index": self.attempt_index,
            "request_id": self.request_id,
            "proposal": self.proposal.to_dict(),
            "status": self.status.value,
            "candidate_id": self.candidate_id,
            "classification_reason": self.classification_reason,
            "provider_parse_error": self.provider_parse_error,
            "trial_semantics": "one_provider_response_for_one_initial_or_repair_attempt",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["attempt_id"] = self.attempt_id
        return payload


@dataclass(frozen=True, slots=True)
class USAgentValueFormalAgentSlotEvidence:
    execution_plan_id: str
    launch_bundle_id: str
    runtime_policy_id: str
    run_spec_id: str
    run_ordinal: int
    slot_index: int
    initial: USAgentValueFormalAgentAttemptEvidence
    repair: USAgentValueFormalAgentAttemptEvidence | None = None
    schema_version: str = "finagent.us-agent-value-formal-agent-slot.v1"

    def __post_init__(self) -> None:
        if self.slot_index < 1 or self.slot_index > 32:
            raise ValueError("FORMAL slot_index must be in 1..32")
        for attempt in (self.initial, self.repair):
            if attempt is None:
                continue
            if attempt.execution_plan_id != self.execution_plan_id:
                raise ValueError("FORMAL slot attempt/execution-plan identity mismatch")
            if attempt.launch_bundle_id != self.launch_bundle_id:
                raise ValueError("FORMAL slot attempt/launch identity mismatch")
            if attempt.runtime_policy_id != self.runtime_policy_id:
                raise ValueError("FORMAL slot attempt/runtime identity mismatch")
            if attempt.run_spec_id != self.run_spec_id or attempt.run_ordinal != self.run_ordinal:
                raise ValueError("FORMAL slot attempt/run identity mismatch")
            if attempt.slot_index != self.slot_index:
                raise ValueError("FORMAL slot attempt/slot identity mismatch")
        if self.initial.attempt_index != 0:
            raise ValueError("FORMAL initial attempt must use attempt_index=0")
        if self.repair is not None and self.repair.attempt_index != 1:
            raise ValueError("FORMAL repair attempt must use attempt_index=1")
        if self.initial.status is CandidateValidationStatus.VALID_UNIQUE and self.repair is not None:
            raise ValueError("FORMAL valid unique initial proposal cannot receive repair")
        if self.initial.status is not CandidateValidationStatus.VALID_UNIQUE and self.repair is None:
            raise ValueError("FORMAL non-valid initial proposal must consume its single repair")

    @property
    def final_attempt(self) -> USAgentValueFormalAgentAttemptEvidence:
        return self.initial if self.repair is None else self.repair

    @property
    def slot_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-formal-agent-slot",
        )

    def to_proposal_slot(self) -> ProposalSlot:
        return ProposalSlot(
            initial=self.initial.proposal,
            repair=None if self.repair is None else self.repair.proposal,
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "launch_bundle_id": self.launch_bundle_id,
            "runtime_policy_id": self.runtime_policy_id,
            "run_spec_id": self.run_spec_id,
            "run_ordinal": self.run_ordinal,
            "slot_index": self.slot_index,
            "initial": self.initial.to_dict(),
            "repair": None if self.repair is None else self.repair.to_dict(),
            "final_status": self.final_attempt.status.value,
            "final_candidate_id": self.final_attempt.candidate_id,
            "repair_count": 0 if self.repair is None else 1,
            "replacement_count": 0,
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["slot_id"] = self.slot_id
        return payload


def parse_us_a0_formal_agent_attempt(
    document: Mapping[str, object],
) -> USAgentValueFormalAgentAttemptEvidence:
    attempt = USAgentValueFormalAgentAttemptEvidence(
        execution_plan_id=_text(document.get("execution_plan_id"), "attempt.execution_plan_id"),
        launch_bundle_id=_text(document.get("launch_bundle_id"), "attempt.launch_bundle_id"),
        runtime_policy_id=_text(document.get("runtime_policy_id"), "attempt.runtime_policy_id"),
        run_spec_id=_text(document.get("run_spec_id"), "attempt.run_spec_id"),
        run_ordinal=_integer(document.get("run_ordinal"), "attempt.run_ordinal"),
        slot_index=_integer(document.get("slot_index"), "attempt.slot_index"),
        attempt_index=_integer(document.get("attempt_index"), "attempt.attempt_index"),
        request_id=_text(document.get("request_id"), "attempt.request_id"),
        proposal=_parse_proposal(_mapping(document.get("proposal"), "attempt.proposal")),
        status=CandidateValidationStatus(_text(document.get("status"), "attempt.status")),
        candidate_id=_optional_text(document.get("candidate_id"), "attempt.candidate_id"),
        classification_reason=_optional_text(
            document.get("classification_reason"), "attempt.classification_reason"
        ),
        provider_parse_error=_optional_text(
            document.get("provider_parse_error"), "attempt.provider_parse_error"
        ),
    )
    if dict(document) != attempt.to_dict():
        raise ValueError("US-A0 FORMAL Agent attempt content identity mismatch")
    return attempt


def parse_us_a0_formal_agent_slot(
    document: Mapping[str, object],
) -> USAgentValueFormalAgentSlotEvidence:
    raw_repair = document.get("repair")
    slot = USAgentValueFormalAgentSlotEvidence(
        execution_plan_id=_text(document.get("execution_plan_id"), "slot.execution_plan_id"),
        launch_bundle_id=_text(document.get("launch_bundle_id"), "slot.launch_bundle_id"),
        runtime_policy_id=_text(document.get("runtime_policy_id"), "slot.runtime_policy_id"),
        run_spec_id=_text(document.get("run_spec_id"), "slot.run_spec_id"),
        run_ordinal=_integer(document.get("run_ordinal"), "slot.run_ordinal"),
        slot_index=_integer(document.get("slot_index"), "slot.slot_index"),
        initial=parse_us_a0_formal_agent_attempt(
            _mapping(document.get("initial"), "slot.initial")
        ),
        repair=(
            None
            if raw_repair is None
            else parse_us_a0_formal_agent_attempt(_mapping(raw_repair, "slot.repair"))
        ),
    )
    if dict(document) != slot.to_dict():
        raise ValueError("US-A0 FORMAL Agent slot content identity mismatch")
    return slot


def _classify_proposal(
    proposal: StructuredCandidateProposal,
    accepted_ids: set[str],
) -> tuple[CandidateValidationStatus, USAgentValueCandidateSpec | None, str | None]:
    if proposal.parent_candidate_id is not None and proposal.parent_candidate_id not in accepted_ids:
        return CandidateValidationStatus.INVALID, None, "parent_candidate_not_previously_accepted"
    vocabulary = canonical_us_a0_primitive_vocabulary()
    try:
        kind = USBaselineFeatureKind(proposal.kind)
    except ValueError:
        return CandidateValidationStatus.INVALID, None, "unsupported_kind"
    try:
        candidate = vocabulary.candidate(kind, proposal.window_bars)
    except ValueError:
        return CandidateValidationStatus.INVALID, None, "window_outside_vocabulary"
    if candidate.candidate_id in accepted_ids:
        return CandidateValidationStatus.DUPLICATE, candidate, "duplicate_candidate"
    return CandidateValidationStatus.VALID_UNIQUE, candidate, None


def validate_us_a0_formal_slot_sequence(
    protocol: USAgentValueExperimentProtocol,
    spec: CandidateGenerationRunSpec,
    slots: Sequence[USAgentValueFormalAgentSlotEvidence],
) -> tuple[USAgentValueCandidateSpec, ...]:
    if protocol.phase is not USAgentValuePhase.FORMAL or spec.phase is not USAgentValuePhase.FORMAL:
        raise ValueError("FORMAL slot sequence requires FORMAL protocol/run spec")
    if spec.protocol_id != protocol.protocol_id:
        raise ValueError("FORMAL slot sequence run-spec/protocol identity mismatch")
    if len(slots) > protocol.candidate_budget_per_run:
        raise ValueError("FORMAL slot sequence exceeds frozen candidate budget")
    accepted_ids: set[str] = set()
    accepted: list[USAgentValueCandidateSpec] = []
    for expected_index, slot in enumerate(slots, start=1):
        if slot.slot_index != expected_index:
            raise ValueError("FORMAL slot evidence must form an ordered prefix from slot 1")
        if slot.run_spec_id != spec.run_spec_id or slot.run_ordinal != spec.run_ordinal:
            raise ValueError("FORMAL slot evidence/run-spec identity mismatch")
        for attempt in (slot.initial, slot.repair):
            if attempt is None:
                continue
            status, candidate, reason = _classify_proposal(attempt.proposal, accepted_ids)
            if attempt.status is not status:
                raise ValueError("FORMAL attempt stored status differs from canonical classification")
            expected_candidate_id = None if candidate is None else candidate.candidate_id
            if attempt.candidate_id != expected_candidate_id:
                raise ValueError("FORMAL attempt stored candidate differs from canonical classification")
            if attempt.classification_reason != reason:
                raise ValueError("FORMAL attempt classification reason mismatch")
        final = slot.final_attempt
        if final.status is CandidateValidationStatus.VALID_UNIQUE:
            assert final.candidate_id is not None
            candidate = canonical_us_a0_primitive_vocabulary().candidate_by_id(final.candidate_id)
            accepted_ids.add(candidate.candidate_id)
            accepted.append(candidate)
    return tuple(accepted)


def build_us_a0_formal_agent_generation_run(
    protocol: USAgentValueExperimentProtocol,
    spec: CandidateGenerationRunSpec,
    slots: Sequence[USAgentValueFormalAgentSlotEvidence],
) -> CandidateGenerationRun:
    if len(slots) != protocol.candidate_budget_per_run:
        raise ValueError("FORMAL Agent run requires all 32 frozen slot evidence documents")
    accepted = validate_us_a0_formal_slot_sequence(protocol, spec, slots)
    run = build_candidate_generation_run(
        protocol,
        spec,
        tuple(slot.to_proposal_slot() for slot in slots),
    )
    if run.accepted_candidates != accepted:
        raise ValueError("FORMAL slot evidence and authoritative generation-run assembly diverged")
    return run


@dataclass(frozen=True, slots=True)
class USAgentValueFormalAgentRunProgress:
    execution_plan_id: str
    launch_bundle_id: str
    runtime_policy_id: str
    run_spec_id: str
    run_ordinal: int
    completed_slot_ids: tuple[str, ...]
    previous_progress_id: str | None = None
    schema_version: str = "finagent.us-agent-value-formal-agent-run-progress.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_plan_id",
            "launch_bundle_id",
            "runtime_policy_id",
            "run_spec_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.run_ordinal not in (1, 2, 3):
            raise ValueError("FORMAL run progress ordinal must be 1, 2 or 3")
        if not 1 <= len(self.completed_slot_ids) <= 32:
            raise ValueError("FORMAL run progress must contain 1..32 completed slot IDs")
        if any(not value.strip() for value in self.completed_slot_ids):
            raise ValueError("FORMAL run progress slot IDs must be non-empty")
        if len(self.completed_slot_ids) != len(set(self.completed_slot_ids)):
            raise ValueError("FORMAL run progress slot IDs must be unique")
        if len(self.completed_slot_ids) == 1 and self.previous_progress_id is not None:
            raise ValueError("first FORMAL slot progress cannot have predecessor")
        if len(self.completed_slot_ids) > 1 and not self.previous_progress_id:
            raise ValueError("advanced FORMAL slot progress requires predecessor")

    @property
    def completed_slot_count(self) -> int:
        return len(self.completed_slot_ids)

    @property
    def progress_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-formal-agent-run-progress",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "launch_bundle_id": self.launch_bundle_id,
            "runtime_policy_id": self.runtime_policy_id,
            "run_spec_id": self.run_spec_id,
            "run_ordinal": self.run_ordinal,
            "completed_slot_count": self.completed_slot_count,
            "completed_slot_ids": list(self.completed_slot_ids),
            "previous_progress_id": self.previous_progress_id,
            "resume_semantics": "slot_prefix_is_immutable_and_never_regenerated",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["progress_id"] = self.progress_id
        return payload


def advance_us_a0_formal_agent_run_progress(
    *,
    previous: USAgentValueFormalAgentRunProgress | None,
    execution_plan: USAgentValueExecutionPlan,
    spec: CandidateGenerationRunSpec,
    slot: USAgentValueFormalAgentSlotEvidence,
) -> USAgentValueFormalAgentRunProgress:
    expected_slot = 1 if previous is None else previous.completed_slot_count + 1
    if slot.slot_index != expected_slot:
        raise ValueError("FORMAL slot progress must advance exactly one slot")
    if spec.run_spec_id != slot.run_spec_id or spec.run_ordinal != slot.run_ordinal:
        raise ValueError("FORMAL slot progress run identity mismatch")
    if execution_plan.run_spec(spec.run_spec_id) != spec:
        raise ValueError("FORMAL slot progress run spec is not ExecutionPlan-authorized")
    prior_ids = () if previous is None else previous.completed_slot_ids
    if previous is not None:
        if previous.execution_plan_id != execution_plan.plan_id:
            raise ValueError("FORMAL slot progress execution-plan identity drift")
        if previous.run_spec_id != spec.run_spec_id or previous.run_ordinal != spec.run_ordinal:
            raise ValueError("FORMAL slot progress run identity drift")
        if previous.launch_bundle_id != slot.launch_bundle_id:
            raise ValueError("FORMAL slot progress launch identity drift")
        if previous.runtime_policy_id != slot.runtime_policy_id:
            raise ValueError("FORMAL slot progress runtime identity drift")
    return USAgentValueFormalAgentRunProgress(
        execution_plan_id=execution_plan.plan_id,
        launch_bundle_id=slot.launch_bundle_id,
        runtime_policy_id=slot.runtime_policy_id,
        run_spec_id=spec.run_spec_id,
        run_ordinal=spec.run_ordinal,
        completed_slot_ids=(*prior_ids, slot.slot_id),
        previous_progress_id=None if previous is None else previous.progress_id,
    )


def parse_us_a0_formal_agent_run_progress(
    document: Mapping[str, object],
) -> USAgentValueFormalAgentRunProgress:
    raw_slots = _sequence(document.get("completed_slot_ids"), "formal_progress.completed_slot_ids")
    if any(not isinstance(item, str) for item in raw_slots):
        raise TypeError("FORMAL progress completed_slot_ids must contain strings")
    progress = USAgentValueFormalAgentRunProgress(
        execution_plan_id=_text(
            document.get("execution_plan_id"), "formal_progress.execution_plan_id"
        ),
        launch_bundle_id=_text(document.get("launch_bundle_id"), "formal_progress.launch_bundle_id"),
        runtime_policy_id=_text(
            document.get("runtime_policy_id"), "formal_progress.runtime_policy_id"
        ),
        run_spec_id=_text(document.get("run_spec_id"), "formal_progress.run_spec_id"),
        run_ordinal=_integer(document.get("run_ordinal"), "formal_progress.run_ordinal"),
        completed_slot_ids=tuple(str(item) for item in raw_slots),
        previous_progress_id=_optional_text(
            document.get("previous_progress_id"), "formal_progress.previous_progress_id"
        ),
    )
    if dict(document) != progress.to_dict():
        raise ValueError("US-A0 FORMAL Agent run progress content identity mismatch")
    return progress
