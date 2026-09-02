from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRunSpec,
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_agent_value_provider import build_authorized_agent_generation_run


@dataclass(frozen=True)
class _ScriptedProvider:
    provider_id: str = "provider-test"
    model_id: str = "model-test"
    prompt_template_id: str = "prompt-test"

    def generate_slots(
        self,
        protocol: USAgentValueExperimentProtocol,
        run_spec: CandidateGenerationRunSpec,
    ) -> tuple[ProposalSlot, ...]:
        assert run_spec.arm is USAgentValueArm.AGENT
        candidates = canonical_us_a0_primitive_vocabulary().all_candidates()[
            : protocol.candidate_budget_per_run
        ]
        timestamp = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
        return tuple(
            ProposalSlot(
                initial=StructuredCandidateProposal(
                    kind=candidate.kind.value,
                    window_bars=candidate.window_bars,
                    hypothesis_summary="Scripted structured Agent proposal.",
                    generated_at=timestamp,
                    usage=CandidateGenerationUsage(
                        llm_calls=1,
                        input_tokens=12,
                        output_tokens=6,
                        latency_ms=25.0,
                        cost_usd=0.0005,
                    ),
                )
            )
            for candidate in candidates
        )


def _plan():
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    return protocol, build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id="bundle-test",
        programmatic_seeds=(1729,),
        agent_provider_id="provider-test",
        agent_model_id="model-test",
        agent_prompt_template_id="prompt-test",
    )


def test_provider_neutral_agent_seam_preserves_plan_identity_and_generation_contract() -> None:
    protocol, plan = _plan()
    spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)

    run = build_authorized_agent_generation_run(
        protocol,
        plan,
        spec.run_spec_id,
        _ScriptedProvider(),
    )

    assert run.spec == spec
    assert len(run.accepted_candidates) == protocol.candidate_budget_per_run
    assert run.usage.llm_calls == protocol.candidate_budget_per_run
    assert run.to_dict()["replacement_count"] == 0


def test_provider_neutral_agent_seam_rejects_model_identity_drift() -> None:
    protocol, plan = _plan()
    spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    provider = _ScriptedProvider(model_id="different-model")

    with pytest.raises(ValueError, match="model_id"):
        build_authorized_agent_generation_run(
            protocol,
            plan,
            spec.run_spec_id,
            provider,
        )
