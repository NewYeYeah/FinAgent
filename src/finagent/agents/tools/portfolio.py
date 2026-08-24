from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..domain import AgentAction, AgentRunContext, ToolMode
from ..supervisor import OperatingPolicyRegistry, SQLitePortfolioSupervisionStore
from .base import FunctionTool, ToolSpec


@dataclass(frozen=True, slots=True)
class PortfolioSupervisorToolDependencies:
    supervision_store: SQLitePortfolioSupervisionStore
    operating_policies: OperatingPolicyRegistry


def _snapshot_id(arguments: Mapping[str, object]) -> str:
    value = arguments.get("snapshot_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("snapshot_id must be a non-empty string")
    return value.strip()


def build_portfolio_supervisor_tools(deps: PortfolioSupervisorToolDependencies):
    def inspect_health(arguments: Mapping[str, object], context: AgentRunContext):
        snapshot = deps.supervision_store.get(_snapshot_id(arguments))
        return {
            "snapshot_id": snapshot.snapshot_id,
            "asof": snapshot.asof.isoformat(),
            "observed_at": snapshot.observed_at.isoformat(),
            "data_asof": snapshot.data_asof.isoformat(),
            "overall_level": snapshot.overall_level.value,
            "selected_constructor": snapshot.selected_constructor,
            "selected_expected_net_return": snapshot.selected_benchmark.expected_net_return,
            "selected_volatility": snapshot.selected_benchmark.volatility,
            "checks": [
                {
                    "name": check.name,
                    "level": check.level.value,
                    "message": check.message,
                    "observed": check.observed,
                    "limit": check.limit,
                }
                for check in snapshot.checks
            ],
            "top_weight_drifts": [
                {
                    "asset_key": item.asset_key,
                    "current_weight": item.current_weight,
                    "target_weight": item.target_weight,
                    "delta": item.delta,
                }
                for item in snapshot.weight_drifts[:5]
            ],
            "metadata": dict(snapshot.metadata),
        }

    def inspect_benchmarks(arguments: Mapping[str, object], context: AgentRunContext):
        snapshot = deps.supervision_store.get(_snapshot_id(arguments))
        return {
            "snapshot_id": snapshot.snapshot_id,
            "selected_constructor": snapshot.selected_constructor,
            "benchmarks": [
                {
                    "name": item.name,
                    "expected_return": item.expected_return,
                    "expected_net_return": item.expected_net_return,
                    "volatility": item.volatility,
                    "turnover": item.turnover,
                    "gross_exposure": item.gross_exposure,
                    "net_exposure": item.net_exposure,
                }
                for item in snapshot.benchmarks
            ],
        }

    def inspect_stress(arguments: Mapping[str, object], context: AgentRunContext):
        snapshot = deps.supervision_store.get(_snapshot_id(arguments))
        worst = snapshot.worst_stress
        return {
            "snapshot_id": snapshot.snapshot_id,
            "worst": None
            if worst is None
            else {"name": worst.name, "portfolio_return": worst.portfolio_return},
            "scenarios": [
                {"name": item.name, "portfolio_return": item.portfolio_return}
                for item in snapshot.stresses
            ],
        }

    def inspect_rebalance(arguments: Mapping[str, object], context: AgentRunContext):
        snapshot = deps.supervision_store.get(_snapshot_id(arguments))
        return {
            "snapshot_id": snapshot.snapshot_id,
            "rebalance_required": snapshot.rebalance_required,
            "turnover": snapshot.rebalance_turnover,
            "max_weight_drift": snapshot.rebalance_max_weight_drift,
            "reasons": list(snapshot.rebalance_reasons),
        }

    def list_policies(arguments: Mapping[str, object], context: AgentRunContext):
        return {
            "policies": [
                {
                    "policy_id": policy.policy_id,
                    "mode": policy.mode.value,
                    "description": policy.description,
                    "constraint_policy_id": policy.constraint_policy_id,
                    "rebalance_policy_id": policy.rebalance_policy_id,
                }
                for policy in deps.operating_policies.list()
            ]
        }

    def request_policy(arguments: Mapping[str, object], context: AgentRunContext):
        snapshot = deps.supervision_store.get(_snapshot_id(arguments))
        policy_id = arguments.get("policy_id")
        reason = arguments.get("reason")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        policy = deps.operating_policies.get(policy_id.strip())
        return {
            "request_type": "operating_policy",
            "snapshot_id": snapshot.snapshot_id,
            "policy_id": policy.policy_id,
            "mode": policy.mode.value,
            "reason": reason.strip(),
            "requested_by": context.actor,
            "mutation_performed": False,
            "requires_human_approval": True,
        }

    def request_rebalance(arguments: Mapping[str, object], context: AgentRunContext):
        snapshot = deps.supervision_store.get(_snapshot_id(arguments))
        reason = arguments.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not snapshot.rebalance_required:
            raise ValueError("deterministic rebalance policy does not currently request a rebalance")
        return {
            "request_type": "rebalance",
            "snapshot_id": snapshot.snapshot_id,
            "reason": reason.strip(),
            "deterministic_reasons": list(snapshot.rebalance_reasons),
            "turnover": snapshot.rebalance_turnover,
            "requested_by": context.actor,
            "mutation_performed": False,
            "requires_human_approval": True,
        }

    def request_review(arguments: Mapping[str, object], context: AgentRunContext):
        snapshot = deps.supervision_store.get(_snapshot_id(arguments))
        reason = arguments.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        return {
            "request_type": "human_review",
            "snapshot_id": snapshot.snapshot_id,
            "reason": reason.strip(),
            "requested_by": context.actor,
            "mutation_performed": False,
        }

    return (
        FunctionTool(
            ToolSpec(
                AgentAction.INSPECT_PORTFOLIO_HEALTH.value,
                "inspect deterministic portfolio/data/model health diagnostics",
                AgentAction.INSPECT_PORTFOLIO_HEALTH,
                ToolMode.READ,
                frozenset({"snapshot_id"}),
            ),
            inspect_health,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.INSPECT_PORTFOLIO_BENCHMARKS.value,
                "inspect common portfolio-constructor benchmark metrics",
                AgentAction.INSPECT_PORTFOLIO_BENCHMARKS,
                ToolMode.READ,
                frozenset({"snapshot_id"}),
            ),
            inspect_benchmarks,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.INSPECT_STRESS_REPORT.value,
                "inspect deterministic portfolio stress scenarios",
                AgentAction.INSPECT_STRESS_REPORT,
                ToolMode.READ,
                frozenset({"snapshot_id"}),
            ),
            inspect_stress,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.INSPECT_REBALANCE_DECISION.value,
                "inspect deterministic rebalance policy output",
                AgentAction.INSPECT_REBALANCE_DECISION,
                ToolMode.READ,
                frozenset({"snapshot_id"}),
            ),
            inspect_rebalance,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.LIST_OPERATING_POLICIES.value,
                "list pre-registered operating policies available for supervisor requests",
                AgentAction.LIST_OPERATING_POLICIES,
                ToolMode.READ,
            ),
            list_policies,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.REQUEST_OPERATING_POLICY.value,
                "request human approval for a pre-registered operating policy; never mutates portfolio state",
                AgentAction.REQUEST_OPERATING_POLICY,
                ToolMode.REQUEST,
                frozenset({"snapshot_id", "policy_id", "reason"}),
            ),
            request_policy,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.REQUEST_REBALANCE.value,
                "request human approval for a rebalance already justified by deterministic policy",
                AgentAction.REQUEST_REBALANCE,
                ToolMode.REQUEST,
                frozenset({"snapshot_id", "reason"}),
            ),
            request_rebalance,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.REQUEST_HUMAN_REVIEW.value,
                "create a non-mutating human-review request",
                AgentAction.REQUEST_HUMAN_REVIEW,
                ToolMode.REQUEST,
                frozenset({"snapshot_id", "reason"}),
            ),
            request_review,
        ),
    )
