"""Preregistered R4 resources and host decisions, separate from campaign results."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Any

from finagent.agents.r3_contracts import canonical_json, identity
from finagent.agents.r4_contracts import ALLOCATORS, AUTHORITY, R4Tool

PRIMARY_TOOLS = tuple(
    t.value
    for t in R4Tool
    if t.value
    not in {
        "propose_factor",
        "validate_factor",
        "evaluate_factor",
        "retire_hypothesis",
    }
)
DISCOVERY_TOOLS = tuple(t.value for t in R4Tool)


@dataclass(frozen=True)
class R4MatchedComparisonProtocol:
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return dict(json.loads(self.payload_json))

    @property
    def protocol_id(self) -> str:
        return identity(self.to_dict(), "r4-matched-protocol")


def matched_protocol(
    *,
    version: str,
    frozen_at: str,
    provider_admission_id: str,
    research_admission_id: str,
    initial_factor_ids: list[str],
    folds: list[dict[str, Any]],
) -> R4MatchedComparisonProtocol:
    ids = sorted(initial_factor_ids)
    if len(ids) != 3 or len(set(ids)) != 3:
        raise ValueError("v1 freezes the three existing R3 executable frontier factors")
    schedule = [ids, *[[f for f in ids if f != omitted] for omitted in ids]]
    budgets = {
        "factor_proposals": 0,
        "factor_evaluations": 0,
        "factor_set_proposals": 4,
        "portfolio_evaluations": 4,
        "tool_calls": 48,
        "total_tokens": 1048576,
        "cost_microusd": 2400000,
        "wall_clock_seconds": 7200,
    }
    return R4MatchedComparisonProtocol(
        canonical_json(
            {
                "protocol_version": version,
                "frozen_at": frozen_at,
                "objective": "Within the admitted exposed development folds, assess whether bounded Agent factor selection and allocation improve on frozen deterministic research; retain negative and failed trials; recommend only development evidence.",
                "provider_admission_id": provider_admission_id,
                "research_admission_id": research_admission_id,
                "initial_factor_ids": ids,
                "mandatory_allocators": list(ALLOCATORS),
                "primary": {
                    "arms": ["deterministic_selection", "agent_selection"],
                    "comparators": [
                        "equal_weight_full_pool",
                        "best_frozen_deterministic",
                        "regime_conditional_full_pool",
                    ],
                    "deterministic_factor_sets": schedule,
                    "tools": list(PRIMARY_TOOLS),
                    "budgets": budgets,
                    "matched_resources": ["factor_set_proposals", "portfolio_evaluations"],
                    "deterministic_llm_calls_tokens_cost": 0,
                    "selection": "Agent value uses each run's explicit final factor-set/allocator recommendation only; no recommendation is NOT_SUPPORTED. Candidate gate separately ranks all completed primary pool/allocator pairs.",
                },
                "discovery": {
                    "classification": "exploratory",
                    "incremental_value_separately_identified": False,
                    "reason": "No admitted matched non-Agent FactorGraph discovery search; no weak replacement baseline.",
                    "tools": list(DISCOVERY_TOOLS),
                    "budgets": {**budgets, "factor_proposals": 3, "factor_evaluations": 3},
                    "candidate_eligible": False,
                },
                "independent_agent_run_count": 3,
                "runs": [
                    "selection-01",
                    "selection-02",
                    "selection-03",
                    "discovery-01",
                    "discovery-02",
                    "discovery-03",
                ],
                "run_isolation": "fresh ledger, library copy, context; identical objective/pool/budgets/provider; independent responses; no cross-run feedback",
                "randomness": {
                    "provider_seed": None,
                    "provider_responses": "independent stochastic calls; no cherry-picked restart",
                    "gmm_seed": "bound_by_research_admission.market_model.config.random_seed",
                },
                "feedback_scope": {
                    "factor": folds[0]["evaluation"],
                    "portfolio": folds,
                    "interpretation": "adaptive_search_exposed; fold evaluation; not independent evidence",
                },
                "failure_policy": {
                    "provider_quota_failure": "campaign_system_failure; retain full uncertain reservation",
                    "provider_timeout": "campaign_system_failure; retain full uncertain reservation",
                    "transport_uncertainty": "campaign_system_failure; no automatic retry",
                    "evaluator_infrastructure_failure": "campaign_system_failure; evaluation slot retained",
                    "invalid_json_or_tool": "consumed_tool_attempt; untyped rejection also debits every proposal category conservatively; no replacement; unknown tool cannot execute",
                    "invalid_proposal": "consumed_proposal_slot_if_typed; consumed_tool_attempt_always",
                    "duplicate_proposal": "consumed_proposal_slot; no replacement",
                    "duplicate_experiment": "consumed_tool_attempt; no second evaluation slot/result",
                    "budget_exhaustion": "normal_stop; unspent slots not replaced; report denominator",
                    "audit_inconsistency": "campaign_system_failure; refuse resume",
                    "negative_result": "valid_research_result; never_retry_or_replace",
                    "maximum_infrastructure_retries": 0,
                    "maximum_repairs": 0,
                    "resume": "committed request replay only; pending uncertainty is system failure",
                },
                "stopping_rule": "Explicit finalize or hard tool/token/cost/wall-clock ceiling stops a run. Proposal/evaluation ceilings deny further actions of that kind but permit remaining bounded inspection/finalization. All three primary runs required. Any infrastructure failure stops campaign; no result-dependent extension.",
                "metrics": [
                    "mean_fold_return_5bp",
                    "worst_fold_return_5bp",
                    "drawdown_5bp",
                    "turnover_5bp",
                    "factor_concentration",
                    "cost_sensitivity",
                    "unavailable_sessions",
                ],
                "agent_value_rule": {
                    "minimum_mean_fold_improvement": 0.002,
                    "minimum_run_wins": 2,
                    "median_worst_fold_noninferiority": True,
                    "required_runs": 3,
                    "interpretation": "development descriptive repeatability; no significance or Alpha gate",
                },
                "candidate_rule": {
                    "required_folds": len(folds),
                    "maximum_unresolved_sessions": 0,
                    "primary_cost_bps": 5,
                    "mean_fold_return_5bp_strictly_greater_than": 0.0,
                    "worst_fold_return_5bp_at_least": -0.01,
                    "mean_fold_return_10bp_at_least": 0.0,
                    "eligible_sources": ["deterministic_selection", "agent_selection"],
                    "ranking": [
                        "higher_mean_5bp",
                        "higher_worst_5bp",
                        "lower_drawdown",
                        "lower_turnover",
                        "lower_concentration",
                        "fewer_factors",
                        "less_runtime_agent_dependence",
                        "canonical_candidate_id",
                    ],
                },
                "terminal_rule": "system failure => SYSTEM_FAILURE; else highest ranked viable primary candidate => ADAPTIVE_CANDIDATE; else NO_ADAPTIVE_CANDIDATE; Agent value assessed independently",
                **AUTHORITY,
            }
        )
    )


class AgentValueAssessment(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class R4CandidateDecision(StrEnum):
    ADAPTIVE_CANDIDATE = "ADAPTIVE_CANDIDATE"
    NO_ADAPTIVE_CANDIDATE = "NO_ADAPTIVE_CANDIDATE"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


def complete(candidate: dict[str, Any], protocol: R4MatchedComparisonProtocol) -> bool:
    m = candidate["metrics"]
    return (
        m["evaluable_folds"] == protocol.to_dict()["candidate_rule"]["required_folds"]
        and m["unavailable_sessions"] == 0
        and all(
            type(m.get(k)) in (int, float) and math.isfinite(m[k])
            for k in (
                "mean_fold_return_5bp",
                "worst_fold_return_5bp",
                "drawdown_5bp",
                "turnover_5bp",
                "factor_concentration",
            )
        )
        and all(
            type(m["cost_sensitivity"][c]["mean_fold_return"]) in (int, float)
            and math.isfinite(m["cost_sensitivity"][c]["mean_fold_return"])
            for c in ("0.0", "1.0", "5.0", "10.0")
        )
    )


def ranking(candidate: dict[str, Any]) -> tuple[Any, ...]:
    m = candidate["metrics"]
    return (
        -m["mean_fold_return_5bp"],
        -m["worst_fold_return_5bp"],
        m["drawdown_5bp"],
        m["turnover_5bp"],
        m["factor_concentration"],
        len(candidate["factor_ids"]),
        candidate["runtime_agent_dependence"],
        candidate["candidate_id"],
    )


def assess_campaign(
    protocol: R4MatchedComparisonProtocol,
    candidates: list[dict[str, Any]],
    *,
    completed_runs: list[str],
    system_failure: bool,
) -> dict[str, Any]:
    """Called by the host after verified run artifacts; never exposed as an Agent tool."""
    p = protocol.to_dict()
    required = {"deterministic", "selection-01", "selection-02", "selection-03"}
    failure = system_failure or not required.issubset(completed_runs)
    eligible = [
        c
        for c in candidates
        if c["arm"] in p["candidate_rule"]["eligible_sources"] and complete(c, protocol)
    ]
    best = {
        r: min(
            (
                c
                for c in eligible
                if c["run_id"] == r and (r == "deterministic" or c.get("agent_selected", False))
            ),
            key=ranking,
            default=None,
        )
        for r in required
    }
    value = AgentValueAssessment.INCONCLUSIVE
    baseline = best["deterministic"]
    agents = [best[r] for r in sorted(required - {"deterministic"})]
    # Deliberate no-candidate is negative; incomplete numbers stay inconclusive.
    if (
        not failure
        and baseline is not None
        and any(a is None for a in agents)
        and not any(c.get("agent_selected") and not complete(c, protocol) for c in candidates)
    ):
        value = AgentValueAssessment.NOT_SUPPORTED
    if not failure and baseline is not None and all(a is not None for a in agents):
        reference = baseline["metrics"]
        rows = [a["metrics"] for a in agents if a is not None]
        margin = p["agent_value_rule"]["minimum_mean_fold_improvement"]
        wins = sum(
            r["mean_fold_return_5bp"] >= reference["mean_fold_return_5bp"] + margin
            and r["worst_fold_return_5bp"] >= reference["worst_fold_return_5bp"]
            for r in rows
        )
        supported = (
            wins >= p["agent_value_rule"]["minimum_run_wins"]
            and median(r["mean_fold_return_5bp"] for r in rows)
            >= reference["mean_fold_return_5bp"] + margin
            and median(r["worst_fold_return_5bp"] for r in rows)
            >= reference["worst_fold_return_5bp"]
        )
        value = AgentValueAssessment.SUPPORTED if supported else AgentValueAssessment.NOT_SUPPORTED
    rule = p["candidate_rule"]
    viable = [
        c
        for c in eligible
        if (
            c["metrics"]["mean_fold_return_5bp"]
            > rule["mean_fold_return_5bp_strictly_greater_than"]
            and c["metrics"]["worst_fold_return_5bp"] >= rule["worst_fold_return_5bp_at_least"]
            and c["metrics"]["cost_sensitivity"]["10.0"]["mean_fold_return"]
            >= rule["mean_fold_return_10bp_at_least"]
        )
    ]
    winner = min(viable, key=ranking) if viable and not failure else None
    return {
        "protocol_id": protocol.protocol_id,
        "agent_value": value.value,
        "candidate_decision": (
            R4CandidateDecision.SYSTEM_FAILURE
            if failure
            else R4CandidateDecision.ADAPTIVE_CANDIDATE
            if winner
            else R4CandidateDecision.NO_ADAPTIVE_CANDIDATE
        ).value,
        "candidate_id": winner["candidate_id"] if winner else None,
        "decision_authority": "deterministic_host",
        **AUTHORITY,
    }


@dataclass(frozen=True)
class AdaptiveStrategySpec:
    payload_json: str

    @property
    def strategy_id(self) -> str:
        return identity(json.loads(self.payload_json), "adaptive-strategy-development")

    @classmethod
    def build(
        cls,
        *,
        research_manifest: dict[str, Any],
        protocol_id: str,
        campaign_result_id: str,
        candidate: dict[str, Any],
        assessment: dict[str, Any],
        factor_definitions: list[dict[str, Any]],
    ) -> AdaptiveStrategySpec:
        if (
            assessment["decision_authority"] != "deterministic_host"
            or assessment["candidate_decision"] != "ADAPTIVE_CANDIDATE"
            or assessment["candidate_id"] != candidate["candidate_id"]
            or assessment["protocol_id"] != protocol_id
            or set(candidate["factor_ids"]) != {f["factor_id"] for f in factor_definitions}
            or candidate["allocator"] not in ALLOCATORS
            or not campaign_result_id
        ):
            raise ValueError("host candidate binding required")
        return cls(
            canonical_json(
                {
                    "schema_version": "finagent.adaptive-strategy-development.v1",
                    "research_manifest": research_manifest,
                    "factor_definitions": factor_definitions,
                    "factor_set": candidate["factor_ids"],
                    "allocator": candidate["allocator"],
                    "allocator_config": {"quality": research_manifest["quality"], "ridge_alpha": 1},
                    "normalization_support": research_manifest["normalization_support"],
                    "performance_history": "previous_completed_sessions; outcome_available_at <= decision_time",
                    "market_state_refit": "fold_local_train_prefix_scaler_GMM; train_only_Ridge",
                    "execution": research_manifest["execution_semantics"],
                    "missing_fallback": research_manifest["missing_fallback"],
                    "agent_role": "research_development_only; no_intraday_LLM",
                    "campaign_protocol_id": protocol_id,
                    "campaign_result_id": campaign_result_id,
                    "development_evidence_ids": [candidate["experiment_id"]],
                    **AUTHORITY,
                }
            )
        )
