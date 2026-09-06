from __future__ import annotations

import hashlib
import heapq
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from finagent.research.us_a1_factor_graph import (
    FactorDenominatorPolicy,
    FactorGraphSpec,
    FactorInputField,
    FactorNode,
    FactorOperator,
    FactorZeroDenominatorAction,
)
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_baselines import USBaselineBar


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _node_parameters(node: FactorNode) -> dict[str, object]:
    operator = node.operator
    if operator is FactorOperator.INPUT:
        return {"input_field": node.input_field.value if node.input_field is not None else None}
    if operator is FactorOperator.CONSTANT:
        return {"constant_value": node.constant_value}
    if operator in {
        FactorOperator.SIMPLE_RETURN,
        FactorOperator.LOG_RETURN,
        FactorOperator.ROLLING_MEAN,
        FactorOperator.ROLLING_STD,
        FactorOperator.ROLLING_MIN,
        FactorOperator.ROLLING_MAX,
    }:
        return {"window_bars": node.window_bars}
    if operator is FactorOperator.LAG:
        return {"lag_bars": node.lag_bars}
    if operator is FactorOperator.SAFE_DIVIDE:
        return {
            "denominator_policy": (
                node.denominator_policy.to_dict() if node.denominator_policy is not None else None
            )
        }
    if operator is FactorOperator.CLIP:
        return {"lower_bound": node.lower_bound, "upper_bound": node.upper_bound}
    if operator is FactorOperator.WINSORIZE:
        return {
            "lower_quantile": node.lower_quantile,
            "upper_quantile": node.upper_quantile,
        }
    if operator is FactorOperator.REGIME_GATE:
        return {"regime_labels": list(node.regime_labels)}
    return {}


def _execution_id(
    node: FactorNode,
    child_execution_ids: tuple[str, ...],
) -> str:
    children = list(child_execution_ids)
    if node.operator in {FactorOperator.ADD, FactorOperator.MULTIPLY}:
        children.sort()
    return _canonical_hash(
        {
            "operator": node.operator.value,
            "inputs": children,
            "parameters": _node_parameters(node),
        },
        prefix="us-a1-factor-node",
    )


def _topological_node_ids(graph: FactorGraphSpec) -> tuple[str, ...]:
    node_by_id = {item.node_id: item for item in graph.nodes}
    indegree = {item.node_id: 0 for item in graph.nodes}
    children: dict[str, list[str]] = {item.node_id: [] for item in graph.nodes}
    for node in graph.nodes:
        for reference in node.inputs:
            indegree[node.node_id] += 1
            children[reference].append(node.node_id)
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for child in children[node_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(node_by_id):
        raise ValueError("validated factor graph unexpectedly contains a cycle")
    return tuple(ordered)


class FactorMaterializationUnavailableReason(StrEnum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    CROSS_SESSION_WINDOW = "CROSS_SESSION_WINDOW"
    INCOMPLETE_BAR = "INCOMPLETE_BAR"
    NUMERIC_UNAVAILABLE = "NUMERIC_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CompiledFactorNode:
    execution_id: str
    operator: FactorOperator
    inputs: tuple[str, ...]
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
    schema_version: str = "finagent.us-a1-compiled-factor-node.v1"

    @classmethod
    def from_node(
        cls,
        node: FactorNode,
        child_execution_ids: tuple[str, ...],
    ) -> CompiledFactorNode:
        canonical_children = child_execution_ids
        if node.operator in {FactorOperator.ADD, FactorOperator.MULTIPLY}:
            canonical_children = tuple(sorted(child_execution_ids))
        return cls(
            execution_id=_execution_id(node, child_execution_ids),
            operator=node.operator,
            inputs=canonical_children,
            input_field=node.input_field,
            constant_value=node.constant_value,
            window_bars=node.window_bars,
            lag_bars=node.lag_bars,
            denominator_policy=node.denominator_policy,
            lower_bound=node.lower_bound,
            upper_bound=node.upper_bound,
            lower_quantile=node.lower_quantile,
            upper_quantile=node.upper_quantile,
            regime_labels=node.regime_labels,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_id": self.execution_id,
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
        }
        # These parameters were not admitted by the original single-asset
        # compiler. Keep absent values out of the payload so every accepted
        # A0/R2 compiled-batch identity remains bitwise stable.
        if self.lower_quantile is not None:
            payload["lower_quantile"] = self.lower_quantile
        if self.upper_quantile is not None:
            payload["upper_quantile"] = self.upper_quantile
        if self.regime_labels:
            payload["regime_labels"] = list(self.regime_labels)
        return payload


@dataclass(frozen=True, slots=True)
class CompiledFactorRoot:
    candidate_id: str
    root_execution_id: str
    lookback_bars: int
    required_input_fields: tuple[str, ...]
    schema_version: str = "finagent.us-a1-compiled-factor-root.v1"

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.root_execution_id.strip():
            raise ValueError("compiled factor root identities must be non-empty")
        if self.lookback_bars < 1:
            raise ValueError("compiled root lookback_bars must be >= 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "root_execution_id": self.root_execution_id,
            "lookback_bars": self.lookback_bars,
            "required_input_fields": list(self.required_input_fields),
        }


@dataclass(frozen=True, slots=True)
class CompiledFactorBatch:
    nodes: tuple[CompiledFactorNode, ...]
    roots: tuple[CompiledFactorRoot, ...]
    naive_node_count: int
    numeric_scope: str = "single_asset_time_series_v1"
    regime_policy_id: str | None = None
    schema_version: str = "finagent.us-a1-compiled-factor-batch.v1"

    def __post_init__(self) -> None:
        if not self.nodes or not self.roots:
            raise ValueError("compiled factor batch requires nodes and roots")
        node_ids = tuple(item.execution_id for item in self.nodes)
        candidate_ids = tuple(item.candidate_id for item in self.roots)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("compiled factor batch nodes must be unique")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("compiled factor batch roots must have unique candidate IDs")
        if self.naive_node_count < len(self.nodes):
            raise ValueError("naive_node_count cannot be smaller than unique compiled nodes")
        if self.numeric_scope not in {
            "single_asset_time_series_v1",
            "multi_asset_panel_v1",
        }:
            raise ValueError("unsupported compiled factor numeric scope")

    @property
    def unique_node_count(self) -> int:
        return len(self.nodes)

    @property
    def reused_node_count(self) -> int:
        return self.naive_node_count - self.unique_node_count

    @property
    def reuse_ratio(self) -> float:
        return self.reused_node_count / self.naive_node_count

    @property
    def batch_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-a1-compiled-factor-batch")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "nodes": [item.to_dict() for item in self.nodes],
            "roots": [item.to_dict() for item in self.roots],
            "candidate_count": len(self.roots),
            "naive_node_count": self.naive_node_count,
            "unique_node_count": self.unique_node_count,
            "reused_node_count": self.reused_node_count,
            "reuse_ratio": self.reuse_ratio,
            "execution_model": "canonical_shared_subexpression_dag",
            "numeric_scope": self.numeric_scope,
        }
        if self.regime_policy_id is not None:
            payload["regime_policy_id"] = self.regime_policy_id
        if include_id:
            payload["batch_id"] = self.batch_id
        return payload


@dataclass(frozen=True, slots=True)
class FactorCandidateSeries:
    candidate_id: str
    values: tuple[float | None, ...]
    unavailable_reasons: tuple[FactorMaterializationUnavailableReason | None, ...]
    lookback_bars: int
    schema_version: str = "finagent.us-a1-factor-candidate-series.v1"

    def __post_init__(self) -> None:
        if len(self.values) != len(self.unavailable_reasons):
            raise ValueError("candidate series values/reasons length mismatch")
        for value, reason in zip(self.values, self.unavailable_reasons, strict=True):
            if (value is None) == (reason is None):
                raise ValueError("exactly one of candidate value/unavailable reason must be set")
            if value is not None and not math.isfinite(value):
                raise ValueError("materialized factor values must be finite")


@dataclass(frozen=True, slots=True)
class FactorBatchMaterialization:
    compiled_batch_id: str
    bar_count: int
    node_series_evaluation_count: int
    candidates: tuple[FactorCandidateSeries, ...]
    schema_version: str = "finagent.us-a1-factor-batch-materialization.v1"

    def __post_init__(self) -> None:
        if self.bar_count < 1:
            raise ValueError("factor materialization requires at least one bar")
        if self.node_series_evaluation_count < 1:
            raise ValueError("node_series_evaluation_count must be positive")
        if any(len(item.values) != self.bar_count for item in self.candidates):
            raise ValueError("every candidate series must cover the complete bar batch")


_UNSUPPORTED_V1 = frozenset(
    {
        FactorOperator.CROSS_SECTION_RANK,
        FactorOperator.CROSS_SECTION_ZSCORE,
        FactorOperator.WINSORIZE,
        FactorOperator.REGIME_GATE,
    }
)


def compile_factor_graph_batch(
    graphs: tuple[FactorGraphSpec, ...],
    *,
    admit_panel_operators: bool = False,
) -> CompiledFactorBatch:
    if not graphs:
        raise ValueError("factor graph compilation requires at least one graph")
    validated: list[tuple[str, FactorGraphSpec, int, tuple[str, ...], str]] = []
    for graph in graphs:
        evidence = validate_factor_graph(graph)
        if not evidence.valid or evidence.canonicalization is None:
            raise ValueError(
                f"cannot compile invalid factor graph {graph.proposal_graph_id}: {evidence.blockers}"
            )
        unsupported = sorted(
            {
                node.operator.value
                for node in graph.nodes
                if node.operator in _UNSUPPORTED_V1 and not admit_panel_operators
            }
        )
        if unsupported:
            raise ValueError(
                "US-A1-1 time-series materializer does not yet admit operators: "
                + ",".join(unsupported)
            )
        validated.append(
            (
                evidence.canonicalization.candidate_id,
                graph,
                evidence.canonicalization.lookback_bars,
                evidence.canonicalization.required_input_fields,
                evidence.canonicalization.root_digest,
            )
        )
    validated.sort(key=lambda item: item[0])
    candidate_ids = tuple(item[0] for item in validated)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("factor batch cannot repeat canonical candidate identities")

    node_by_execution_id: dict[str, CompiledFactorNode] = {}
    roots: list[CompiledFactorRoot] = []
    naive_node_count = 0
    for candidate_id, graph, lookback, required_inputs, expected_root_digest in validated:
        naive_node_count += len(graph.nodes)
        graph_node_by_id = {item.node_id: item for item in graph.nodes}
        local_execution_ids: dict[str, str] = {}
        for node_id in _topological_node_ids(graph):
            graph_node = graph_node_by_id[node_id]
            child_execution_ids = tuple(local_execution_ids[item] for item in graph_node.inputs)
            compiled = CompiledFactorNode.from_node(graph_node, child_execution_ids)
            existing = node_by_execution_id.get(compiled.execution_id)
            if existing is not None and existing.to_dict() != compiled.to_dict():
                raise RuntimeError("canonical execution ID collision")
            node_by_execution_id.setdefault(compiled.execution_id, compiled)
            local_execution_ids[node_id] = compiled.execution_id
        root_execution_id = local_execution_ids[graph.output_node_id]
        if root_execution_id != expected_root_digest:
            raise RuntimeError("compiler root digest diverged from FactorGraph canonicalization")
        roots.append(
            CompiledFactorRoot(
                candidate_id=candidate_id,
                root_execution_id=root_execution_id,
                lookback_bars=lookback,
                required_input_fields=required_inputs,
            )
        )

    dependency_count: dict[str, int] = {item: 0 for item in node_by_execution_id}
    children: dict[str, list[str]] = {item: [] for item in node_by_execution_id}
    for node in node_by_execution_id.values():
        for dependency in node.inputs:
            dependency_count[node.execution_id] += 1
            children[dependency].append(node.execution_id)
    ready = [item for item, count in dependency_count.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[CompiledFactorNode] = []
    while ready:
        execution_id = heapq.heappop(ready)
        ordered.append(node_by_execution_id[execution_id])
        for child in children[execution_id]:
            dependency_count[child] -= 1
            if dependency_count[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(node_by_execution_id):
        raise RuntimeError("compiled shared execution DAG unexpectedly contains a cycle")
    regime_policy_ids = {
        graph.regime_policy_id
        for _, graph, _, _, _ in validated
        if any(node.operator is FactorOperator.REGIME_GATE for node in graph.nodes)
    }
    if len(regime_policy_ids) > 1:
        raise ValueError("panel compilation requires one shared regime_policy_id")
    regime_policy_id = next(iter(regime_policy_ids), None)
    return CompiledFactorBatch(
        nodes=tuple(ordered),
        roots=tuple(sorted(roots, key=lambda item: item.candidate_id)),
        naive_node_count=naive_node_count,
        numeric_scope=(
            "multi_asset_panel_v1" if admit_panel_operators else "single_asset_time_series_v1"
        ),
        regime_policy_id=regime_policy_id,
    )


def _input_series(field: FactorInputField, bars: tuple[USBaselineBar, ...]) -> list[float]:
    if field is FactorInputField.OPEN:
        return [float(item.open) for item in bars]
    if field is FactorInputField.HIGH:
        return [float(item.high) for item in bars]
    if field is FactorInputField.LOW:
        return [float(item.low) for item in bars]
    if field is FactorInputField.CLOSE:
        return [float(item.close) for item in bars]
    if field is FactorInputField.VOLUME:
        return [float(item.volume) for item in bars]
    raise ValueError(f"unsupported factor input field: {field}")


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _window_values(series: list[float | None], end: int, window: int) -> list[float] | None:
    start = end - window + 1
    if start < 0:
        return None
    values = series[start : end + 1]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _evaluate_node_series(
    node: CompiledFactorNode,
    dependencies: tuple[list[float | None], ...],
    bars: tuple[USBaselineBar, ...],
) -> list[float | None]:
    size = len(bars)
    operator = node.operator
    if operator is FactorOperator.INPUT:
        if node.input_field is None:
            raise RuntimeError("compiled INPUT node lost input field")
        return list(_input_series(node.input_field, bars))
    if operator is FactorOperator.CONSTANT:
        if node.constant_value is None:
            raise RuntimeError("compiled CONSTANT node lost value")
        return [node.constant_value] * size
    if operator is FactorOperator.LAG:
        if node.lag_bars is None or len(dependencies) != 1:
            raise RuntimeError("compiled LAG node is malformed")
        source = dependencies[0]
        return [None] * node.lag_bars + source[: max(0, size - node.lag_bars)]
    if operator in {FactorOperator.SIMPLE_RETURN, FactorOperator.LOG_RETURN}:
        if node.window_bars is None or len(dependencies) != 1:
            raise RuntimeError("compiled return node is malformed")
        source = dependencies[0]
        result: list[float | None] = [None] * size
        offset = node.window_bars - 1
        for index in range(offset, size):
            first = source[index - offset]
            last = source[index]
            if first is None or last is None or first <= 0 or last <= 0:
                continue
            if operator is FactorOperator.SIMPLE_RETURN:
                result[index] = _finite_or_none(last / first - 1.0)
            else:
                result[index] = _finite_or_none(math.log(last / first))
        return result
    if operator in {
        FactorOperator.ROLLING_MEAN,
        FactorOperator.ROLLING_STD,
        FactorOperator.ROLLING_MIN,
        FactorOperator.ROLLING_MAX,
    }:
        if node.window_bars is None or len(dependencies) != 1:
            raise RuntimeError("compiled rolling node is malformed")
        source = dependencies[0]
        result = [None] * size
        for index in range(node.window_bars - 1, size):
            values = _window_values(source, index, node.window_bars)
            if values is None:
                continue
            if operator is FactorOperator.ROLLING_MEAN:
                value = sum(values) / len(values)
            elif operator is FactorOperator.ROLLING_STD:
                mean_value = sum(values) / len(values)
                variance = sum((item - mean_value) ** 2 for item in values) / len(values)
                value = math.sqrt(variance)
            elif operator is FactorOperator.ROLLING_MIN:
                value = min(values)
            else:
                value = max(values)
            result[index] = _finite_or_none(value)
        return result
    if operator in {
        FactorOperator.ADD,
        FactorOperator.SUBTRACT,
        FactorOperator.MULTIPLY,
        FactorOperator.SAFE_DIVIDE,
    }:
        if len(dependencies) != 2:
            raise RuntimeError("compiled binary node is malformed")
        left, right = dependencies
        result = [None] * size
        for index, (left_value, right_value) in enumerate(zip(left, right, strict=True)):
            if left_value is None or right_value is None:
                continue
            if operator is FactorOperator.ADD:
                value = left_value + right_value
            elif operator is FactorOperator.SUBTRACT:
                value = left_value - right_value
            elif operator is FactorOperator.MULTIPLY:
                value = left_value * right_value
            else:
                policy = node.denominator_policy
                if policy is None:
                    raise RuntimeError("compiled SAFE_DIVIDE node lost denominator policy")
                if abs(right_value) <= policy.epsilon:
                    if policy.action is FactorZeroDenominatorAction.CONSTANT:
                        if policy.fallback_value is None:
                            raise RuntimeError("compiled denominator fallback is missing")
                        result[index] = policy.fallback_value
                    continue
                value = left_value / right_value
            result[index] = _finite_or_none(value)
        return result
    if operator is FactorOperator.NEGATE:
        if len(dependencies) != 1:
            raise RuntimeError("compiled NEGATE node is malformed")
        return [None if value is None else _finite_or_none(-value) for value in dependencies[0]]
    if operator is FactorOperator.CLIP:
        if node.lower_bound is None or node.upper_bound is None or len(dependencies) != 1:
            raise RuntimeError("compiled CLIP node is malformed")
        return [
            None if value is None else min(node.upper_bound, max(node.lower_bound, value))
            for value in dependencies[0]
        ]
    raise ValueError(
        f"operator is not admitted by the A1-1 time-series materializer: {operator.value}"
    )


def _validate_bars(bars: tuple[USBaselineBar, ...]) -> None:
    if not bars:
        raise ValueError("factor materialization requires at least one bar")
    for left, right in pairwise(bars):
        if right.event_time <= left.event_time:
            raise ValueError("factor materialization bars must be strictly ordered by event_time")
        if right.available_at <= left.available_at:
            raise ValueError("factor materialization bars must be strictly ordered by available_at")


def materialize_compiled_factor_batch(
    compiled: CompiledFactorBatch,
    bars: tuple[USBaselineBar, ...],
    *,
    maximum_bars_per_batch: int = 10_000,
) -> FactorBatchMaterialization:
    _validate_bars(bars)
    if maximum_bars_per_batch < 1:
        raise ValueError("maximum_bars_per_batch must be positive")
    if len(bars) > maximum_bars_per_batch:
        raise ValueError(
            f"factor materialization batch exceeds bounded bar count: {len(bars)}>{maximum_bars_per_batch}"
        )

    series_by_execution_id: dict[str, list[float | None]] = {}
    for node in compiled.nodes:
        dependencies = tuple(series_by_execution_id[item] for item in node.inputs)
        series_by_execution_id[node.execution_id] = _evaluate_node_series(node, dependencies, bars)

    candidates: list[FactorCandidateSeries] = []
    for root in compiled.roots:
        raw_values = series_by_execution_id[root.root_execution_id]
        values: list[float | None] = []
        reasons: list[FactorMaterializationUnavailableReason | None] = []
        for index, raw_value in enumerate(raw_values):
            if index + 1 < root.lookback_bars:
                values.append(None)
                reasons.append(FactorMaterializationUnavailableReason.INSUFFICIENT_HISTORY)
                continue
            window = bars[index - root.lookback_bars + 1 : index + 1]
            current_session = bars[index].session_id
            if any(item.session_id != current_session for item in window):
                values.append(None)
                reasons.append(FactorMaterializationUnavailableReason.CROSS_SESSION_WINDOW)
                continue
            if any(not item.is_complete for item in window):
                values.append(None)
                reasons.append(FactorMaterializationUnavailableReason.INCOMPLETE_BAR)
                continue
            if raw_value is None:
                values.append(None)
                reasons.append(FactorMaterializationUnavailableReason.NUMERIC_UNAVAILABLE)
                continue
            values.append(raw_value)
            reasons.append(None)
        candidates.append(
            FactorCandidateSeries(
                candidate_id=root.candidate_id,
                values=tuple(values),
                unavailable_reasons=tuple(reasons),
                lookback_bars=root.lookback_bars,
            )
        )
    return FactorBatchMaterialization(
        compiled_batch_id=compiled.batch_id,
        bar_count=len(bars),
        node_series_evaluation_count=compiled.unique_node_count,
        candidates=tuple(candidates),
    )
