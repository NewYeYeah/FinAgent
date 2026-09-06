from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

from finagent.research.us_a1_factor_graph import (
    FactorComplexityBudget,
    FactorGraphSpec,
    FactorHypothesisSpec,
)
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_r3_alpha_catalog import FrontierAlphaCandidate


def _canonical_hash(payload: object, *, prefix: str) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(rendered).hexdigest()[:24]}"


class AgentResearchCapability(StrEnum):
    PROPOSE_FACTOR_GRAPH = "PROPOSE_FACTOR_GRAPH"
    PROPOSE_HYPOTHESIS = "PROPOSE_HYPOTHESIS"
    PROPOSE_FALSIFICATION = "PROPOSE_FALSIFICATION"
    REQUEST_DETERMINISTIC_VALIDATION = "REQUEST_DETERMINISTIC_VALIDATION"


class AgentGeneratorType(StrEnum):
    MANUAL = "MANUAL"
    PROGRAMMATIC = "PROGRAMMATIC"
    AGENT = "AGENT"


@dataclass(frozen=True, slots=True)
class AgentResearchBoundaryPolicy:
    predecessor_review_id: str
    maximum_candidate_slots_per_run: int = 24
    maximum_generation_rounds: int = 3
    graph_budget: FactorComplexityBudget = field(default_factory=FactorComplexityBudget)
    allowed_capabilities: tuple[AgentResearchCapability, ...] = (
        AgentResearchCapability.PROPOSE_FACTOR_GRAPH,
        AgentResearchCapability.PROPOSE_HYPOTHESIS,
        AgentResearchCapability.PROPOSE_FALSIFICATION,
        AgentResearchCapability.REQUEST_DETERMINISTIC_VALIDATION,
    )
    forbidden_data_classes: tuple[str, ...] = (
        "labels",
        "candidate_performance",
        "holdout_or_reserve_evidence",
        "positions_or_fills",
        "broker_or_mt5_state",
    )
    schema_version: str = "finagent.us-r3-agent-research-boundary-policy.v1"

    def __post_init__(self) -> None:
        if not self.predecessor_review_id.strip():
            raise ValueError("agent boundary predecessor review must be non-empty")
        if min(self.maximum_candidate_slots_per_run, self.maximum_generation_rounds) < 1:
            raise ValueError("agent boundary generation limits must be positive")
        if len(self.allowed_capabilities) != len(set(self.allowed_capabilities)):
            raise ValueError("allowed agent capabilities must be unique")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r3-agent-boundary")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "predecessor_review_id": self.predecessor_review_id,
            "maximum_candidate_slots_per_run": self.maximum_candidate_slots_per_run,
            "maximum_generation_rounds": self.maximum_generation_rounds,
            "graph_budget": self.graph_budget.to_dict(),
            "allowed_capabilities": sorted(item.value for item in self.allowed_capabilities),
            "forbidden_data_classes": list(self.forbidden_data_classes),
            "proposal_representation": "typed_factor_graph_plus_structured_falsification",
            "arbitrary_code_authority": False,
            "financial_data_access_authority": False,
            "label_access_authority": False,
            "evaluation_feedback_authority": False,
            "threshold_mutation_authority": False,
            "candidate_selection_authority": False,
            "provider_tool_authority": False,
            "mt5_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class AgentFactorProposalEnvelope:
    generation_run_id: str
    slot: int
    round_number: int
    generator_type: AgentGeneratorType
    graph: FactorGraphSpec
    hypothesis: FactorHypothesisSpec
    requested_capabilities: tuple[AgentResearchCapability, ...]
    provider_id: str | None = None
    model_id: str | None = None
    prompt_template_id: str | None = None
    requested_data_classes: tuple[str, ...] = ()
    requested_tool_names: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r3-agent-factor-proposal-envelope.v1"

    def __post_init__(self) -> None:
        if not self.generation_run_id.strip():
            raise ValueError("generation_run_id must be non-empty")
        if self.slot < 0 or self.round_number < 1:
            raise ValueError("proposal slot/round must be non-negative and positive")
        if len(self.requested_capabilities) != len(set(self.requested_capabilities)):
            raise ValueError("requested capabilities must be unique")
        if self.generator_type is AgentGeneratorType.AGENT:
            if not all(
                item is not None and item.strip()
                for item in (self.provider_id, self.model_id, self.prompt_template_id)
            ):
                raise ValueError("Agent proposals require provider/model/prompt identities")
        elif any(
            item is not None for item in (self.provider_id, self.model_id, self.prompt_template_id)
        ):
            raise ValueError("non-Agent proposals cannot carry model identities")

    @property
    def proposal_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r3-agent-proposal")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "generation_run_id": self.generation_run_id,
            "slot": self.slot,
            "round_number": self.round_number,
            "generator_type": self.generator_type.value,
            "graph": self.graph.to_dict(),
            "hypothesis": self.hypothesis.to_dict(),
            "requested_capabilities": sorted(item.value for item in self.requested_capabilities),
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_template_id": self.prompt_template_id,
            "requested_data_classes": list(self.requested_data_classes),
            "requested_tool_names": list(self.requested_tool_names),
            "stored_reasoning_scope": "structured_hypothesis_and_falsification_only",
            "financial_performance_fields": [],
            "executable_content": False,
        }
        if include_id:
            payload["proposal_id"] = self.proposal_id
        return payload


@dataclass(frozen=True, slots=True)
class AgentProposalValidationEvidence:
    proposal_id: str
    policy_id: str
    valid: bool
    candidate_id: str | None
    graph_validation_evidence_id: str
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r3-agent-proposal-validation-evidence.v1"

    def __post_init__(self) -> None:
        if self.valid != (not self.blockers):
            raise ValueError("proposal validation valid flag must match blockers")
        if self.valid != (self.candidate_id is not None):
            raise ValueError("valid proposal validation requires candidate_id")

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r3-agent-validation")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "policy_id": self.policy_id,
            "valid": self.valid,
            "candidate_id": self.candidate_id,
            "graph_validation_evidence_id": self.graph_validation_evidence_id,
            "blockers": list(self.blockers),
            "financial_data_read": False,
            "labels_read": False,
            "evaluation_metrics_read": False,
            "mt5_accessed": False,
            "execution_attempted": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def canonical_us_r3_agent_boundary_policy() -> AgentResearchBoundaryPolicy:
    return AgentResearchBoundaryPolicy(
        predecessor_review_id="us-r2-alpha-gate-review-36d4d07f8dd0b3dbf70656de"
    )


def _budget_blockers(
    proposal: FactorComplexityBudget,
    admitted: FactorComplexityBudget,
) -> list[str]:
    blockers: list[str] = []
    for field_name in (
        "max_nodes",
        "max_edges",
        "max_depth",
        "max_window_bars",
        "max_lookback_bars",
        "max_regime_gates",
    ):
        if int(getattr(proposal, field_name)) > int(getattr(admitted, field_name)):
            blockers.append(f"graph_budget_exceeds_policy:{field_name}")
    return blockers


def validate_agent_factor_proposal(
    envelope: AgentFactorProposalEnvelope,
    *,
    policy: AgentResearchBoundaryPolicy | None = None,
) -> AgentProposalValidationEvidence:
    admitted = policy or canonical_us_r3_agent_boundary_policy()
    graph_evidence = validate_factor_graph(envelope.graph)
    blockers = list(graph_evidence.blockers)
    blockers.extend(_budget_blockers(envelope.graph.budget, admitted.graph_budget))
    if envelope.slot >= admitted.maximum_candidate_slots_per_run:
        blockers.append("candidate_slot_exceeds_policy")
    if envelope.round_number > admitted.maximum_generation_rounds:
        blockers.append("generation_round_exceeds_policy")
    for capability in envelope.requested_capabilities:
        if capability not in admitted.allowed_capabilities:
            blockers.append(f"capability_not_admitted:{capability.value}")
    if envelope.requested_data_classes:
        blockers.append("agent_data_access_requested")
    if envelope.requested_tool_names:
        blockers.append("agent_tool_access_requested")
    candidate_id: str | None = None
    if graph_evidence.canonicalization is not None:
        candidate_id = graph_evidence.canonicalization.candidate_id
        if envelope.hypothesis.candidate_id != candidate_id:
            blockers.append("hypothesis_candidate_id_mismatch")
        expected_inputs = graph_evidence.canonicalization.required_input_fields
        observed_inputs = tuple(
            sorted(item.value for item in envelope.hypothesis.required_input_fields)
        )
        if observed_inputs != expected_inputs:
            blockers.append("hypothesis_required_inputs_mismatch")
    blockers = list(dict.fromkeys(blockers))
    if blockers:
        candidate_id = None
    return AgentProposalValidationEvidence(
        proposal_id=envelope.proposal_id,
        policy_id=admitted.policy_id,
        valid=not blockers,
        candidate_id=candidate_id,
        graph_validation_evidence_id=graph_evidence.evidence_id,
        blockers=tuple(blockers),
    )


@dataclass(frozen=True, slots=True)
class USR3ResearchIterationPlan:
    agent_boundary_policy_id: str
    preregistered_candidate_ids: tuple[str, ...]
    manual_slots: int = 24
    programmatic_slots_per_seed: int = 24
    programmatic_seeds: tuple[int, ...] = (1729, 2718, 3141)
    agent_slots_per_run: int = 24
    agent_independent_run_count: int = 3
    schema_version: str = "finagent.us-r3-research-iteration-plan.v1"

    def __post_init__(self) -> None:
        if not self.agent_boundary_policy_id.strip() or not self.preregistered_candidate_ids:
            raise ValueError("US-R3 plan requires policy and candidate identities")
        if len(self.preregistered_candidate_ids) != len(set(self.preregistered_candidate_ids)):
            raise ValueError("US-R3 preregistered candidates must be unique")
        counts = (
            self.manual_slots,
            self.programmatic_slots_per_seed,
            self.agent_slots_per_run,
            self.agent_independent_run_count,
        )
        if any(item < 1 for item in counts) or len(self.programmatic_seeds) < 3:
            raise ValueError("US-R3 plan requires positive equal-arm budgets and >=3 seeds")
        if (
            len({self.manual_slots, self.programmatic_slots_per_seed, self.agent_slots_per_run})
            != 1
        ):
            raise ValueError("US-R3 search arms must have equal candidate-slot budgets")

    @property
    def plan_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r3-research-plan")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "agent_boundary_policy_id": self.agent_boundary_policy_id,
            "preregistered_candidate_ids": list(self.preregistered_candidate_ids),
            "manual_slots": self.manual_slots,
            "programmatic_slots_per_seed": self.programmatic_slots_per_seed,
            "programmatic_seeds": list(self.programmatic_seeds),
            "agent_slots_per_run": self.agent_slots_per_run,
            "agent_independent_run_count": self.agent_independent_run_count,
            "certified_input_scope": "local_us_ohlcv_only_no_mt5",
            "r2_corpus_reuse_authority": "development_and_exploratory_only",
            "independent_alpha_gate_requirement": "new_post_r2_or_independent_sealed_evidence",
            "candidate_denominator_frozen_before_financial_evaluation": True,
            "performance_filtering_allowed": False,
            "direction_refit_allowed": False,
            "threshold_relaxation_allowed": False,
            "agent_evaluation_feedback_allowed": False,
            "mt5_required": False,
            "alpha_authority": False,
            "execution_authority": False,
        }
        if include_id:
            payload["plan_id"] = self.plan_id
        return payload


def build_us_r3_research_iteration_plan(
    candidates: tuple[FrontierAlphaCandidate, ...],
) -> USR3ResearchIterationPlan:
    policy = canonical_us_r3_agent_boundary_policy()
    return USR3ResearchIterationPlan(
        agent_boundary_policy_id=policy.policy_id,
        preregistered_candidate_ids=tuple(sorted(item.candidate_id for item in candidates)),
    )
