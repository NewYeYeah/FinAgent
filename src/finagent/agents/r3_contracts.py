"""Typed, versioned R3 research capabilities. No executable model content."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, cast

from finagent.research.us_a1_factor_graph import (
    FactorDenominatorPolicy,
    FactorExpectedDirection,
    FactorFalsificationSpec,
    FactorGraphSpec,
    FactorHypothesisSpec,
    FactorInputField,
    FactorMechanismCategory,
    FactorNode,
    FactorOperator,
    FactorZeroDenominatorAction,
)
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_r3_agent_boundary import canonical_us_r3_agent_boundary_policy


class ContractError(ValueError):
    """Safe fixed diagnostic, never a raw model response or exception excerpt."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def identity(value: object, prefix: str) -> str:
    return prefix + "-" + hashlib.sha256(canonical_json(value).encode()).hexdigest()[:24]


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value):
        raise ContractError("invalid_identifier")
    return value


def integer(value: object, minimum: int = 0, maximum: int = 1_000_000_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError("invalid_integer")
    return value


def number(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(cast(float, value)):
        raise ContractError("invalid_finite_number")
    return float(cast(float, value))


def _object(value: object, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - (optional or set())
    ):
        raise ContractError("invalid_object_fields")
    return cast(dict[str, Any], value)


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError("invalid_text")
    return value


def _texts(value: object, limit: int = 200) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ContractError("invalid_text_list")
    result = tuple(_text(item, limit) for item in value)
    if len(set(result)) != len(result):
        raise ContractError("duplicate_text")
    return result


def strict_json(raw: str, maximum_bytes: int = 32768) -> object:
    if not isinstance(raw, str):
        raise ContractError("payload_bound_exceeded")
    try:
        if len(raw.encode("utf-8")) > maximum_bytes:
            raise ContractError("payload_bound_exceeded")
    except UnicodeError:
        raise ContractError("invalid_json") from None

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ContractError("duplicate_json_key")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise ContractError("nonfinite_json")

    def bounded(value: object, depth: int = 0) -> None:
        if depth > 16:
            raise ContractError("json_depth_exceeded")
        if isinstance(value, dict):
            for child in value.values():
                bounded(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                bounded(child, depth + 1)
        elif isinstance(value, str):
            value.encode("utf-8")

    try:
        result: object = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        bounded(result)
        return result
    except (json.JSONDecodeError, RecursionError, UnicodeError) as error:
        raise ContractError("invalid_json") from error


class ResearchTool(StrEnum):
    VALIDATE_FACTOR = "validate_factor"
    SUBMIT_FACTOR = "submit_factor"
    READ_DEVELOPMENT = "read_development"
    READ_LITERATURE = "read_literature"
    EVALUATE_DEVELOPMENT = "evaluate_development"
    RECALL = "recall"


@dataclass(frozen=True, slots=True)
class ResearchRuntimePolicy:
    maximum_slots: int = 24
    maximum_attempts: int = 72
    maximum_attempts_per_slot: int = 6
    maximum_evaluations: int = 24
    maximum_tokens: int = 65536
    tokens_per_call: int = 16384
    maximum_cost_microusd: int = 250000
    cost_per_call_microusd: int = 50000
    maximum_run_seconds: float = 900.0
    call_timeout_seconds: float = 30.0
    feedback_enabled: bool = True
    schema_version: str = "finagent.us-r3-agent-runtime-policy.v2"

    def __post_init__(self) -> None:
        if self.schema_version != "finagent.us-r3-agent-runtime-policy.v2":
            raise ContractError("policy_schema_mismatch")
        integer(self.maximum_slots, 1, 24)
        for name in (
            "maximum_attempts",
            "maximum_attempts_per_slot",
            "maximum_tokens",
            "tokens_per_call",
            "maximum_cost_microusd",
            "cost_per_call_microusd",
        ):
            integer(getattr(self, name), 1)
        integer(self.maximum_evaluations)
        if (
            self.maximum_tokens < self.tokens_per_call
            or self.maximum_cost_microusd < self.cost_per_call_microusd
        ):
            raise ContractError("call_budget_exceeds_run_budget")
        if not 0 < number(self.call_timeout_seconds) <= number(self.maximum_run_seconds):
            raise ContractError("invalid_timeout")
        if type(self.feedback_enabled) is not bool:
            raise ContractError("invalid_feedback_flag")

    @property
    def tools(self) -> tuple[ResearchTool, ...]:
        return tuple(
            tool
            for tool in ResearchTool
            if self.feedback_enabled
            or tool
            in (
                ResearchTool.VALIDATE_FACTOR,
                ResearchTool.SUBMIT_FACTOR,
                ResearchTool.READ_LITERATURE,
                ResearchTool.RECALL,
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "legacy_policy_id": canonical_us_r3_agent_boundary_policy().policy_id,
            "tools": [tool.value for tool in self.tools],
            "arbitrary_code": False,
            "outer_final_reserve_access": False,
            "broker_access": False,
            "alpha_authority": False,
            "unknown_usage_action": "charge_full_reservation_and_stop",
            "memory_scope": "current_run_admitted_results_only",
        }

    @property
    def policy_id(self) -> str:
        return identity(self.to_dict(), "us-r3-agent-runtime-policy")


@dataclass(frozen=True, slots=True)
class DevelopmentRecord:
    """Admitted by the trusted host, never deserialized from a model action.

    Payloads are small, immutable JSON values. Label arrays/raw rows are absent.
    Host admission must independently establish source and split authenticity.
    """

    scope_id: str
    source_id: str
    kind: str
    payload_json: str
    partition: str = "development"

    def __post_init__(self) -> None:
        identifier(self.scope_id)
        identifier(self.source_id)
        if self.partition != "development":
            raise ContractError("nondevelopment_record_denied")
        payload = strict_json(self.payload_json, 2048)
        if self.kind == "literature":
            data = _object(payload, {"title", "url", "summary"})
            for key in data:
                _text(data[key], 512)
            if not data["url"].startswith("https://"):
                raise ContractError("invalid_curated_source_url")
        elif self.kind == "coverage":
            data = _object(payload, {"row_count", "available_count"})
            if integer(data["available_count"]) > integer(data["row_count"]):
                raise ContractError("invalid_coverage_counts")
        elif self.kind == "evaluation":
            data = _object(payload, {"candidate_id", "evaluator_id", "metrics"})
            identifier(data["candidate_id"])
            identifier(data["evaluator_id"])
            metrics = _object(
                data["metrics"], set(), {"rank_ic", "turnover", "net_return_bps", "valid_count"}
            )
            if not metrics:
                raise ContractError("empty_evaluation")
            for key, value in metrics.items():
                integer(value) if key == "valid_count" else number(value)
        else:
            raise ContractError("record_kind_denied")
        object.__setattr__(self, "payload_json", canonical_json(payload))

    def to_dict(self) -> dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "source_id": self.source_id,
            "kind": self.kind,
            "partition": self.partition,
            "payload": json.loads(self.payload_json),
        }

    @property
    def record_id(self) -> str:
        return identity(self.to_dict(), "us-r3-development-record")


@dataclass(frozen=True, slots=True)
class DevelopmentScope:
    scope_id: str
    records: tuple[DevelopmentRecord, ...] = ()
    evaluation_source_id: str | None = None
    evaluator_id: str | None = None

    def __post_init__(self) -> None:
        identifier(self.scope_id)
        object.__setattr__(self, "records", tuple(self.records))
        if len(self.records) > 32 or len({item.record_id for item in self.records}) != len(
            self.records
        ):
            raise ContractError("scope_record_bound_or_duplicate")
        if any(item.scope_id != self.scope_id for item in self.records):
            raise ContractError("cross_scope_record_denied")
        if (self.evaluation_source_id is None) != (self.evaluator_id is None):
            raise ContractError("incomplete_evaluator_binding")
        if self.evaluator_id is not None:
            identifier(self.evaluator_id)
            identifier(self.evaluation_source_id)

    @property
    def manifest_id(self) -> str:
        return identity(
            {
                "scope_id": self.scope_id,
                "records": [item.record_id for item in self.records],
                "evaluation_source_id": self.evaluation_source_id,
                "evaluator_id": self.evaluator_id,
            },
            "us-r3-development-scope",
        )


@dataclass(frozen=True, slots=True)
class FactorProposal:
    graph: FactorGraphSpec
    summary: str
    mechanism: FactorMechanismCategory
    direction: FactorExpectedDirection
    criteria: tuple[str, ...]
    invalidating_conditions: tuple[str, ...]

    def hypothesis(self) -> FactorHypothesisSpec:
        result = validate_factor_graph(self.graph)
        if not result.valid or result.canonicalization is None:
            raise ContractError("invalid_factor_graph")
        return FactorHypothesisSpec(
            candidate_id=result.canonicalization.candidate_id,
            summary=self.summary,
            mechanism_category=self.mechanism,
            expected_direction=self.direction,
            expected_regime_scope=("development_only",),
            required_input_fields=tuple(
                FactorInputField(item) for item in result.canonicalization.required_input_fields
            ),
            falsification=FactorFalsificationSpec(self.criteria, self.invalidating_conditions),
        )


@dataclass(frozen=True, slots=True)
class ResearchAction:
    tool: ResearchTool
    reference_id: str | None = None
    proposal: FactorProposal | None = None


def action_guide() -> dict[str, object]:
    """Bounded wire instructions supplied to every provider, not an implicit SDK dependency."""
    return {
        "envelope": {
            "schema_version": "finagent.us-r3-agent-action.v2",
            "tool": "allowed tool",
            "arguments": {},
        },
        "arguments": {
            "read_literature|read_development": {"record_id": "admitted resource ID"},
            "evaluate_development": {"candidate_id": "previously VALIDATED candidate ID"},
            "recall": {},
            "validate_factor|submit_factor": {
                "nodes": "1..32 nodes, each {node_id,operator,inputs:[node IDs], operator-specific parameters}",
                "output_node_id": "root node ID",
                "hypothesis": {
                    "summary": "nonempty <=280 chars",
                    "mechanism": [item.value for item in FactorMechanismCategory],
                    "direction": [item.value for item in FactorExpectedDirection],
                    "criteria": ["1..8 falsifiable criteria, each <=200 chars"],
                    "invalidating_conditions": ["1..8 invalidation conditions, each <=200 chars"],
                },
            },
        },
        "node_parameters": {
            "INPUT": "input_field: open|high|low|close|volume; no inputs",
            "CONSTANT": "constant_value: finite number; no inputs",
            "LAG": "one input, lag_bars: integer 1..26",
            "SIMPLE_RETURN|LOG_RETURN": "one input, window_bars: integer 2..26",
            "ROLLING_MEAN|ROLLING_STD|ROLLING_MIN|ROLLING_MAX": "one input, window_bars: integer 1..26",
            "ADD|SUBTRACT|MULTIPLY": "two inputs",
            "SAFE_DIVIDE": "two inputs, denominator_policy: {epsilon: nonnegative number, action: UNAVAILABLE|CONSTANT, fallback_value: finite number only for CONSTANT}",
            "NEGATE|CROSS_SECTION_RANK|CROSS_SECTION_ZSCORE": "one input",
            "CLIP": "one input, lower_bound and upper_bound: finite numbers",
            "WINSORIZE": "one input, lower_quantile and upper_quantile: numbers 0..1",
        },
        "limits": "JSON only; no extra fields, code or reasoning. IDs: letters/digits/_/-, <=80 chars for nodes. Total graph lookback <=26, depth <=8, edges <=48. Operator parameters must match operator. REGIME_GATE unavailable.",
    }


def _node(value: object) -> FactorNode:
    data = _object(
        value,
        {"node_id", "operator"},
        {
            "inputs",
            "input_field",
            "constant_value",
            "window_bars",
            "lag_bars",
            "denominator_policy",
            "lower_bound",
            "upper_bound",
            "lower_quantile",
            "upper_quantile",
        },
    )
    operator = FactorOperator(data["operator"])
    if operator is FactorOperator.REGIME_GATE:
        raise ContractError("regime_source_not_admitted")
    inputs = data.get("inputs", [])
    if not isinstance(inputs, list) or len(inputs) > 2:
        raise ContractError("invalid_node_inputs")
    parameters: dict[str, Any] = {}
    for key in ("constant_value", "lower_bound", "upper_bound", "lower_quantile", "upper_quantile"):
        if key in data:
            parameters[key] = number(data[key])
    for key in ("window_bars", "lag_bars"):
        if key in data:
            parameters[key] = integer(data[key], 1, 26)
    if "input_field" in data:
        parameters["input_field"] = FactorInputField(data["input_field"])
    if "denominator_policy" in data:
        denominator = _object(data["denominator_policy"], {"epsilon", "action"}, {"fallback_value"})
        parameters["denominator_policy"] = FactorDenominatorPolicy(
            epsilon=number(denominator["epsilon"]),
            action=FactorZeroDenominatorAction(denominator["action"]),
            fallback_value=number(denominator["fallback_value"])
            if "fallback_value" in denominator
            else None,
        )
    return FactorNode(
        identifier(data["node_id"]),
        operator,
        tuple(identifier(item) for item in inputs),
        **parameters,
    )


def decode_action(raw: str) -> ResearchAction:
    data = _object(strict_json(raw), {"schema_version", "tool", "arguments"})
    if data["schema_version"] != "finagent.us-r3-agent-action.v2":
        raise ContractError("action_schema_mismatch")
    try:
        tool = ResearchTool(data["tool"])
        if tool in (ResearchTool.READ_DEVELOPMENT, ResearchTool.READ_LITERATURE):
            args = _object(data["arguments"], {"record_id"})
            return ResearchAction(tool, identifier(args["record_id"]))
        if tool is ResearchTool.EVALUATE_DEVELOPMENT:
            args = _object(data["arguments"], {"candidate_id"})
            return ResearchAction(tool, identifier(args["candidate_id"]))
        if tool is ResearchTool.RECALL:
            _object(data["arguments"], set())
            return ResearchAction(tool)
        args = _object(data["arguments"], {"nodes", "output_node_id", "hypothesis"})
        if not isinstance(args["nodes"], list) or not 1 <= len(args["nodes"]) <= 32:
            raise ContractError("graph_node_bound_exceeded")
        hypothesis = _object(
            args["hypothesis"],
            {"summary", "mechanism", "direction", "criteria", "invalidating_conditions"},
        )
        graph = FactorGraphSpec(
            tuple(_node(item) for item in args["nodes"]), identifier(args["output_node_id"])
        )
        return ResearchAction(
            tool,
            proposal=FactorProposal(
                graph=graph,
                summary=_text(hypothesis["summary"], 280),
                mechanism=FactorMechanismCategory(hypothesis["mechanism"]),
                direction=FactorExpectedDirection(hypothesis["direction"]),
                criteria=_texts(hypothesis["criteria"]),
                invalidating_conditions=_texts(hypothesis["invalidating_conditions"]),
            ),
        )
    except (ValueError, TypeError, KeyError) as error:
        raise ContractError("invalid_action_contract") from error


def proposal_action(
    graph: FactorGraphSpec,
    hypothesis: FactorHypothesisSpec,
    tool: ResearchTool = ResearchTool.SUBMIT_FACTOR,
) -> str:
    """Wire example/exporter for trusted callers; model never supplies authority fields."""
    nodes = []
    for node in graph.nodes:
        payload = {
            key: value
            for key, value in node.to_dict().items()
            if value is not None and key not in ("schema_version", "regime_labels")
        }
        if node.denominator_policy is not None:
            payload["denominator_policy"] = {
                key: value
                for key, value in node.denominator_policy.to_dict().items()
                if key != "schema_version" and value is not None
            }
        nodes.append(payload)
    return canonical_json(
        {
            "schema_version": "finagent.us-r3-agent-action.v2",
            "tool": tool.value,
            "arguments": {
                "nodes": nodes,
                "output_node_id": graph.output_node_id,
                "hypothesis": {
                    "summary": hypothesis.summary,
                    "mechanism": hypothesis.mechanism_category.value,
                    "direction": hypothesis.expected_direction.value,
                    "criteria": hypothesis.falsification.criteria,
                    "invalidating_conditions": hypothesis.falsification.invalidating_conditions,
                },
            },
        }
    )
