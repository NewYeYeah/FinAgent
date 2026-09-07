"""Preregistered R4 resources and host decisions, separate from campaign results."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
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
PRIMARY_MIN_FACTOR_SET_SIZE = 2
PRIMARY_MAX_FACTOR_SET_SIZE = 20
PRIMARY_AGENT_RUNS = ("selection-01", "selection-02", "selection-03")
AGENT_VALUE_BASIS = "research_efficiency_under_exhaustive_oracle"
CURRENT_R4_MATCHED_PROTOCOL_VERSION = "r4-matched-v3"
CURRENT_R4_BLOCKED_PROTOCOL_VERSION = (
    f"{CURRENT_R4_MATCHED_PROTOCOL_VERSION}-blocked-provider"
)
SUPERSEDED_R4_MATCHED_PROTOCOL_VERSIONS = frozenset(
    {
        "r4-matched-v1",
        "r4-matched-v2",
        "r4-matched-v1-blocked-provider",
        "r4-matched-v2-blocked-provider",
    }
)


def validate_new_r4_protocol_version(version: str) -> str:
    """Keep newly generated corrected artifacts inside the current v3 version family."""
    if not version or version != version.strip():
        raise ValueError("invalid R4 matched protocol version")
    if version in SUPERSEDED_R4_MATCHED_PROTOCOL_VERSIONS:
        raise ValueError(
            "superseded historical R4 matched protocol version cannot label a new artifact"
        )
    if version != CURRENT_R4_MATCHED_PROTOCOL_VERSION and not version.startswith(
        f"{CURRENT_R4_MATCHED_PROTOCOL_VERSION}-"
    ):
        raise ValueError("new R4 matched protocol artifacts must use the current v3 version family")
    return version


@dataclass(frozen=True)
class R4MatchedComparisonProtocol:
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return dict(json.loads(self.payload_json))

    @property
    def protocol_id(self) -> str:
        return identity(self.to_dict(), "r4-matched-protocol")


def primary_admissible_factor_sets(initial_factor_ids: list[str]) -> list[list[str]]:
    """Enumerate the FactorSet contract over the frozen Primary initial pool."""
    ids = sorted(initial_factor_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("primary factor IDs must be distinct")
    upper = min(PRIMARY_MAX_FACTOR_SET_SIZE, len(ids))
    if upper < PRIMARY_MIN_FACTOR_SET_SIZE:
        return []
    return [
        list(group)
        for size in range(PRIMARY_MIN_FACTOR_SET_SIZE, upper + 1)
        for group in combinations(ids, size)
    ]


def strategy_key(candidate: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    """Run-independent Primary strategy identity used for oracle comparison."""
    return tuple(sorted(candidate["factor_ids"])), str(candidate["allocator"])


def primary_search_space(
    initial_factor_ids: list[str], deterministic_factor_sets: list[list[str]]
) -> dict[str, Any]:
    """Prove whether deterministic evaluation covers every Agent-admissible strategy."""
    ids = sorted(initial_factor_ids)
    admissible = primary_admissible_factor_sets(ids)
    deterministic = [sorted(group) for group in deterministic_factor_sets]
    agent_factor_sets = {tuple(group) for group in admissible}
    deterministic_sets = {tuple(group) for group in deterministic}
    agent_strategies = {(group, allocator) for group in agent_factor_sets for allocator in ALLOCATORS}
    deterministic_strategies = {
        (group, allocator) for group in deterministic_sets for allocator in ALLOCATORS
    }
    exhaustive = agent_factor_sets == deterministic_sets and agent_strategies == deterministic_strategies
    return {
        "initial_factor_count": len(ids),
        "minimum_factor_set_size": PRIMARY_MIN_FACTOR_SET_SIZE,
        "maximum_factor_set_size": PRIMARY_MAX_FACTOR_SET_SIZE,
        "agent_admissible_factor_sets": admissible,
        "admissible_factor_set_count": len(agent_factor_sets),
        "deterministic_factor_set_count": len(deterministic_sets),
        "allocator_count": len(ALLOCATORS),
        "reachable_candidate_count": len(agent_strategies),
        "deterministic_candidate_count": len(deterministic_strategies),
        "deterministic_search": "exhaustive" if exhaustive else "bounded_non_exhaustive",
    }


def matched_protocol(
    *,
    version: str,
    frozen_at: str,
    provider_admission_id: str,
    research_admission_id: str,
    initial_factor_ids: list[str],
    folds: list[dict[str, Any]],
) -> R4MatchedComparisonProtocol:
    version = validate_new_r4_protocol_version(version)
    ids = sorted(initial_factor_ids)
    if len(ids) != 3 or len(set(ids)) != 3:
        raise ValueError("current Primary protocol requires exactly three distinct initial factors")
    schedule = [ids, *[[f for f in ids if f != omitted] for omitted in ids]]
    search_space = primary_search_space(ids, schedule)
    if search_space["deterministic_search"] != "exhaustive":
        raise ValueError("exhaustive-oracle Agent value requires complete deterministic coverage")
    if (
        search_space["admissible_factor_set_count"] != 4
        or search_space["allocator_count"] != 5
        or search_space["reachable_candidate_count"] != 20
    ):
        raise ValueError("current Primary protocol must bind four factor sets and twenty strategies")
    deterministic_evaluations = search_space["deterministic_factor_set_count"]
    budgets = {
        "factor_proposals": 0,
        "factor_evaluations": 0,
        "factor_set_proposals": deterministic_evaluations,
        "portfolio_evaluations": deterministic_evaluations,
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
                "objective": "Within the admitted exposed development folds, assess whether bounded Agent selection can identify an exhaustive-oracle-noninferior factor-set/allocator with fewer portfolio evaluations; retain negative and failed trials; recommend only development evidence.",
                "provider_admission_id": provider_admission_id,
                "research_admission_id": research_admission_id,
                "initial_factor_ids": ids,
                "mandatory_allocators": list(ALLOCATORS),
                "primary_search_space": search_space,
                "primary": {
                    "arms": ["deterministic_selection", "agent_selection"],
                    "comparators": [
                        "equal_weight_full_pool",
                        "best_frozen_deterministic",
                        "regime_conditional_full_pool",
                    ],
                    "deterministic_factor_sets": schedule,
                    "deterministic_search": "exhaustive",
                    "deterministic_oracle": "exhaustive deterministic oracle for the frozen primary search space",
                    "tools": list(PRIMARY_TOOLS),
                    "budgets": budgets,
                    "matched_resources": ["factor_set_proposals", "portfolio_evaluations"],
                    "deterministic_llm_calls_tokens_cost": 0,
                    "selection": "Agent value uses each run's explicit final factor-set/allocator recommendation, matched to the deterministic strategy key, and authoritative ResearchLedger-derived portfolio-evaluation usage. Candidate viability separately ranks all completed primary pairs.",
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
                    *PRIMARY_AGENT_RUNS,
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
                    "basis": AGENT_VALUE_BASIS,
                    "required_runs": 3,
                    "minimum_successful_runs": 2,
                    "deterministic_oracle_portfolio_evaluations": deterministic_evaluations,
                    "minimum_evaluation_saving_per_successful_run": 1,
                    "median_evaluation_saving_at_least": 1,
                    "oracle_noninferiority": "same frozen Primary economic ordering; run/candidate identity cannot improve economic rank",
                    "resource_authority": "deterministic host from ResearchLedger/campaign accounting",
                    "interpretation": "development descriptive research efficiency under exhaustive oracle; performance superiority is not identifiable in this frozen finite space and this is not a significance or Alpha gate",
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
    try:
        m = candidate["metrics"]
        costs = m["cost_sensitivity"]
        required_folds = protocol.to_dict()["candidate_rule"]["required_folds"]
        return (
            m["evaluable_folds"] == required_folds
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
                type(costs[c]["mean_fold_return"]) in (int, float)
                and math.isfinite(costs[c]["mean_fold_return"])
                for c in ("0.0", "1.0", "5.0", "10.0")
            )
        )
    except (KeyError, TypeError):
        return False


def economic_ranking(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Frozen economic ordering without run-specific Agent metadata or candidate ID."""
    m = candidate["metrics"]
    return (
        -m["mean_fold_return_5bp"],
        -m["worst_fold_return_5bp"],
        m["drawdown_5bp"],
        m["turnover_5bp"],
        m["factor_concentration"],
        len(candidate["factor_ids"]),
    )


def ranking(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        *economic_ranking(candidate),
        candidate["runtime_agent_dependence"],
        candidate["candidate_id"],
    )


def _portfolio_evaluations(resources: dict[str, Any] | None, run_id: str) -> int | None:
    if resources is None or not isinstance(resources.get(run_id), dict):
        return None
    row = resources[run_id]
    if run_id == "deterministic":
        value = row.get("portfolio_evaluations")
    else:
        research = row.get("research_resources")
        value = research.get("portfolio_evaluations") if isinstance(research, dict) else None
    return value if type(value) is int and value >= 0 else None


def _strategy_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    metrics = candidate["metrics"]
    return {
        "factor_ids": sorted(candidate["factor_ids"]),
        "allocator": candidate["allocator"],
        "economic_metrics": {
            key: metrics[key]
            for key in (
                "mean_fold_return_5bp",
                "worst_fold_return_5bp",
                "drawdown_5bp",
                "turnover_5bp",
                "factor_concentration",
            )
        },
    }


def assess_campaign(
    protocol: R4MatchedComparisonProtocol,
    candidates: list[dict[str, Any]],
    *,
    completed_runs: list[str],
    system_failure: bool,
    resources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Called by the host after verified run artifacts; never exposed as an Agent tool."""
    p = protocol.to_dict()
    required = {"deterministic", *PRIMARY_AGENT_RUNS}
    failure = system_failure or not required.issubset(completed_runs)
    eligible = [
        c
        for c in candidates
        if c.get("arm") in p["candidate_rule"]["eligible_sources"] and complete(c, protocol)
    ]

    expected_keys = {
        (tuple(group), allocator)
        for group in p["primary_search_space"]["agent_admissible_factor_sets"]
        for allocator in p["mandatory_allocators"]
    }
    deterministic_rows = [
        c
        for c in candidates
        if c.get("run_id") == "deterministic" and c.get("arm") == "deterministic_selection"
    ]
    deterministic_by_key: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
    deterministic_evidence_complete = len(deterministic_rows) == len(expected_keys)
    for candidate in deterministic_rows:
        if not complete(candidate, protocol):
            deterministic_evidence_complete = False
            continue
        key = strategy_key(candidate)
        if key in deterministic_by_key:
            deterministic_evidence_complete = False
        deterministic_by_key[key] = candidate
    deterministic_evidence_complete = (
        deterministic_evidence_complete and set(deterministic_by_key) == expected_keys
    )
    oracle = (
        min(
            deterministic_by_key.values(),
            key=lambda candidate: (economic_ranking(candidate), strategy_key(candidate)),
        )
        if deterministic_evidence_complete
        else None
    )

    rule = p["agent_value_rule"]
    expected_deterministic_evaluations = rule["deterministic_oracle_portfolio_evaluations"]
    deterministic_evaluations = _portfolio_evaluations(resources, "deterministic")
    accounting_complete = deterministic_evaluations == expected_deterministic_evaluations
    run_assessments: list[dict[str, Any]] = []
    agent_evidence_complete = True
    for run_id in PRIMARY_AGENT_RUNS:
        used = _portfolio_evaluations(resources, run_id)
        saving = (
            deterministic_evaluations - used
            if deterministic_evaluations is not None and used is not None
            else None
        )
        selected_rows = [
            c
            for c in candidates
            if c.get("run_id") == run_id
            and c.get("arm") == "agent_selection"
            and c.get("agent_selected", False)
        ]
        selected: dict[str, Any] | None = None
        oracle_noninferior: bool | None = None
        status = "COMPLETE_NO_CANDIDATE"
        if run_id not in completed_runs:
            status = "RUN_NOT_COMPLETED"
            agent_evidence_complete = False
        elif used is None or used > p["primary"]["budgets"]["portfolio_evaluations"]:
            status = "INCOMPLETE_RESOURCE_ACCOUNTING"
            agent_evidence_complete = False
        elif len(selected_rows) > 1:
            status = "INCOMPLETE_SELECTION"
            agent_evidence_complete = False
        elif len(selected_rows) == 1:
            selected = selected_rows[0]
            if not complete(selected, protocol):
                status = "INCOMPLETE_SELECTED_METRICS"
                agent_evidence_complete = False
            elif oracle is None:
                status = "INCOMPLETE_ORACLE"
                agent_evidence_complete = False
            else:
                counterpart = deterministic_by_key.get(strategy_key(selected))
                if counterpart is None:
                    status = "INCOMPLETE_ORACLE_COVERAGE"
                    agent_evidence_complete = False
                elif economic_ranking(selected) != economic_ranking(counterpart):
                    status = "INCOMPLETE_STRATEGY_METRIC_CONSISTENCY"
                    agent_evidence_complete = False
                else:
                    status = "COMPLETE_SELECTED"
                    oracle_noninferior = economic_ranking(counterpart) <= economic_ranking(oracle)
        if status == "COMPLETE_NO_CANDIDATE":
            oracle_noninferior = False
        efficiency_success = bool(
            oracle_noninferior is True
            and saving is not None
            and saving >= rule["minimum_evaluation_saving_per_successful_run"]
        )
        run_assessments.append(
            {
                "run_id": run_id,
                "completion_status": status,
                "selected_strategy": _strategy_summary(selected) if selected is not None and complete(selected, protocol) else None,
                "portfolio_evaluations_used": used,
                "evaluation_saving": saving,
                "oracle_noninferior": oracle_noninferior,
                "efficiency_success": efficiency_success,
            }
        )

    savings = [row["evaluation_saving"] for row in run_assessments]
    median_saving = median(savings) if all(type(value) is int for value in savings) else None
    value = AgentValueAssessment.INCONCLUSIVE
    complete_value_evidence = (
        not system_failure
        and required.issubset(completed_runs)
        and deterministic_evidence_complete
        and accounting_complete
        and agent_evidence_complete
    )
    if complete_value_evidence:
        successes = sum(row["efficiency_success"] for row in run_assessments)
        supported = (
            successes >= rule["minimum_successful_runs"]
            and median_saving is not None
            and median_saving >= rule["median_evaluation_saving_at_least"]
        )
        value = AgentValueAssessment.SUPPORTED if supported else AgentValueAssessment.NOT_SUPPORTED

    candidate_rule = p["candidate_rule"]
    viable = [
        c
        for c in eligible
        if (
            c["metrics"]["mean_fold_return_5bp"]
            > candidate_rule["mean_fold_return_5bp_strictly_greater_than"]
            and c["metrics"]["worst_fold_return_5bp"]
            >= candidate_rule["worst_fold_return_5bp_at_least"]
            and c["metrics"]["cost_sensitivity"]["10.0"]["mean_fold_return"]
            >= candidate_rule["mean_fold_return_10bp_at_least"]
        )
    ]
    winner = min(viable, key=ranking) if viable and not failure else None
    return {
        "protocol_id": protocol.protocol_id,
        "agent_value": value.value,
        "agent_value_basis": rule["basis"],
        "deterministic_oracle": _strategy_summary(oracle) if oracle is not None else None,
        "deterministic_portfolio_evaluations": deterministic_evaluations,
        "expected_deterministic_portfolio_evaluations": expected_deterministic_evaluations,
        "agent_run_assessments": run_assessments,
        "median_portfolio_evaluation_saving": median_saving,
        "successful_agent_runs": sum(row["efficiency_success"] for row in run_assessments),
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
