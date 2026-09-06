"""Strict R4 product actions over the existing R3 FactorProposal boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, cast

from finagent.agents.r3_contracts import (
    ContractError,
    ResearchAction,
    _object,
    _text,
    action_guide,
    canonical_json,
    decode_action,
    identifier,
    integer,
    strict_json,
)
from finagent.research.us_a1_factor_graph import FactorExpectedDirection

AUTHORITY = {
    "development_only": True,
    "independent_confirmation": False,
    "alpha_authority": False,
    "paper_authority": False,
    "live_authority": False,
    "r5_eligible": False,
}
ALLOCATORS = (
    "equal_weight",
    "rolling_ic",
    "rolling_net_return",
    "regime_conditional",
    "ridge_meta",
)


class R4Tool(StrEnum):
    INSPECT_MARKET_STATE = "inspect_market_state"
    INSPECT_FACTOR_LIBRARY = "inspect_factor_library"
    INSPECT_FACTOR = "inspect_factor"
    INSPECT_EXPERIMENT_HISTORY = "inspect_experiment_history"
    READ_LITERATURE = "read_literature"
    PROPOSE_FACTOR = "propose_factor"
    VALIDATE_FACTOR = "validate_factor"
    EVALUATE_FACTOR = "evaluate_factor"
    PROPOSE_FACTOR_SET = "propose_factor_set"
    PROPOSE_ALLOCATOR = "propose_allocator"
    EVALUATE_PORTFOLIO = "evaluate_portfolio"
    COMPARE_EXPERIMENTS = "compare_experiments"
    ALLOCATE_BUDGET = "allocate_budget"
    RETIRE_HYPOTHESIS = "retire_hypothesis"
    RECORD_DECISION = "record_decision"
    FINALIZE_CANDIDATE = "finalize_candidate"


FIELDS: dict[str, tuple[str, ...]] = {
    "inspect_market_state": (),
    "inspect_factor_library": ("offset",),
    "inspect_factor": ("factor_id",),
    "inspect_experiment_history": ("offset",),
    "read_literature": ("record_id",),
    "propose_factor": ("nodes", "output_node_id", "hypothesis"),
    "validate_factor": ("nodes", "output_node_id", "hypothesis"),
    "evaluate_factor": ("candidate_id",),
    "propose_factor_set": ("factor_ids", "hypothesis_id"),
    "propose_allocator": ("allocator",),
    "evaluate_portfolio": ("factor_set_id", "allocator_proposal_id", "hypothesis_id"),
    "compare_experiments": ("experiment_ids",),
    "allocate_budget": ("hypothesis_id",),
    "retire_hypothesis": ("factor_id", "status", "reason", "experiment_ids"),
    "record_decision": ("critique", "next_action"),
    "finalize_candidate": (
        "recommendation",
        "factor_set_id",
        "allocator_proposal_id",
        "experiment_ids",
        "decision",
    ),
}


def r4_manifest() -> dict[str, Any]:
    factor_proposal = cast(dict[str, Any], action_guide()["arguments"])[
        "validate_factor|submit_factor"
    ]
    factor_proposal["hypothesis"]["direction"] = [FactorExpectedDirection.POSITIVE.value]
    return {
        "schema_version": "finagent.r4-action.v1",
        "tools": FIELDS,
        "authority": AUTHORITY,
        "allocator_catalog": ALLOCATORS,
        "allocator_config": {"lookback_sessions": 20, "minimum_observations": 5, "ridge_alpha": 1},
        "factor_proposal": factor_proposal,
        "node_parameters": action_guide()["node_parameters"],
        "rules": "Return {schema_version,tool,arguments} only. Exact argument fields. offset pages 20 attempts or 5 factors. IDs from admitted results/resources only. experiment_ids 1..5. finalize recommendation=candidate|none; none uses null set/allocator and may use empty experiment_ids. No reasoning/scratchpad, paths, budget changes or arbitrary parameters.",
    }


def r3_proposal(action: dict[str, Any]) -> ResearchAction:
    proposal = decode_action(
        canonical_json(
            {
                "schema_version": "finagent.us-r3-agent-action.v2",
                "tool": "validate_factor",
                "arguments": {
                    k: v for k, v in action["arguments"].items() if k != "repairs_request_id"
                },
            }
        )
    )
    if (
        proposal.proposal is not None
        and proposal.proposal.direction is not FactorExpectedDirection.POSITIVE
    ):
        raise ContractError("positive_graph_direction_required_use_explicit_NEGATE")
    return proposal


def decode_r4_action(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = _object(strict_json(raw), {"schema_version", "tool", "arguments"})
    if data["schema_version"] != "finagent.r4-action.v1":
        raise ContractError("action_schema_mismatch")
    try:
        tool = R4Tool(data["tool"]).value
    except (ValueError, TypeError):
        raise ContractError("unknown_r4_tool") from None
    args = _object(
        data["arguments"],
        set(FIELDS[tool]),
        {"repairs_request_id"} if tool in {"propose_factor", "validate_factor"} else None,
    )
    if tool in {"propose_factor", "validate_factor"}:
        if "repairs_request_id" in args:
            identifier(args["repairs_request_id"])
        r3_proposal(data)
        return data
    for name, value in args.items():
        if name == "offset":
            integer(value, 0, 1000)
        elif name in {"factor_ids", "experiment_ids"}:
            low, high = (2, 20) if name == "factor_ids" else (0, 5)
            if not isinstance(value, list) or not low <= len(value) <= high:
                raise ContractError("reference_list_bound")
            if len({identifier(v) for v in value}) != len(value):
                raise ContractError("duplicate_reference")
            if not value and tool not in {"finalize_candidate", "retire_hypothesis"}:
                raise ContractError("empty_experiment_selection")
        elif name in {"critique", "next_action", "decision", "reason"}:
            _text(value, 400)
        elif name == "allocator":
            if value not in ALLOCATORS:
                raise ContractError("allocator_not_admitted")
        elif name == "status":
            if value not in {"DORMANT", "REJECTED", "RETIRED", "TESTING"}:
                raise ContractError("lifecycle_authority_denied")
        elif name == "recommendation":
            if value not in {"candidate", "none"}:
                raise ContractError("invalid_recommendation")
        elif (
            value is None
            and tool == "finalize_candidate"
            and name in {"factor_set_id", "allocator_proposal_id"}
        ):
            continue
        else:
            identifier(value)
    return data
