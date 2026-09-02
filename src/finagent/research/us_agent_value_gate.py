from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from statistics import median

from finagent.research.us_agent_value_assembly import AgentValueExperimentEvidenceGraph
from finagent.research.us_agent_value_comparison import AgentValueComparisonSnapshot
from finagent.research.us_agent_value_execution import USAgentValueExecutionPlan
from finagent.research.us_agent_value_experiment import (
    AgentValueExperiment,
    RunEvaluationLink,
    SearchArmResult,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
)


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


def _complete_metric_values(
    links: tuple[RunEvaluationLink, ...],
    field_name: str,
) -> tuple[float, ...] | None:
    values: list[float] = []
    for link in links:
        value = getattr(link, field_name)
        if value is None:
            return None
        values.append(float(value))
    return tuple(values)


def _median_or_none(values: tuple[float, ...] | None) -> float | None:
    if values is None or not values:
        return None
    return float(median(values))


def _agent_usage(result: SearchArmResult) -> tuple[int, int, float, float]:
    llm_calls = sum(run.usage.llm_calls for run in result.generation_runs)
    total_tokens = sum(run.usage.total_tokens for run in result.generation_runs)
    latency_ms = sum(run.usage.latency_ms for run in result.generation_runs)
    cost_usd = sum(run.usage.cost_usd for run in result.generation_runs)
    return llm_calls, total_tokens, latency_ms, cost_usd


class USAgentValueGateDecision(StrEnum):
    PILOT_PROCEED_TO_FORMAL = "PILOT_PROCEED_TO_FORMAL"
    PILOT_DO_NOT_PROCEED_TO_FORMAL = "PILOT_DO_NOT_PROCEED_TO_FORMAL"
    FORMAL_INCREMENTAL_VALUE_SUPPORTED = "FORMAL_INCREMENTAL_VALUE_SUPPORTED"
    FORMAL_NO_INCREMENTAL_VALUE = "FORMAL_NO_INCREMENTAL_VALUE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class USAgentValueGatePolicy:
    protocol_id: str
    phase: USAgentValuePhase
    practical_rank_ic_margin: float
    required_agent_run_win_numerator: int
    required_agent_run_win_denominator: int
    valid_candidate_rate_noninferiority_tolerance: float
    failure_rate_noninferiority_tolerance: float
    meaningful_efficiency_advantage_margin: float
    minimum_agent_novel_candidate_count: int
    schema_version: str = "finagent.us-agent-value-gate-policy.v1"

    def __post_init__(self) -> None:
        protocol = canonical_us_a0_experiment_protocol(self.phase)
        if self.protocol_id != protocol.protocol_id:
            raise ValueError("Agent Value Gate policy phase/protocol identity mismatch")
        if not math.isfinite(self.practical_rank_ic_margin) or self.practical_rank_ic_margin <= 0:
            raise ValueError("practical_rank_ic_margin must be finite and positive")
        if self.required_agent_run_win_numerator < 1:
            raise ValueError("required_agent_run_win_numerator must be positive")
        if self.required_agent_run_win_denominator < self.required_agent_run_win_numerator:
            raise ValueError("required Agent run-win fraction must be in (0,1]")
        for field_name in (
            "valid_candidate_rate_noninferiority_tolerance",
            "failure_rate_noninferiority_tolerance",
            "meaningful_efficiency_advantage_margin",
        ):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be finite and in [0,1]")
        if self.minimum_agent_novel_candidate_count < 1:
            raise ValueError("minimum_agent_novel_candidate_count must be positive")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-gate-policy",
        )

    def required_agent_run_wins(self, run_count: int) -> int:
        if run_count < 1:
            raise ValueError("run_count must be positive")
        return math.ceil(
            run_count
            * self.required_agent_run_win_numerator
            / self.required_agent_run_win_denominator
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "phase": self.phase.value,
            "primary_quality_metric": "best_worst_fold_rank_ic",
            "secondary_quality_metric": "best_mean_rank_ic",
            "practical_rank_ic_margin": self.practical_rank_ic_margin,
            "required_agent_run_win_fraction": {
                "numerator": self.required_agent_run_win_numerator,
                "denominator": self.required_agent_run_win_denominator,
            },
            "valid_candidate_rate_noninferiority_tolerance": (
                self.valid_candidate_rate_noninferiority_tolerance
            ),
            "failure_rate_noninferiority_tolerance": self.failure_rate_noninferiority_tolerance,
            "meaningful_efficiency_advantage_margin": self.meaningful_efficiency_advantage_margin,
            "minimum_agent_novel_candidate_count": self.minimum_agent_novel_candidate_count,
            "positive_rule": (
                "median quality superiority versus MANUAL and PROGRAMMATIC by the practical "
                "margin, preregistered run-level repeatability, PROGRAMMATIC-relative search "
                "efficiency non-inferiority, and at least one structurally novel AGENT candidate"
            ),
            "negative_rule": (
                "no AGENT run is better than both MANUAL and its ordinal-matched PROGRAMMATIC "
                "run on both quality metrics, and AGENT has no meaningful search-efficiency advantage"
            ),
            "inconclusive_rule": "all complete-evidence outcomes between positive and negative rules",
            "cost_treatment": (
                "recorded_and_reported_as_diagnostic_in_v1_no_provider-independent_usd_ceiling"
            ),
            "statistical_interpretation": (
                "preregistered_practical_effect_rule_not_a_p_value_or_deployment_alpha_claim"
            ),
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_a0_agent_value_gate_policy(
    phase: USAgentValuePhase,
) -> USAgentValueGatePolicy:
    protocol = canonical_us_a0_experiment_protocol(phase)
    if phase is USAgentValuePhase.PILOT:
        numerator, denominator = 1, 1
    else:
        numerator, denominator = 2, 3
    return USAgentValueGatePolicy(
        protocol_id=protocol.protocol_id,
        phase=phase,
        practical_rank_ic_margin=0.01,
        required_agent_run_win_numerator=numerator,
        required_agent_run_win_denominator=denominator,
        valid_candidate_rate_noninferiority_tolerance=0.10,
        failure_rate_noninferiority_tolerance=0.10,
        meaningful_efficiency_advantage_margin=0.10,
        minimum_agent_novel_candidate_count=1,
    )


def validate_us_a0_agent_value_gate_policy(
    document: dict[str, object],
    phase: USAgentValuePhase,
) -> USAgentValueGatePolicy:
    expected = canonical_us_a0_agent_value_gate_policy(phase)
    if document != expected.to_dict():
        raise ValueError("Agent Value Gate policy does not match the exact frozen canonical policy")
    return expected


@dataclass(frozen=True, slots=True)
class USAgentValueGateAssessment:
    policy_id: str
    execution_plan_id: str
    experiment_id: str
    comparison_snapshot_id: str
    evidence_graph_id: str
    predecessor_binding_id: str
    phase: USAgentValuePhase
    decision: USAgentValueGateDecision
    manual_primary_quality: float | None
    programmatic_median_primary_quality: float | None
    agent_median_primary_quality: float | None
    manual_secondary_quality: float | None
    programmatic_median_secondary_quality: float | None
    agent_median_secondary_quality: float | None
    paired_quality_win_count: int
    required_paired_quality_win_count: int
    programmatic_valid_candidate_rate: float
    agent_valid_candidate_rate: float
    programmatic_failure_rate: float
    agent_failure_rate: float
    agent_novel_candidate_count: int
    agent_llm_calls: int
    agent_total_tokens: int
    agent_latency_ms: float
    agent_cost_usd: float
    baseline_quality_available: bool
    complete_quality_vectors: bool
    median_quality_superiority_passed: bool
    repeatability_passed: bool
    efficiency_noninferiority_passed: bool
    novelty_support_passed: bool
    positive_rule_passed: bool
    quality_not_better: bool
    meaningful_efficiency_advantage: bool
    reasons: tuple[str, ...]
    schema_version: str = "finagent.us-agent-value-gate-assessment.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "policy_id",
            "execution_plan_id",
            "experiment_id",
            "comparison_snapshot_id",
            "evidence_graph_id",
            "predecessor_binding_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.paired_quality_win_count < 0:
            raise ValueError("paired_quality_win_count must be non-negative")
        if self.required_paired_quality_win_count < 1:
            raise ValueError("required_paired_quality_win_count must be positive")
        for field_name in (
            "programmatic_valid_candidate_rate",
            "agent_valid_candidate_rate",
            "programmatic_failure_rate",
            "agent_failure_rate",
        ):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be in [0,1]")
        if self.agent_novel_candidate_count < 0:
            raise ValueError("agent_novel_candidate_count must be non-negative")
        if self.agent_llm_calls < 0 or self.agent_total_tokens < 0:
            raise ValueError("Agent usage counts must be non-negative")
        if not math.isfinite(self.agent_latency_ms) or self.agent_latency_ms < 0:
            raise ValueError("agent_latency_ms must be finite and non-negative")
        if not math.isfinite(self.agent_cost_usd) or self.agent_cost_usd < 0:
            raise ValueError("agent_cost_usd must be finite and non-negative")

    @property
    def assessment_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-gate-assessment",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "execution_plan_id": self.execution_plan_id,
            "experiment_id": self.experiment_id,
            "comparison_snapshot_id": self.comparison_snapshot_id,
            "evidence_graph_id": self.evidence_graph_id,
            "predecessor_binding_id": self.predecessor_binding_id,
            "phase": self.phase.value,
            "decision": self.decision.value,
            "manual_primary_quality": self.manual_primary_quality,
            "programmatic_median_primary_quality": self.programmatic_median_primary_quality,
            "agent_median_primary_quality": self.agent_median_primary_quality,
            "manual_secondary_quality": self.manual_secondary_quality,
            "programmatic_median_secondary_quality": self.programmatic_median_secondary_quality,
            "agent_median_secondary_quality": self.agent_median_secondary_quality,
            "paired_quality_win_count": self.paired_quality_win_count,
            "required_paired_quality_win_count": self.required_paired_quality_win_count,
            "programmatic_valid_candidate_rate": self.programmatic_valid_candidate_rate,
            "agent_valid_candidate_rate": self.agent_valid_candidate_rate,
            "programmatic_failure_rate": self.programmatic_failure_rate,
            "agent_failure_rate": self.agent_failure_rate,
            "agent_novel_candidate_count": self.agent_novel_candidate_count,
            "agent_usage": {
                "llm_calls": self.agent_llm_calls,
                "total_tokens": self.agent_total_tokens,
                "latency_ms": self.agent_latency_ms,
                "cost_usd": self.agent_cost_usd,
            },
            "criteria": {
                "baseline_quality_available": self.baseline_quality_available,
                "complete_quality_vectors": self.complete_quality_vectors,
                "median_quality_superiority_passed": self.median_quality_superiority_passed,
                "repeatability_passed": self.repeatability_passed,
                "efficiency_noninferiority_passed": self.efficiency_noninferiority_passed,
                "novelty_support_passed": self.novelty_support_passed,
                "positive_rule_passed": self.positive_rule_passed,
                "quality_not_better": self.quality_not_better,
                "meaningful_efficiency_advantage": self.meaningful_efficiency_advantage,
            },
            "reasons": list(self.reasons),
            "recommendation_authority": "deterministic_preregistered_policy_only",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["assessment_id"] = self.assessment_id
        return payload


def _arm_result(
    experiment: AgentValueExperiment,
    arm: USAgentValueArm,
) -> SearchArmResult:
    match = next((result for result in experiment.arm_results if result.arm is arm), None)
    if match is None:
        raise ValueError(f"Agent Value Gate experiment is missing {arm.value} arm evidence")
    return match


def _validate_gate_lineage(
    *,
    policy: USAgentValueGatePolicy,
    execution_plan: USAgentValueExecutionPlan,
    experiment: AgentValueExperiment,
    comparison: AgentValueComparisonSnapshot,
    evidence_graph: AgentValueExperimentEvidenceGraph,
) -> tuple[SearchArmResult, SearchArmResult, SearchArmResult]:
    protocol: USAgentValueExperimentProtocol = experiment.protocol
    if policy.protocol_id != protocol.protocol_id or policy.phase is not protocol.phase:
        raise ValueError("Agent Value Gate policy/experiment protocol identity mismatch")
    if execution_plan.protocol_id != protocol.protocol_id or execution_plan.phase is not protocol.phase:
        raise ValueError("Agent Value Gate execution-plan/experiment identity mismatch")
    if evidence_graph.execution_plan_id != execution_plan.plan_id:
        raise ValueError("Agent Value Gate evidence graph/execution-plan identity mismatch")
    if evidence_graph.experiment_id != experiment.experiment_id:
        raise ValueError("Agent Value Gate evidence graph/experiment identity mismatch")
    if evidence_graph.comparison_snapshot_id != comparison.snapshot_id:
        raise ValueError("Agent Value Gate evidence graph/comparison identity mismatch")
    if evidence_graph.predecessor_binding_id != experiment.predecessor.binding_id:
        raise ValueError("Agent Value Gate evidence graph/predecessor identity mismatch")
    if not experiment.evidence_complete:
        raise ValueError("Agent Value Gate requires a complete three-arm experiment")
    if not evidence_graph.evidence_complete or not evidence_graph.ready_for_agent_value_gate_review:
        raise ValueError("Agent Value Gate requires complete review-ready experiment evidence")

    manual = _arm_result(experiment, USAgentValueArm.MANUAL)
    programmatic = _arm_result(experiment, USAgentValueArm.PROGRAMMATIC)
    agent = _arm_result(experiment, USAgentValueArm.AGENT)
    if comparison.protocol_id != protocol.protocol_id:
        raise ValueError("Agent Value Gate comparison/experiment protocol mismatch")
    if comparison.manual_result_id != manual.result_id:
        raise ValueError("Agent Value Gate comparison/MANUAL result identity mismatch")
    if comparison.programmatic_result_id != programmatic.result_id:
        raise ValueError("Agent Value Gate comparison/PROGRAMMATIC result identity mismatch")
    if comparison.agent_result_id != agent.result_id:
        raise ValueError("Agent Value Gate comparison/AGENT result identity mismatch")
    if evidence_graph.arm_result_ids != tuple(result.result_id for result in experiment.arm_results):
        raise ValueError("Agent Value Gate evidence graph/arm-result identity mismatch")

    for arm, result in (
        (USAgentValueArm.MANUAL, manual),
        (USAgentValueArm.PROGRAMMATIC, programmatic),
        (USAgentValueArm.AGENT, agent),
    ):
        planned = tuple(spec for spec in execution_plan.run_specs if spec.arm is arm)
        actual = tuple(run.spec for run in result.generation_runs)
        if actual != planned:
            raise ValueError(f"Agent Value Gate {arm.value} run set differs from ExecutionPlan")
    return manual, programmatic, agent


def assess_us_a0_agent_value_gate(
    *,
    policy: USAgentValueGatePolicy,
    execution_plan: USAgentValueExecutionPlan,
    experiment: AgentValueExperiment,
    comparison: AgentValueComparisonSnapshot,
    evidence_graph: AgentValueExperimentEvidenceGraph,
) -> USAgentValueGateAssessment:
    manual, programmatic, agent = _validate_gate_lineage(
        policy=policy,
        execution_plan=execution_plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=evidence_graph,
    )
    if len(manual.evaluation_links) != 1:
        raise ValueError("Agent Value Gate requires exactly one MANUAL evaluation link")
    if len(programmatic.evaluation_links) != len(agent.evaluation_links):
        raise ValueError("Agent Value Gate requires equal PROGRAMMATIC and AGENT run counts")

    manual_primary = manual.evaluation_links[0].best_worst_fold_rank_ic
    manual_secondary = manual.evaluation_links[0].best_mean_rank_ic
    programmatic_primary = _complete_metric_values(
        programmatic.evaluation_links,
        "best_worst_fold_rank_ic",
    )
    programmatic_secondary = _complete_metric_values(
        programmatic.evaluation_links,
        "best_mean_rank_ic",
    )
    agent_primary = _complete_metric_values(agent.evaluation_links, "best_worst_fold_rank_ic")
    agent_secondary = _complete_metric_values(agent.evaluation_links, "best_mean_rank_ic")

    baseline_quality_available = (
        manual_primary is not None
        and manual_secondary is not None
        and programmatic_primary is not None
        and programmatic_secondary is not None
    )
    complete_quality_vectors = (
        baseline_quality_available and agent_primary is not None and agent_secondary is not None
    )
    programmatic_median_primary = _median_or_none(programmatic_primary)
    programmatic_median_secondary = _median_or_none(programmatic_secondary)
    agent_median_primary = _median_or_none(agent_primary)
    agent_median_secondary = _median_or_none(agent_secondary)

    median_quality_superiority = False
    paired_quality_win_count = 0
    if complete_quality_vectors:
        assert manual_primary is not None
        assert manual_secondary is not None
        assert programmatic_primary is not None
        assert programmatic_secondary is not None
        assert agent_primary is not None
        assert agent_secondary is not None
        assert programmatic_median_primary is not None
        assert programmatic_median_secondary is not None
        assert agent_median_primary is not None
        assert agent_median_secondary is not None
        margin = policy.practical_rank_ic_margin
        median_quality_superiority = (
            agent_median_primary
            >= max(float(manual_primary), programmatic_median_primary) + margin
            and agent_median_secondary
            >= max(float(manual_secondary), programmatic_median_secondary) + margin
        )
        paired_quality_win_count = sum(
            agent_primary[index]
            >= max(float(manual_primary), programmatic_primary[index]) + margin
            and agent_secondary[index]
            >= max(float(manual_secondary), programmatic_secondary[index]) + margin
            for index in range(len(agent_primary))
        )

    required_paired_wins = policy.required_agent_run_wins(len(agent.evaluation_links))
    repeatability_passed = paired_quality_win_count >= required_paired_wins
    programmatic_failure_rate = programmatic.invalid_rate + programmatic.duplicate_rate
    agent_failure_rate = agent.invalid_rate + agent.duplicate_rate
    efficiency_noninferiority = (
        agent.valid_candidate_rate
        >= programmatic.valid_candidate_rate
        - policy.valid_candidate_rate_noninferiority_tolerance
        and agent_failure_rate
        <= programmatic_failure_rate + policy.failure_rate_noninferiority_tolerance
    )
    meaningful_efficiency_advantage = (
        agent.valid_candidate_rate
        >= programmatic.valid_candidate_rate + policy.meaningful_efficiency_advantage_margin
        or agent_failure_rate
        <= programmatic_failure_rate - policy.meaningful_efficiency_advantage_margin
    )
    agent_novel_count = len(
        comparison.novelty.agent_novel_vs_manual_and_programmatic
    )
    novelty_support = agent_novel_count >= policy.minimum_agent_novel_candidate_count
    positive_rule_passed = (
        median_quality_superiority
        and repeatability_passed
        and efficiency_noninferiority
        and novelty_support
    )

    quality_not_better = False
    if baseline_quality_available:
        assert manual_primary is not None
        assert manual_secondary is not None
        assert programmatic_primary is not None
        assert programmatic_secondary is not None
        quality_not_better = all(
            (
                agent.evaluation_links[index].best_worst_fold_rank_ic is None
                or float(agent.evaluation_links[index].best_worst_fold_rank_ic)
                <= max(float(manual_primary), programmatic_primary[index])
            )
            and (
                agent.evaluation_links[index].best_mean_rank_ic is None
                or float(agent.evaluation_links[index].best_mean_rank_ic)
                <= max(float(manual_secondary), programmatic_secondary[index])
            )
            for index in range(len(agent.evaluation_links))
        )

    if positive_rule_passed:
        decision = (
            USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL
            if policy.phase is USAgentValuePhase.PILOT
            else USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED
        )
    elif baseline_quality_available and quality_not_better and not meaningful_efficiency_advantage:
        decision = (
            USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL
            if policy.phase is USAgentValuePhase.PILOT
            else USAgentValueGateDecision.FORMAL_NO_INCREMENTAL_VALUE
        )
    else:
        decision = USAgentValueGateDecision.INCONCLUSIVE

    reasons: list[str] = []
    if positive_rule_passed:
        reasons.append("positive_rule_passed")
    else:
        if not baseline_quality_available:
            reasons.append("baseline_quality_metrics_incomplete")
        if not complete_quality_vectors:
            reasons.append("agent_or_baseline_quality_vector_incomplete")
        if not median_quality_superiority:
            reasons.append("median_quality_superiority_not_met")
        if not repeatability_passed:
            reasons.append("run_level_repeatability_not_met")
        if not efficiency_noninferiority:
            reasons.append("search_efficiency_noninferiority_not_met")
        if not novelty_support:
            reasons.append("structural_novelty_support_not_met")
        if quality_not_better:
            reasons.append("agent_quality_not_better_than_both_baselines")
        if meaningful_efficiency_advantage:
            reasons.append("meaningful_search_efficiency_advantage_observed")

    llm_calls, total_tokens, latency_ms, cost_usd = _agent_usage(agent)
    return USAgentValueGateAssessment(
        policy_id=policy.policy_id,
        execution_plan_id=execution_plan.plan_id,
        experiment_id=experiment.experiment_id,
        comparison_snapshot_id=comparison.snapshot_id,
        evidence_graph_id=evidence_graph.graph_id,
        predecessor_binding_id=experiment.predecessor.binding_id,
        phase=policy.phase,
        decision=decision,
        manual_primary_quality=(None if manual_primary is None else float(manual_primary)),
        programmatic_median_primary_quality=programmatic_median_primary,
        agent_median_primary_quality=agent_median_primary,
        manual_secondary_quality=(None if manual_secondary is None else float(manual_secondary)),
        programmatic_median_secondary_quality=programmatic_median_secondary,
        agent_median_secondary_quality=agent_median_secondary,
        paired_quality_win_count=paired_quality_win_count,
        required_paired_quality_win_count=required_paired_wins,
        programmatic_valid_candidate_rate=programmatic.valid_candidate_rate,
        agent_valid_candidate_rate=agent.valid_candidate_rate,
        programmatic_failure_rate=programmatic_failure_rate,
        agent_failure_rate=agent_failure_rate,
        agent_novel_candidate_count=agent_novel_count,
        agent_llm_calls=llm_calls,
        agent_total_tokens=total_tokens,
        agent_latency_ms=latency_ms,
        agent_cost_usd=cost_usd,
        baseline_quality_available=baseline_quality_available,
        complete_quality_vectors=complete_quality_vectors,
        median_quality_superiority_passed=median_quality_superiority,
        repeatability_passed=repeatability_passed,
        efficiency_noninferiority_passed=efficiency_noninferiority,
        novelty_support_passed=novelty_support,
        positive_rule_passed=positive_rule_passed,
        quality_not_better=quality_not_better,
        meaningful_efficiency_advantage=meaningful_efficiency_advantage,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class USAgentValueGateReview:
    assessment: USAgentValueGateAssessment
    reviewer_id: str
    reviewed_at: datetime
    decision: USAgentValueGateDecision
    review_notes: str
    thresholds_unchanged_attested: bool
    evidence_lineage_attested: bool
    alpha_gate_separation_attested: bool
    stage_authority_separation_attested: bool
    schema_version: str = "finagent.us-agent-value-gate-review.v1"

    def __post_init__(self) -> None:
        reviewer = self.reviewer_id.strip()
        if not reviewer:
            raise ValueError("reviewer_id must be non-empty")
        object.__setattr__(self, "reviewer_id", reviewer)
        object.__setattr__(self, "reviewed_at", _aware_utc(self.reviewed_at, "reviewed_at"))
        notes = self.review_notes.strip()
        if not notes or len(notes) > 2000:
            raise ValueError("review_notes must contain 1..2000 characters")
        object.__setattr__(self, "review_notes", notes)
        if not all(
            (
                self.thresholds_unchanged_attested,
                self.evidence_lineage_attested,
                self.alpha_gate_separation_attested,
                self.stage_authority_separation_attested,
            )
        ):
            raise ValueError("all Agent Value Gate review attestations must be true")
        allowed = {self.assessment.decision, USAgentValueGateDecision.INCONCLUSIVE}
        if self.decision not in allowed:
            raise ValueError("reviewer may accept the assessment or downgrade it to INCONCLUSIVE only")
        if self.assessment.decision is USAgentValueGateDecision.INCONCLUSIVE:
            if self.decision is not USAgentValueGateDecision.INCONCLUSIVE:
                raise ValueError("INCONCLUSIVE machine assessment cannot be upgraded by review")
        if self.decision is USAgentValueGateDecision.INCONCLUSIVE and (
            self.assessment.decision is not USAgentValueGateDecision.INCONCLUSIVE
        ):
            if len(notes) < 20:
                raise ValueError("downgrading to INCONCLUSIVE requires substantive review notes")

    @property
    def review_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-gate-review",
        )

    @property
    def formal_progression_authority(self) -> bool:
        return (
            self.assessment.phase is USAgentValuePhase.PILOT
            and self.decision is USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL
        )

    @property
    def agent_value_gate_authority(self) -> bool:
        return self.assessment.phase is USAgentValuePhase.FORMAL

    @property
    def supports_agent_retention_for_us_r1(self) -> bool:
        return self.decision is USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED

    @property
    def supports_agent_scope_contraction(self) -> bool:
        return self.decision in {
            USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
            USAgentValueGateDecision.FORMAL_NO_INCREMENTAL_VALUE,
        }

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "assessment": self.assessment.to_dict(),
            "assessment_id": self.assessment.assessment_id,
            "policy_id": self.assessment.policy_id,
            "phase": self.assessment.phase.value,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at.isoformat(),
            "decision": self.decision.value,
            "review_notes": self.review_notes,
            "attestations": {
                "thresholds_unchanged_after_result": self.thresholds_unchanged_attested,
                "evidence_lineage_verified": self.evidence_lineage_attested,
                "alpha_gate_is_separate": self.alpha_gate_separation_attested,
                "project_stage_authority_is_separate": self.stage_authority_separation_attested,
            },
            "formal_progression_authority": self.formal_progression_authority,
            "agent_value_gate_authority": self.agent_value_gate_authority,
            "supports_agent_retention_for_us_r1": self.supports_agent_retention_for_us_r1,
            "supports_agent_scope_contraction": self.supports_agent_scope_contraction,
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["review_id"] = self.review_id
        return payload


def finalize_us_a0_agent_value_gate_review(
    assessment: USAgentValueGateAssessment,
    *,
    reviewer_id: str,
    reviewed_at: datetime,
    review_notes: str,
    decision: USAgentValueGateDecision | None = None,
    thresholds_unchanged_attested: bool,
    evidence_lineage_attested: bool,
    alpha_gate_separation_attested: bool,
    stage_authority_separation_attested: bool,
) -> USAgentValueGateReview:
    return USAgentValueGateReview(
        assessment=assessment,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        decision=assessment.decision if decision is None else decision,
        review_notes=review_notes,
        thresholds_unchanged_attested=thresholds_unchanged_attested,
        evidence_lineage_attested=evidence_lineage_attested,
        alpha_gate_separation_attested=alpha_gate_separation_attested,
        stage_authority_separation_attested=stage_authority_separation_attested,
    )


def validate_pilot_gate_review_for_formal_progression(
    document: dict[str, object],
    *,
    expected_review_id: str | None = None,
) -> str:
    if document.get("schema_version") != "finagent.us-agent-value-gate-review.v1":
        raise ValueError("formal A0 requires Agent Value Gate review schema v1")
    claimed_review_id = str(document.get("review_id", "")).strip()
    if not claimed_review_id:
        raise ValueError("pilot gate review_id must be non-empty")
    payload = dict(document)
    del payload["review_id"]
    if claimed_review_id != _canonical_hash(payload, prefix="us-agent-value-gate-review"):
        raise ValueError("pilot gate review content identity mismatch")
    if expected_review_id is not None and claimed_review_id != expected_review_id:
        raise ValueError("pilot gate review does not match docs/status.toml authority")
    if document.get("phase") != USAgentValuePhase.PILOT.value:
        raise ValueError("formal A0 requires a PILOT gate review")
    if document.get("decision") != USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL.value:
        raise ValueError("formal A0 requires PILOT_PROCEED_TO_FORMAL")
    if document.get("formal_progression_authority") is not True:
        raise ValueError("pilot review does not authorize FORMAL progression")
    if document.get("agent_value_gate_authority") is not False:
        raise ValueError("PILOT review cannot claim final Agent Value Gate authority")
    for field_name in ("status_authority", "stage_exit_authority", "alpha_authority"):
        if document.get(field_name) is not False:
            raise ValueError(f"pilot gate review must keep {field_name}=false")
    attestations = document.get("attestations")
    if not isinstance(attestations, dict) or not all(attestations.values()):
        raise ValueError("formal A0 requires all PILOT gate-review attestations")
    return claimed_review_id
