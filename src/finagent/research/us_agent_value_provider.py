from __future__ import annotations

from typing import Protocol

from finagent.research.us_agent_value_execution import USAgentValueExecutionPlan
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRun,
    CandidateGenerationRunSpec,
    ProposalSlot,
    build_candidate_generation_run,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueExperimentProtocol,
)


class StructuredAgentSlotProvider(Protocol):
    """Provider-neutral seam for a preregistered structured AGENT run.

    Implementations may call any external model, but they may only return the already-frozen
    ``ProposalSlot`` structure. Hidden reasoning is neither required nor accepted by this seam.
    Usage/cost/latency metadata remains part of each ``StructuredCandidateProposal`` and is
    validated by the existing candidate-generation contract.
    """

    @property
    def provider_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def prompt_template_id(self) -> str: ...

    def generate_slots(
        self,
        protocol: USAgentValueExperimentProtocol,
        run_spec: CandidateGenerationRunSpec,
    ) -> tuple[ProposalSlot, ...]: ...


def build_authorized_agent_generation_run(
    protocol: USAgentValueExperimentProtocol,
    execution_plan: USAgentValueExecutionPlan,
    run_spec_id: str,
    provider: StructuredAgentSlotProvider,
) -> CandidateGenerationRun:
    """Build one AGENT run without permitting provider-specific experiment drift."""

    if execution_plan.protocol_id != protocol.protocol_id or execution_plan.phase is not protocol.phase:
        raise ValueError("Agent provider execution-plan/protocol identity mismatch")
    spec = execution_plan.run_spec(run_spec_id)
    if spec.arm is not USAgentValueArm.AGENT:
        raise ValueError("provider-neutral Agent seam may only execute an AGENT run spec")
    if spec.provider_id != provider.provider_id:
        raise ValueError("Agent provider_id does not match the preregistered run spec")
    if spec.model_id != provider.model_id:
        raise ValueError("Agent model_id does not match the preregistered run spec")
    if spec.prompt_template_id != provider.prompt_template_id:
        raise ValueError("Agent prompt_template_id does not match the preregistered run spec")

    slots = provider.generate_slots(protocol, spec)
    return build_candidate_generation_run(protocol, spec, slots)
