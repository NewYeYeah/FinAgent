from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from finagent.memory import FailureCategory, ResearchMemoryService

from ..domain import AgentAction, AgentRunContext, ToolMode
from .base import FunctionTool, ToolSpec


@dataclass(frozen=True, slots=True)
class ResearchMemoryToolDependencies:
    memory: ResearchMemoryService


def _int_arg(arguments: Mapping[str, object], name: str, default: int, *, low: int, high: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _str_arg(arguments: Mapping[str, object], name: str, *, required: bool = True) -> str:
    value = arguments.get(name, "")
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _tags(arguments: Mapping[str, object]) -> tuple[str, ...]:
    raw = arguments.get("tags", ())
    if not isinstance(raw, (list, tuple)) or any(not isinstance(value, str) for value in raw):
        raise ValueError("tags must be an array of strings")
    return tuple(value.strip() for value in raw if value.strip())


def _node_payload(node) -> dict[str, object]:
    return {
        "key": node.key,
        "type": node.node_type.value,
        "id": node.node_id,
        "label": node.label,
        "created_at": node.created_at.isoformat(),
        "metadata": dict(node.metadata),
    }


def _failure_payload(item) -> dict[str, object]:
    return {
        "failure_id": item.failure_id,
        "category": item.category.value,
        "stage": item.stage.value,
        "summary": item.summary,
        "observed_at": item.observed_at.isoformat(),
        "hypothesis_id": item.hypothesis_id,
        "experiment_id": item.experiment_id,
        "related_node_keys": list(item.related_node_keys),
        "metadata": dict(item.metadata),
    }


def build_research_memory_tools(deps: ResearchMemoryToolDependencies):
    def list_hypotheses(arguments: Mapping[str, object], context: AgentRunContext):
        limit = _int_arg(arguments, "limit", 20, low=1, high=100)
        items = deps.memory.list_hypotheses(limit=limit)
        return {
            "hypotheses": [
                {
                    "hypothesis_id": item.hypothesis_id,
                    "revision": item.revision,
                    "statement": item.statement,
                    "tags": list(item.tags),
                    "disposition": item.disposition.value,
                    "created_at": item.created_at.isoformat(),
                }
                for item in items
            ]
        }

    def inspect_hypothesis(arguments: Mapping[str, object], context: AgentRunContext):
        hypothesis_id = _str_arg(arguments, "hypothesis_id")
        max_nodes = _int_arg(arguments, "max_nodes", 40, low=1, high=100)
        max_failures = _int_arg(arguments, "max_failures", 20, low=0, high=100)
        summary = deps.memory.summary(
            hypothesis_id,
            max_nodes=max_nodes,
            max_failures=max_failures,
        )
        latest = summary.hypothesis
        return {
            "hypothesis": {
                "hypothesis_id": latest.hypothesis_id,
                "revision": latest.revision,
                "statement": latest.statement,
                "rationale": latest.rationale,
                "tags": list(latest.tags),
                "disposition": latest.disposition.value,
                "created_at": latest.created_at.isoformat(),
            },
            "revision_count": summary.revision_count,
            "node_counts": dict(summary.node_counts),
            "failures": [_failure_payload(item) for item in summary.failures],
            "truncated": summary.truncated,
        }

    def find_similar(arguments: Mapping[str, object], context: AgentRunContext):
        statement = _str_arg(arguments, "statement")
        limit = _int_arg(arguments, "limit", 5, low=1, high=20)
        exclude = _str_arg(arguments, "exclude_hypothesis_id", required=False)
        matches = deps.memory.find_similar_hypotheses(
            statement,
            tags=_tags(arguments),
            exclude_hypothesis_id=exclude,
            limit=limit,
        )
        return {
            "matches": [
                {"hypothesis_id": item.entity_id, "score": item.score, "reason": item.reason}
                for item in matches
            ]
        }

    def inspect_lineage(arguments: Mapping[str, object], context: AgentRunContext):
        node_key = _str_arg(arguments, "node_key")
        max_depth = _int_arg(arguments, "max_depth", 6, low=0, high=12)
        max_nodes = _int_arg(arguments, "max_nodes", 50, low=1, high=100)
        graph = deps.memory.store.traverse(
            node_key,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        return {
            "nodes": [_node_payload(node) for node in graph.nodes],
            "edges": [
                {
                    "edge_id": edge.edge_id,
                    "source_key": edge.source_key,
                    "target_key": edge.target_key,
                    "relation": edge.relation.value,
                    "created_at": edge.created_at.isoformat(),
                    "metadata": dict(edge.metadata),
                }
                for edge in graph.edges
            ],
            "truncated": graph.truncated,
        }

    def inspect_failures(arguments: Mapping[str, object], context: AgentRunContext):
        hypothesis_id = _str_arg(arguments, "hypothesis_id", required=False)
        experiment_id = _str_arg(arguments, "experiment_id", required=False)
        raw_category = _str_arg(arguments, "category", required=False)
        category = FailureCategory(raw_category) if raw_category else None
        limit = _int_arg(arguments, "limit", 20, low=1, high=100)
        items = deps.memory.store.failures(
            hypothesis_id=hypothesis_id or None,
            experiment_id=experiment_id or None,
            category=category,
        )[:limit]
        return {"failures": [_failure_payload(item) for item in items]}

    def recommend_budget(arguments: Mapping[str, object], context: AgentRunContext):
        recommendation = deps.memory.recommend_budget(
            statement=_str_arg(arguments, "statement"),
            requested_max_experiments=_int_arg(
                arguments, "requested_max_experiments", 1, low=1, high=100
            ),
            tags=_tags(arguments),
            hypothesis_id=_str_arg(arguments, "hypothesis_id", required=False),
        )
        return {
            "requested_max_experiments": recommendation.requested_max_experiments,
            "recommended_max_experiments": recommendation.recommended_max_experiments,
            "duplicate_score": recommendation.duplicate_score,
            "similar_hypothesis_ids": list(recommendation.similar_hypothesis_ids),
            "prior_failure_count": recommendation.prior_failure_count,
            "supporting_result_count": recommendation.supporting_result_count,
            "reasons": list(recommendation.reasons),
            "budget_expanded": False,
        }

    return (
        FunctionTool(
            ToolSpec(
                AgentAction.LIST_RESEARCH_HYPOTHESES.value,
                "list bounded structured hypothesis memory",
                AgentAction.LIST_RESEARCH_HYPOTHESES,
                ToolMode.READ,
                optional_arguments=frozenset({"limit"}),
            ),
            list_hypotheses,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.INSPECT_RESEARCH_HYPOTHESIS.value,
                "inspect one bounded hypothesis evidence summary",
                AgentAction.INSPECT_RESEARCH_HYPOTHESIS,
                ToolMode.READ,
                frozenset({"hypothesis_id"}),
                frozenset({"max_nodes", "max_failures"}),
            ),
            inspect_hypothesis,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.FIND_SIMILAR_HYPOTHESES.value,
                "find deterministic near-duplicate hypotheses from relational memory",
                AgentAction.FIND_SIMILAR_HYPOTHESES,
                ToolMode.READ,
                frozenset({"statement"}),
                frozenset({"tags", "exclude_hypothesis_id", "limit"}),
            ),
            find_similar,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.INSPECT_RESEARCH_LINEAGE.value,
                "inspect a bounded cross-registry research/portfolio/operation lineage graph",
                AgentAction.INSPECT_RESEARCH_LINEAGE,
                ToolMode.READ,
                frozenset({"node_key"}),
                frozenset({"max_depth", "max_nodes"}),
            ),
            inspect_lineage,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.INSPECT_RESEARCH_FAILURES.value,
                "inspect normalized research and operational failure history",
                AgentAction.INSPECT_RESEARCH_FAILURES,
                ToolMode.READ,
                optional_arguments=frozenset(
                    {"hypothesis_id", "experiment_id", "category", "limit"}
                ),
            ),
            inspect_failures,
        ),
        FunctionTool(
            ToolSpec(
                AgentAction.RECOMMEND_RESEARCH_BUDGET.value,
                "recommend a bounded experiment budget that can never exceed the requested budget",
                AgentAction.RECOMMEND_RESEARCH_BUDGET,
                ToolMode.READ,
                frozenset({"statement", "requested_max_experiments"}),
                frozenset({"tags", "hypothesis_id"}),
            ),
            recommend_budget,
        ),
    )
