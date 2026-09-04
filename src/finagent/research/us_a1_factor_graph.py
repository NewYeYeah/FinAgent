from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: object, field_name: str, *, maximum_length: int | None = None) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    if maximum_length is not None and len(rendered) > maximum_length:
        raise ValueError(f"{field_name} exceeds maximum length {maximum_length}")
    return rendered


def _bounded_texts(
    values: tuple[str, ...],
    field_name: str,
    *,
    maximum_items: int,
    maximum_length: int,
) -> tuple[str, ...]:
    rendered = tuple(_text(item, f"{field_name}[]", maximum_length=maximum_length) for item in values)
    if len(rendered) > maximum_items:
        raise ValueError(f"{field_name} exceeds maximum item count {maximum_items}")
    if len(rendered) != len(set(rendered)):
        raise ValueError(f"{field_name} values must be unique")
    return rendered


class FactorInputField(StrEnum):
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


class FactorSemanticType(StrEnum):
    PRICE = "PRICE"
    VOLUME = "VOLUME"
    DIMENSIONLESS = "DIMENSIONLESS"


class FactorScope(StrEnum):
    TIME_SERIES = "TIME_SERIES"
    CROSS_SECTIONAL = "CROSS_SECTIONAL"


class FactorOperator(StrEnum):
    INPUT = "INPUT"
    CONSTANT = "CONSTANT"
    LAG = "LAG"
    SIMPLE_RETURN = "SIMPLE_RETURN"
    LOG_RETURN = "LOG_RETURN"
    ROLLING_MEAN = "ROLLING_MEAN"
    ROLLING_STD = "ROLLING_STD"
    ROLLING_MIN = "ROLLING_MIN"
    ROLLING_MAX = "ROLLING_MAX"
    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MULTIPLY = "MULTIPLY"
    SAFE_DIVIDE = "SAFE_DIVIDE"
    NEGATE = "NEGATE"
    CROSS_SECTION_RANK = "CROSS_SECTION_RANK"
    CROSS_SECTION_ZSCORE = "CROSS_SECTION_ZSCORE"
    CLIP = "CLIP"
    WINSORIZE = "WINSORIZE"
    REGIME_GATE = "REGIME_GATE"


class FactorZeroDenominatorAction(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    CONSTANT = "CONSTANT"


class FactorExpectedDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    REGIME_DEPENDENT = "REGIME_DEPENDENT"
    UNSPECIFIED = "UNSPECIFIED"


class FactorMechanismCategory(StrEnum):
    MOMENTUM = "MOMENTUM"
    REVERSAL = "REVERSAL"
    VOLATILITY = "VOLATILITY"
    LIQUIDITY_VOLUME = "LIQUIDITY_VOLUME"
    PRICE_LOCATION = "PRICE_LOCATION"
    RANGE = "RANGE"
    INTERACTION = "INTERACTION"
    REGIME_CONDITIONAL = "REGIME_CONDITIONAL"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class FactorDenominatorPolicy:
    epsilon: float
    action: FactorZeroDenominatorAction
    fallback_value: float | None = None
    schema_version: str = "finagent.us-a1-factor-denominator-policy.v1"

    def __post_init__(self) -> None:
        if not math.isfinite(self.epsilon) or self.epsilon < 0:
            raise ValueError("denominator epsilon must be finite and >= 0")
        if self.action is FactorZeroDenominatorAction.CONSTANT:
            if self.fallback_value is None or not math.isfinite(self.fallback_value):
                raise ValueError("CONSTANT denominator policy requires a finite fallback_value")
        elif self.fallback_value is not None:
            raise ValueError("UNAVAILABLE denominator policy cannot carry fallback_value")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "epsilon": self.epsilon,
            "action": self.action.value,
            "fallback_value": self.fallback_value,
        }


@dataclass(frozen=True, slots=True)
class FactorComplexityBudget:
    max_nodes: int = 32
    max_edges: int = 48
    max_depth: int = 8
    max_window_bars: int = 26
    max_lookback_bars: int = 26
    max_regime_gates: int = 2
    schema_version: str = "finagent.us-a1-factor-complexity-budget.v1"

    def __post_init__(self) -> None:
        values = (
            self.max_nodes,
            self.max_edges,
            self.max_depth,
            self.max_window_bars,
            self.max_lookback_bars,
        )
        if any(value < 1 for value in values):
            raise ValueError("factor complexity limits must be positive")
        if self.max_regime_gates < 0:
            raise ValueError("max_regime_gates must be >= 0")
        if self.max_edges < self.max_nodes - 1:
            raise ValueError("max_edges must permit at least a connected max-node DAG")

    @property
    def budget_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-a1-factor-budget")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
            "max_depth": self.max_depth,
            "max_window_bars": self.max_window_bars,
            "max_lookback_bars": self.max_lookback_bars,
            "max_regime_gates": self.max_regime_gates,
        }
        if include_id:
            payload["budget_id"] = self.budget_id
        return payload


@dataclass(frozen=True, slots=True)
class FactorNode:
    node_id: str
    operator: FactorOperator
    inputs: tuple[str, ...] = ()
    input_field: FactorInputField | None = None
    constant_value: float | None = None
    window_bars: int | None = None
    lag_bars: int | None = None
    denominator_policy: FactorDenominatorPolicy | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    lower_quantile: float | None = None
    upper_quantile: float | None = None
    regime_labels: tuple[str, ...] = ()
    schema_version: str = "finagent.us-a1-factor-node.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "node_id", maximum_length=80))
        normalized_inputs = tuple(_text(item, "inputs[]", maximum_length=80) for item in self.inputs)
        object.__setattr__(self, "inputs", normalized_inputs)
        if self.constant_value is not None and not math.isfinite(self.constant_value):
            raise ValueError("constant_value must be finite when present")
        for field_name in ("lower_bound", "upper_bound", "lower_quantile", "upper_quantile"):
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite when present")
        labels = _bounded_texts(
            self.regime_labels,
            "regime_labels",
            maximum_items=8,
            maximum_length=64,
        )
        object.__setattr__(self, "regime_labels", tuple(sorted(labels)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "operator": self.operator.value,
            "inputs": list(self.inputs),
            "input_field": self.input_field.value if self.input_field is not None else None,
            "constant_value": self.constant_value,
            "window_bars": self.window_bars,
            "lag_bars": self.lag_bars,
            "denominator_policy": (
                self.denominator_policy.to_dict() if self.denominator_policy is not None else None
            ),
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "lower_quantile": self.lower_quantile,
            "upper_quantile": self.upper_quantile,
            "regime_labels": list(self.regime_labels),
        }


@dataclass(frozen=True, slots=True)
class FactorGraphSpec:
    nodes: tuple[FactorNode, ...]
    output_node_id: str
    budget: FactorComplexityBudget = FactorComplexityBudget()
    signal_interval: str = "15m"
    same_session_only: bool = True
    require_complete_bars: bool = True
    price_basis: str = "RAW"
    availability_policy: str = "available_at"
    regime_policy_id: str | None = None
    schema_version: str = "finagent.us-a1-factor-graph-spec.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_node_id",
            _text(self.output_node_id, "output_node_id", maximum_length=80),
        )
        if self.signal_interval != "15m":
            raise ValueError("US-A1 v1 factor graphs use the accepted 15m signal clock")
        if not self.same_session_only or not self.require_complete_bars:
            raise ValueError("US-A1 v1 factor graphs require same-session complete bars")
        if self.price_basis != "RAW" or self.availability_policy != "available_at":
            raise ValueError("US-A1 v1 factor graphs preserve RAW/available_at semantics")
        if self.regime_policy_id is not None:
            object.__setattr__(
                self,
                "regime_policy_id",
                _text(self.regime_policy_id, "regime_policy_id", maximum_length=120),
            )

    @property
    def proposal_graph_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-a1-graph-proposal")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "nodes": [item.to_dict() for item in self.nodes],
            "output_node_id": self.output_node_id,
            "budget": self.budget.to_dict(),
            "signal_interval": self.signal_interval,
            "same_session_only": self.same_session_only,
            "require_complete_bars": self.require_complete_bars,
            "price_basis": self.price_basis,
            "availability_policy": self.availability_policy,
            "regime_policy_id": self.regime_policy_id,
            "executable_code_authority": False,
            "provider_specific_data_access": False,
            "label_access": False,
        }
        if include_id:
            payload["proposal_graph_id"] = self.proposal_graph_id
        return payload


@dataclass(frozen=True, slots=True)
class FactorCanonicalizationEvidence:
    proposal_graph_id: str
    candidate_id: str
    root_digest: str
    canonical_node_digests: tuple[str, ...]
    required_input_fields: tuple[str, ...]
    inferred_semantic_type: FactorSemanticType
    inferred_scope: FactorScope
    lookback_bars: int
    depth: int
    commutative_reorder_count: int
    schema_version: str = "finagent.us-a1-factor-canonicalization-evidence.v1"

    def __post_init__(self) -> None:
        for field_name in ("proposal_graph_id", "candidate_id", "root_digest"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.lookback_bars < 1 or self.depth < 1:
            raise ValueError("canonicalized factor lookback/depth must be positive")
        if self.commutative_reorder_count < 0:
            raise ValueError("commutative_reorder_count must be >= 0")
        if len(self.canonical_node_digests) != len(set(self.canonical_node_digests)):
            raise ValueError("canonical_node_digests must be unique")

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-a1-canonicalization")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "proposal_graph_id": self.proposal_graph_id,
            "candidate_id": self.candidate_id,
            "root_digest": self.root_digest,
            "canonical_node_digests": list(self.canonical_node_digests),
            "required_input_fields": list(self.required_input_fields),
            "inferred_semantic_type": self.inferred_semantic_type.value,
            "inferred_scope": self.inferred_scope.value,
            "lookback_bars": self.lookback_bars,
            "depth": self.depth,
            "commutative_reorder_count": self.commutative_reorder_count,
            "candidate_identity_independent_of_node_ids_and_order": True,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class FactorGraphValidationEvidence:
    proposal_graph_id: str
    valid: bool
    node_count: int
    edge_count: int
    reachable_node_count: int
    blockers: tuple[str, ...]
    canonicalization: FactorCanonicalizationEvidence | None
    schema_version: str = "finagent.us-a1-factor-graph-validation-evidence.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_graph_id", _text(self.proposal_graph_id, "proposal_graph_id"))
        if min(self.node_count, self.edge_count, self.reachable_node_count) < 0:
            raise ValueError("factor validation counts must be >= 0")
        blockers = tuple(dict.fromkeys(_text(item, "blockers[]") for item in self.blockers))
        object.__setattr__(self, "blockers", blockers)
        if self.valid != (not blockers):
            raise ValueError("factor validation valid flag must match blockers")
        if self.valid != (self.canonicalization is not None):
            raise ValueError("valid factor graph requires canonicalization evidence")

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-a1-factor-validation")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "proposal_graph_id": self.proposal_graph_id,
            "valid": self.valid,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "reachable_node_count": self.reachable_node_count,
            "blockers": list(self.blockers),
            "canonicalization": (
                self.canonicalization.to_dict() if self.canonicalization is not None else None
            ),
            "validation_complexity": "O(V+E)_plus_bounded_commutative_child_sort",
            "arbitrary_code_execution_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class FactorFalsificationSpec:
    criteria: tuple[str, ...]
    invalidating_conditions: tuple[str, ...]
    schema_version: str = "finagent.us-a1-factor-falsification-spec.v1"

    def __post_init__(self) -> None:
        criteria = _bounded_texts(
            self.criteria,
            "criteria",
            maximum_items=8,
            maximum_length=200,
        )
        conditions = _bounded_texts(
            self.invalidating_conditions,
            "invalidating_conditions",
            maximum_items=8,
            maximum_length=200,
        )
        if not criteria:
            raise ValueError("falsification criteria cannot be empty")
        object.__setattr__(self, "criteria", criteria)
        object.__setattr__(self, "invalidating_conditions", conditions)

    @property
    def falsification_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-a1-falsification")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "criteria": list(self.criteria),
            "invalidating_conditions": list(self.invalidating_conditions),
            "executable_content": False,
        }
        if include_id:
            payload["falsification_id"] = self.falsification_id
        return payload


@dataclass(frozen=True, slots=True)
class FactorHypothesisSpec:
    candidate_id: str
    summary: str
    mechanism_category: FactorMechanismCategory
    expected_direction: FactorExpectedDirection
    expected_regime_scope: tuple[str, ...]
    required_input_fields: tuple[FactorInputField, ...]
    falsification: FactorFalsificationSpec
    parent_candidate_ids: tuple[str, ...] = ()
    schema_version: str = "finagent.us-a1-factor-hypothesis-spec.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "summary", _text(self.summary, "summary", maximum_length=280))
        regimes = _bounded_texts(
            self.expected_regime_scope,
            "expected_regime_scope",
            maximum_items=8,
            maximum_length=64,
        )
        parents = _bounded_texts(
            self.parent_candidate_ids,
            "parent_candidate_ids",
            maximum_items=8,
            maximum_length=120,
        )
        fields = tuple(sorted(set(self.required_input_fields), key=lambda item: item.value))
        if not fields:
            raise ValueError("hypothesis required_input_fields cannot be empty")
        object.__setattr__(self, "expected_regime_scope", tuple(sorted(regimes)))
        object.__setattr__(self, "parent_candidate_ids", tuple(sorted(parents)))
        object.__setattr__(self, "required_input_fields", fields)

    @property
    def hypothesis_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-a1-hypothesis")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "summary": self.summary,
            "mechanism_category": self.mechanism_category.value,
            "expected_direction": self.expected_direction.value,
            "expected_regime_scope": list(self.expected_regime_scope),
            "required_input_fields": [item.value for item in self.required_input_fields],
            "falsification": self.falsification.to_dict(),
            "parent_candidate_ids": list(self.parent_candidate_ids),
            "stored_reasoning_scope": "structured_hypothesis_and_falsification_only_no_chain_of_thought",
            "financial_data_access_authority": False,
            "execution_authority": False,
        }
        if include_id:
            payload["hypothesis_id"] = self.hypothesis_id
        return payload
