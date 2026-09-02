from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from finagent.agents.providers import ConfiguredLLM, LLMCallStore, LLMRequest
from finagent.research.us_agent_value_deepseek import DeepSeekStructuredAgentSlotProvider
from finagent.research.us_agent_value_formal_generation import (
    USAgentValueFormalAgentAttemptEvidence,
)
from finagent.research.us_agent_value_formal_runtime import (
    USAgentValueFormalDeepSeekRuntimePolicy,
)
from finagent.research.us_agent_value_generation import CandidateGenerationRunSpec
from finagent.research.us_agent_value_protocol import (
    USAgentValueCandidateSpec,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
)


class FormalRuntimeBoundDeepSeekAttemptProvider(DeepSeekStructuredAgentSlotProvider):
    """Generate one persisted FORMAL initial/repair attempt at a time."""

    def __init__(
        self,
        configured_llm: ConfiguredLLM,
        *,
        runtime_policy: USAgentValueFormalDeepSeekRuntimePolicy,
        call_store: LLMCallStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if configured_llm.profile.provider != runtime_policy.provider_id:
            raise ValueError("FORMAL provider/profile provider identity mismatch")
        if configured_llm.profile.model != runtime_policy.model_id:
            raise ValueError("FORMAL provider/profile model identity mismatch")
        if configured_llm.profile.thinking is not runtime_policy.thinking_enabled:
            raise ValueError("FORMAL provider thinking identity mismatch")
        if (configured_llm.profile.reasoning_effort or "high") != runtime_policy.reasoning_effort:
            raise ValueError("FORMAL provider reasoning-effort identity mismatch")
        super().__init__(configured_llm, call_store=call_store, clock=clock)
        self.runtime_policy = runtime_policy

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
        request = super()._request(
            protocol,
            run_spec,
            slot_index=slot_index,
            attempt_index=attempt_index,
            accepted_candidates=accepted_candidates,
            repair_reason=repair_reason,
        )
        return replace(
            request,
            max_output_tokens=self.runtime_policy.max_output_tokens,
            temperature=None,
            metadata={
                **dict(request.metadata),
                "formal_runtime_policy_id": self.runtime_policy.runtime_policy_id,
                "pilot_gate_review_id": self.runtime_policy.pilot_gate_review_id,
                "reasoning_effort": self.runtime_policy.reasoning_effort,
                "max_output_tokens": str(self.runtime_policy.max_output_tokens),
            },
        )

    def generate_attempt(
        self,
        protocol: USAgentValueExperimentProtocol,
        run_spec: CandidateGenerationRunSpec,
        *,
        slot_index: int,
        attempt_index: int,
        accepted_candidates: tuple[USAgentValueCandidateSpec, ...],
        repair_reason: str | None,
    ) -> USAgentValueFormalAgentAttemptEvidence:
        if protocol.phase is not USAgentValuePhase.FORMAL:
            raise ValueError("FORMAL attempt provider requires FORMAL protocol")
        if run_spec.phase is not USAgentValuePhase.FORMAL:
            raise ValueError("FORMAL attempt provider requires FORMAL run spec")
        if run_spec.protocol_id != protocol.protocol_id:
            raise ValueError("FORMAL attempt run-spec/protocol identity mismatch")
        if run_spec.provider_id != self.provider_id or run_spec.model_id != self.model_id:
            raise ValueError("FORMAL attempt provider/model identity mismatch")
        if run_spec.prompt_template_id != self.prompt_template_id:
            raise ValueError("FORMAL attempt prompt-template identity mismatch")

        request = self._request(
            protocol,
            run_spec,
            slot_index=slot_index,
            attempt_index=attempt_index,
            accepted_candidates=accepted_candidates,
            repair_reason=repair_reason,
        )
        task_id = f"us-a0-formal:{run_spec.run_spec_id}:slot:{slot_index}:attempt:{attempt_index}"
        response, proposal, parse_error = self._complete(request, task_id=task_id)
        accepted_ids = {candidate.candidate_id for candidate in accepted_candidates}
        classification = self._classify(proposal, accepted_ids)
        self._record_response(
            task_id=task_id,
            request=request,
            response=response,
            parse_error=parse_error,
            classification=classification,
        )
        candidate_id = (
            None if classification.candidate is None else classification.candidate.candidate_id
        )
        return USAgentValueFormalAgentAttemptEvidence(
            execution_plan_id=self.runtime_policy.execution_plan_id,
            launch_bundle_id=self.runtime_policy.launch_bundle_id,
            runtime_policy_id=self.runtime_policy.runtime_policy_id,
            run_spec_id=run_spec.run_spec_id,
            run_ordinal=run_spec.run_ordinal,
            slot_index=slot_index,
            attempt_index=attempt_index,
            request_id=request.request_id,
            proposal=proposal,
            status=classification.status,
            candidate_id=candidate_id,
            classification_reason=classification.reason,
            provider_parse_error=parse_error,
        )
