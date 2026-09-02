from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.agents.providers import (
    ConfiguredLLM,
    LLMCallStore,
    LLMRequest,
    LLMResponse,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRunSpec,
    CandidateGenerationUsage,
    CandidateValidationStatus,
    ProposalSlot,
    StructuredCandidateProposal,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueCandidateSpec,
    USAgentValueExperimentProtocol,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baselines import USBaselineFeatureKind

US_A0_STRUCTURED_PROMPT_TEMPLATE_ID = "us-a0-structured-candidate-v1"
DEEPSEEK_V4_PRICING_POLICY_ID = "deepseek-v4-pricing-2026-08-17-v1"
_SUPPORTED_DEEPSEEK_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})
_PRICING_EFFECTIVE_AT = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DeepSeekV4TokenRates:
    cached_input_per_million_usd: float
    uncached_input_per_million_usd: float
    output_per_million_usd: float

    def __post_init__(self) -> None:
        for field_name in (
            "cached_input_per_million_usd",
            "uncached_input_per_million_usd",
            "output_per_million_usd",
        ):
            rate = float(getattr(self, field_name))
            if not math.isfinite(rate) or rate < 0:
                raise ValueError(f"{field_name} must be finite and non-negative")


def _is_deepseek_peak(at: datetime) -> bool:
    """Return the frozen 2026-08-17 DeepSeek peak-window classification.

    Official V4 pricing defines peak hours every day at 01:00-04:00 and 06:00-10:00 UTC;
    all other hours are off-peak. There is deliberately no weekday exception.
    """

    utc = at.astimezone(UTC)
    return 1 <= utc.hour < 4 or 6 <= utc.hour < 10


def deepseek_v4_token_rates(model: str, at: datetime) -> DeepSeekV4TokenRates:
    normalized = model.strip().lower()
    if normalized not in _SUPPORTED_DEEPSEEK_MODELS:
        raise ValueError(f"unsupported DeepSeek V4 pricing model: {model}")
    utc = at.astimezone(UTC)
    if utc < _PRICING_EFFECTIVE_AT:
        raise ValueError(
            "DeepSeek V4 pricing policy v1 is only valid from 2026-08-16T16:00:00Z"
        )
    peak = _is_deepseek_peak(utc)
    if normalized == "deepseek-v4-flash":
        return DeepSeekV4TokenRates(
            cached_input_per_million_usd=0.014 if peak else 0.007,
            uncached_input_per_million_usd=0.44 if peak else 0.22,
            output_per_million_usd=1.32 if peak else 0.66,
        )
    return DeepSeekV4TokenRates(
        cached_input_per_million_usd=0.044 if peak else 0.022,
        uncached_input_per_million_usd=1.32 if peak else 0.66,
        output_per_million_usd=3.96 if peak else 1.98,
    )


def estimate_deepseek_v4_cost_usd(
    model: str,
    response: LLMResponse,
    *,
    priced_at: datetime,
) -> float:
    usage = response.usage
    cached = usage.cached_input_tokens
    if cached > usage.input_tokens:
        raise ValueError("cached input tokens cannot exceed input tokens")
    uncached = usage.input_tokens - cached
    rates = deepseek_v4_token_rates(model, priced_at)
    cost = (
        cached * rates.cached_input_per_million_usd
        + uncached * rates.uncached_input_per_million_usd
        + usage.output_tokens * rates.output_per_million_usd
    ) / 1_000_000.0
    return float(cost)


@dataclass(frozen=True, slots=True)
class _ClassifiedProposal:
    status: CandidateValidationStatus
    candidate: USAgentValueCandidateSpec | None
    reason: str | None


class DeepSeekStructuredAgentSlotProvider:
    """Adapt the shared FinAgent DeepSeek transport to the frozen US-A0 grammar.

    The underlying ``finagent.agents.providers`` stack was built for the earlier A-share
    Agent work and remains authoritative for API credentials, OpenAI-compatible transport,
    retry/backoff, JSON response mode, token/cache/reasoning accounting and optional durable
    LLM-call telemetry. This adapter owns only US-A0 structured-proposal translation.
    """

    def __init__(
        self,
        configured_llm: ConfiguredLLM,
        *,
        prompt_template_id: str = US_A0_STRUCTURED_PROMPT_TEMPLATE_ID,
        call_store: LLMCallStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if configured_llm.profile.provider != "deepseek":
            raise ValueError("US-A0 DeepSeek adapter requires a deepseek LLM profile")
        if configured_llm.profile.model not in _SUPPORTED_DEEPSEEK_MODELS:
            raise ValueError(
                "US-A0 DeepSeek adapter supports deepseek-v4-flash or deepseek-v4-pro"
            )
        prompt_id = prompt_template_id.strip()
        if prompt_id != US_A0_STRUCTURED_PROMPT_TEMPLATE_ID:
            raise ValueError("unsupported US-A0 structured prompt-template identity")
        self.configured_llm = configured_llm
        self.call_store = call_store
        self._prompt_template_id = prompt_id
        self.clock = clock or (lambda: datetime.now(UTC))

    @property
    def provider_id(self) -> str:
        return self.configured_llm.profile.provider

    @property
    def model_id(self) -> str:
        return self.configured_llm.profile.model

    @property
    def prompt_template_id(self) -> str:
        return self._prompt_template_id

    @staticmethod
    def _schema() -> Mapping[str, object]:
        kinds = [kind.value for kind in USBaselineFeatureKind]
        return {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": kinds},
                "window_bars": {"type": "integer", "minimum": 1, "maximum": 13},
                "hypothesis_summary": {"type": "string", "minLength": 1, "maxLength": 280},
            },
            "required": ["kind", "window_bars", "hypothesis_summary"],
            "additionalProperties": False,
        }

    def _request(
        self,
        protocol: USAgentValueExperimentProtocol,
        run_spec: CandidateGenerationRunSpec,
        *,
        slot_index: int,
        attempt_index: int,
        accepted_candidates: tuple[USAgentValueCandidateSpec, ...],
        repair_reason: str | None,
    ) -> LLMRequest:
        vocabulary = canonical_us_a0_primitive_vocabulary()
        allowed = {
            rule.kind.value: list(rule.allowed_window_bars)
            for rule in vocabulary.rules
        }
        accepted = [candidate.structural_key for candidate in accepted_candidates]
        instructions = (
            "You are the FinAgent US-A0 structured factor proposer. Propose exactly one formula "
            "from the supplied frozen grammar. Do not emit Python, SQL, tools, portfolio rules, "
            "validation thresholds, observed market statistics, or chain-of-thought. The short "
            "hypothesis must state only the economic intuition for the proposed structure."
        )
        payload: dict[str, object] = {
            "phase": protocol.phase.value,
            "run_ordinal": run_spec.run_ordinal,
            "slot_index": slot_index,
            "attempt_index": attempt_index,
            "candidate_budget": protocol.candidate_budget_per_run,
            "allowed_kind_windows": allowed,
            "previously_accepted_structures": accepted,
            "selection_instruction": (
                "Prefer a valid structure not already accepted in this run. Do not infer or use "
                "financial performance because no evaluation evidence is available to generation."
            ),
        }
        if repair_reason is not None:
            payload["repair_feedback"] = (
                "The initial proposal consumed this slot but failed structural conformance: "
                f"{repair_reason}. This is the single permitted in-slot repair; return a complete "
                "replacement structured proposal without using market-result feedback."
            )
        return LLMRequest(
            request_id=(
                f"us-a0-{run_spec.run_spec_id[-12:]}-slot-{slot_index:02d}-attempt-{attempt_index}"
            ),
            model=self.model_id,
            instructions=instructions,
            input_text=json.dumps(payload, sort_keys=True, ensure_ascii=False),
            schema_name="finagent_us_a0_structured_candidate_v1",
            response_schema=self._schema(),
            max_output_tokens=512,
            temperature=1.0,
            metadata={
                "protocol_id": protocol.protocol_id,
                "run_spec_id": run_spec.run_spec_id,
                "slot_index": str(slot_index),
                "attempt_index": str(attempt_index),
                "prompt_template_id": self.prompt_template_id,
                "pricing_policy_id": DEEPSEEK_V4_PRICING_POLICY_ID,
            },
        )

    @staticmethod
    def _parse_payload(output_text: str) -> tuple[str, int, str]:
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_json:{exc.msg}") from exc
        if not isinstance(payload, dict):
            raise TypeError("structured_candidate_root_must_be_object")
        if set(payload) != {"kind", "window_bars", "hypothesis_summary"}:
            raise ValueError("structured_candidate_fields_do_not_match_schema")
        kind = payload.get("kind")
        window = payload.get("window_bars")
        summary = payload.get("hypothesis_summary")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("structured_candidate_kind_must_be_string")
        if isinstance(window, bool) or not isinstance(window, int):
            raise TypeError("structured_candidate_window_must_be_integer")
        if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 280:
            raise ValueError("structured_candidate_hypothesis_must_be_1_to_280_chars")
        return kind, window, summary

    def _proposal_from_response(
        self,
        response: LLMResponse,
        *,
        generated_at: datetime,
    ) -> tuple[StructuredCandidateProposal, str | None]:
        cost = estimate_deepseek_v4_cost_usd(
            self.model_id,
            response,
            priced_at=generated_at,
        )
        usage = CandidateGenerationUsage(
            llm_calls=1,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=response.latency_ms,
            cost_usd=cost,
        )
        try:
            kind, window, summary = self._parse_payload(response.output_text)
        except (TypeError, ValueError) as exc:
            proposal = StructuredCandidateProposal(
                kind="invalid_provider_output",
                window_bars=1,
                hypothesis_summary=(
                    "Provider output failed the frozen structured-candidate JSON contract."
                ),
                generated_at=generated_at,
                usage=usage,
            )
            return proposal, str(exc)
        return (
            StructuredCandidateProposal(
                kind=kind,
                window_bars=window,
                hypothesis_summary=summary,
                generated_at=generated_at,
                usage=usage,
            ),
            None,
        )

    @staticmethod
    def _classify(
        proposal: StructuredCandidateProposal,
        accepted_ids: set[str],
    ) -> _ClassifiedProposal:
        vocabulary = canonical_us_a0_primitive_vocabulary()
        try:
            kind = USBaselineFeatureKind(proposal.kind)
        except ValueError:
            return _ClassifiedProposal(CandidateValidationStatus.INVALID, None, "unsupported_kind")
        try:
            candidate = vocabulary.candidate(kind, proposal.window_bars)
        except ValueError:
            return _ClassifiedProposal(
                CandidateValidationStatus.INVALID,
                None,
                "window_outside_vocabulary",
            )
        if candidate.candidate_id in accepted_ids:
            return _ClassifiedProposal(
                CandidateValidationStatus.DUPLICATE,
                candidate,
                "duplicate_candidate",
            )
        return _ClassifiedProposal(CandidateValidationStatus.VALID_UNIQUE, candidate, None)

    def _complete(
        self,
        request: LLMRequest,
        *,
        task_id: str,
    ) -> tuple[LLMResponse, StructuredCandidateProposal, str | None]:
        try:
            response = self.configured_llm.provider.complete(request)
        except Exception as exc:
            if self.call_store is not None:
                self.call_store.record_failure(task_id, request, self.provider_id, exc)
            raise
        generated_at = self.clock().astimezone(UTC)
        proposal, parse_error = self._proposal_from_response(
            response,
            generated_at=generated_at,
        )
        return response, proposal, parse_error

    def _record_response(
        self,
        *,
        task_id: str,
        request: LLMRequest,
        response: LLMResponse,
        parse_error: str | None,
        classification: _ClassifiedProposal,
    ) -> None:
        if self.call_store is None:
            return
        validation_error = parse_error or classification.reason or ""
        self.call_store.record_response(
            task_id,
            request,
            response,
            planning_valid=(
                parse_error is None
                and classification.status is CandidateValidationStatus.VALID_UNIQUE
            ),
            validation_error=validation_error,
        )

    def generate_slots(
        self,
        protocol: USAgentValueExperimentProtocol,
        run_spec: CandidateGenerationRunSpec,
    ) -> tuple[ProposalSlot, ...]:
        if run_spec.protocol_id != protocol.protocol_id:
            raise ValueError("DeepSeek A0 run-spec/protocol identity mismatch")
        if run_spec.provider_id != self.provider_id:
            raise ValueError("DeepSeek A0 run-spec/provider identity mismatch")
        if run_spec.model_id != self.model_id:
            raise ValueError("DeepSeek A0 run-spec/model identity mismatch")
        if run_spec.prompt_template_id != self.prompt_template_id:
            raise ValueError("DeepSeek A0 run-spec/prompt-template identity mismatch")
        if run_spec.candidate_budget != protocol.candidate_budget_per_run:
            raise ValueError("DeepSeek A0 run-spec candidate budget mismatch")

        accepted_ids: set[str] = set()
        accepted_candidates: list[USAgentValueCandidateSpec] = []
        slots: list[ProposalSlot] = []
        for slot_index in range(1, protocol.candidate_budget_per_run + 1):
            initial_request = self._request(
                protocol,
                run_spec,
                slot_index=slot_index,
                attempt_index=0,
                accepted_candidates=tuple(accepted_candidates),
                repair_reason=None,
            )
            task_id = f"us-a0:{run_spec.run_spec_id}:slot:{slot_index}"
            initial_response, initial, parse_error = self._complete(
                initial_request,
                task_id=task_id,
            )
            initial_result = self._classify(initial, accepted_ids)
            self._record_response(
                task_id=task_id,
                request=initial_request,
                response=initial_response,
                parse_error=parse_error,
                classification=initial_result,
            )
            repair_reason = parse_error or initial_result.reason
            if initial_result.status is CandidateValidationStatus.VALID_UNIQUE:
                assert initial_result.candidate is not None
                accepted_ids.add(initial_result.candidate.candidate_id)
                accepted_candidates.append(initial_result.candidate)
                slots.append(ProposalSlot(initial=initial))
                continue

            repair_request = self._request(
                protocol,
                run_spec,
                slot_index=slot_index,
                attempt_index=1,
                accepted_candidates=tuple(accepted_candidates),
                repair_reason=repair_reason or "structural_conformance_failure",
            )
            repair_response, repair, repair_parse_error = self._complete(
                repair_request,
                task_id=task_id,
            )
            repair_result = self._classify(repair, accepted_ids)
            self._record_response(
                task_id=task_id,
                request=repair_request,
                response=repair_response,
                parse_error=repair_parse_error,
                classification=repair_result,
            )
            if repair_result.status is CandidateValidationStatus.VALID_UNIQUE:
                assert repair_result.candidate is not None
                accepted_ids.add(repair_result.candidate.candidate_id)
                accepted_candidates.append(repair_result.candidate)
            slots.append(ProposalSlot(initial=initial, repair=repair))
        return tuple(slots)


def configured_deepseek_structured_provider(
    configured_llm: ConfiguredLLM,
    *,
    call_store: LLMCallStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> DeepSeekStructuredAgentSlotProvider:
    return DeepSeekStructuredAgentSlotProvider(
        configured_llm,
        call_store=call_store,
        clock=clock,
    )
