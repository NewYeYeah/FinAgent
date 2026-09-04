from __future__ import annotations

import hashlib
import heapq
import json
from collections import defaultdict
from dataclasses import dataclass

from finagent.research.us_a1_factor_graph import (
    FactorCanonicalizationEvidence,
    FactorGraphSpec,
    FactorGraphValidationEvidence,
    FactorInputField,
    FactorNode,
    FactorOperator,
    FactorScope,
    FactorSemanticType,
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


_INPUT_TYPES: dict[FactorInputField, FactorSemanticType] = {
    FactorInputField.OPEN: FactorSemanticType.PRICE,
    FactorInputField.HIGH: FactorSemanticType.PRICE,
    FactorInputField.LOW: FactorSemanticType.PRICE,
    FactorInputField.CLOSE: FactorSemanticType.PRICE,
    FactorInputField.VOLUME: FactorSemanticType.VOLUME,
}
_UNARY_OPERATORS = frozenset(
    {
        FactorOperator.LAG,
        FactorOperator.SIMPLE_RETURN,
        FactorOperator.LOG_RETURN,
        FactorOperator.ROLLING_MEAN,
        FactorOperator.ROLLING_STD,
        FactorOperator.ROLLING_MIN,
        FactorOperator.ROLLING_MAX,
        FactorOperator.NEGATE,
        FactorOperator.CROSS_SECTION_RANK,
        FactorOperator.CROSS_SECTION_ZSCORE,
        FactorOperator.CLIP,
        FactorOperator.WINSORIZE,
        FactorOperator.REGIME_GATE,
    }
)
_BINARY_OPERATORS = frozenset(
    {
        FactorOperator.ADD,
        FactorOperator.SUBTRACT,
        FactorOperator.MULTIPLY,
        FactorOperator.SAFE_DIVIDE,
    }
)
_SUPPORTED_OPERATORS = (
    frozenset({FactorOperator.INPUT, FactorOperator.CONSTANT})
    | _UNARY_OPERATORS
    | _BINARY_OPERATORS
)
_COMMUTATIVE_OPERATORS = frozenset({FactorOperator.ADD, FactorOperator.MULTIPLY})
_WINDOW_OPERATORS = frozenset(
    {
        FactorOperator.SIMPLE_RETURN,
        FactorOperator.LOG_RETURN,
        FactorOperator.ROLLING_MEAN,
        FactorOperator.ROLLING_STD,
        FactorOperator.ROLLING_MIN,
        FactorOperator.ROLLING_MAX,
    }
)


@dataclass(frozen=True, slots=True)
class _NodeState:
    semantic_type: FactorSemanticType
    scope: FactorScope
    lookback_bars: int
    depth: int
    digest: str
    required_inputs: frozenset[FactorInputField]


def _add(blockers: list[str], message: str) -> None:
    if message not in blockers:
        blockers.append(message)


def _validate_parameter_surface(node: FactorNode, blockers: list[str]) -> None:
    operator = node.operator
    if operator not in _SUPPORTED_OPERATORS:
        _add(blockers, f"unsupported_operator:{node.node_id}:{operator.value}")
        return
    arity = 0 if operator in {FactorOperator.INPUT, FactorOperator.CONSTANT} else (
        1 if operator in _UNARY_OPERATORS else 2
    )
    if len(node.inputs) != arity:
        _add(blockers, f"arity_mismatch:{node.node_id}:{len(node.inputs)}!={arity}")

    if operator is FactorOperator.INPUT:
        if node.input_field is None:
            _add(blockers, f"input_field_required:{node.node_id}")
    elif node.input_field is not None:
        _add(blockers, f"extraneous_input_field:{node.node_id}")

    if operator is FactorOperator.CONSTANT:
        if node.constant_value is None:
            _add(blockers, f"constant_value_required:{node.node_id}")
    elif node.constant_value is not None:
        _add(blockers, f"extraneous_constant_value:{node.node_id}")

    if operator in _WINDOW_OPERATORS:
        if node.window_bars is None or node.window_bars < 1:
            _add(blockers, f"window_bars_required:{node.node_id}")
        elif operator in {FactorOperator.SIMPLE_RETURN, FactorOperator.LOG_RETURN} and node.window_bars < 2:
            _add(blockers, f"return_window_requires_two_bars:{node.node_id}")
    elif node.window_bars is not None:
        _add(blockers, f"extraneous_window_bars:{node.node_id}")

    if operator is FactorOperator.LAG:
        if node.lag_bars is None or node.lag_bars < 1:
            _add(blockers, f"lag_bars_required:{node.node_id}")
    elif node.lag_bars is not None:
        _add(blockers, f"extraneous_lag_bars:{node.node_id}")

    if operator is FactorOperator.SAFE_DIVIDE:
        if node.denominator_policy is None:
            _add(blockers, f"denominator_policy_required:{node.node_id}")
    elif node.denominator_policy is not None:
        _add(blockers, f"extraneous_denominator_policy:{node.node_id}")

    if operator is FactorOperator.CLIP:
        if node.lower_bound is None or node.upper_bound is None:
            _add(blockers, f"clip_bounds_required:{node.node_id}")
        elif node.lower_bound >= node.upper_bound:
            _add(blockers, f"clip_bounds_invalid:{node.node_id}")
    elif node.lower_bound is not None or node.upper_bound is not None:
        _add(blockers, f"extraneous_clip_bounds:{node.node_id}")

    if operator is FactorOperator.WINSORIZE:
        if node.lower_quantile is None or node.upper_quantile is None:
            _add(blockers, f"winsorize_quantiles_required:{node.node_id}")
        elif not (0.0 <= node.lower_quantile < node.upper_quantile <= 1.0):
            _add(blockers, f"winsorize_quantiles_invalid:{node.node_id}")
    elif node.lower_quantile is not None or node.upper_quantile is not None:
        _add(blockers, f"extraneous_winsorize_quantiles:{node.node_id}")

    if operator is FactorOperator.REGIME_GATE:
        if not node.regime_labels:
            _add(blockers, f"regime_labels_required:{node.node_id}")
    elif node.regime_labels:
        _add(blockers, f"extraneous_regime_labels:{node.node_id}")


def _canonical_parameters(node: FactorNode) -> dict[str, object]:
    operator = node.operator
    if operator is FactorOperator.INPUT:
        return {"input_field": node.input_field.value if node.input_field is not None else None}
    if operator is FactorOperator.CONSTANT:
        return {"constant_value": node.constant_value}
    if operator in _WINDOW_OPERATORS:
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


def _multiply_type(
    left: FactorSemanticType,
    right: FactorSemanticType,
) -> FactorSemanticType | None:
    if left is FactorSemanticType.DIMENSIONLESS:
        return right
    if right is FactorSemanticType.DIMENSIONLESS:
        return left
    return None


def _divide_type(
    numerator: FactorSemanticType,
    denominator: FactorSemanticType,
) -> FactorSemanticType | None:
    if numerator is denominator:
        return FactorSemanticType.DIMENSIONLESS
    if denominator is FactorSemanticType.DIMENSIONLESS:
        return numerator
    return None


def _infer_node(
    node: FactorNode,
    child_states: tuple[_NodeState, ...],
    graph: FactorGraphSpec,
    blockers: list[str],
) -> tuple[_NodeState | None, bool]:
    operator = node.operator
    reordered = False
    if operator is FactorOperator.INPUT:
        if node.input_field is None:
            return None, reordered
        semantic = _INPUT_TYPES[node.input_field]
        scope = FactorScope.TIME_SERIES
        lookback = 1
        depth = 1
        required = frozenset({node.input_field})
    elif operator is FactorOperator.CONSTANT:
        if node.constant_value is None:
            return None, reordered
        semantic = FactorSemanticType.DIMENSIONLESS
        scope = FactorScope.TIME_SERIES
        lookback = 1
        depth = 1
        required = frozenset()
    else:
        expected_arity = 1 if operator in _UNARY_OPERATORS else 2
        if operator not in _SUPPORTED_OPERATORS or len(child_states) != expected_arity:
            return None, reordered
        required = frozenset().union(*(item.required_inputs for item in child_states))
        depth = 1 + max(item.depth for item in child_states)
        lookback = max(item.lookback_bars for item in child_states)

        if operator is FactorOperator.LAG:
            if node.lag_bars is None or node.lag_bars < 1:
                return None, reordered
            child = child_states[0]
            semantic, scope = child.semantic_type, child.scope
            lookback = child.lookback_bars + node.lag_bars
        elif operator in {FactorOperator.SIMPLE_RETURN, FactorOperator.LOG_RETURN}:
            if node.window_bars is None or node.window_bars < 2:
                return None, reordered
            child = child_states[0]
            if child.semantic_type is not FactorSemanticType.PRICE:
                _add(blockers, f"return_requires_price:{node.node_id}")
                return None, reordered
            if child.scope is not FactorScope.TIME_SERIES:
                _add(blockers, f"return_requires_time_series:{node.node_id}")
                return None, reordered
            semantic, scope = FactorSemanticType.DIMENSIONLESS, FactorScope.TIME_SERIES
            lookback = child.lookback_bars + node.window_bars - 1
        elif operator in {
            FactorOperator.ROLLING_MEAN,
            FactorOperator.ROLLING_STD,
            FactorOperator.ROLLING_MIN,
            FactorOperator.ROLLING_MAX,
        }:
            if node.window_bars is None or node.window_bars < 1:
                return None, reordered
            child = child_states[0]
            semantic, scope = child.semantic_type, child.scope
            lookback = child.lookback_bars + node.window_bars - 1
        elif operator in {FactorOperator.ADD, FactorOperator.SUBTRACT}:
            left, right = child_states
            if left.semantic_type is not right.semantic_type:
                _add(blockers, f"add_subtract_type_mismatch:{node.node_id}")
                return None, reordered
            if left.scope is not right.scope:
                _add(blockers, f"add_subtract_scope_mismatch:{node.node_id}")
                return None, reordered
            semantic, scope = left.semantic_type, left.scope
        elif operator is FactorOperator.MULTIPLY:
            left, right = child_states
            semantic = _multiply_type(left.semantic_type, right.semantic_type)
            if semantic is None:
                _add(blockers, f"multiply_units_unsupported:{node.node_id}")
                return None, reordered
            if left.scope is not right.scope:
                _add(blockers, f"multiply_scope_mismatch:{node.node_id}")
                return None, reordered
            scope = left.scope
        elif operator is FactorOperator.SAFE_DIVIDE:
            left, right = child_states
            if node.denominator_policy is None:
                return None, reordered
            semantic = _divide_type(left.semantic_type, right.semantic_type)
            if semantic is None:
                _add(blockers, f"divide_units_unsupported:{node.node_id}")
                return None, reordered
            if left.scope is not right.scope:
                _add(blockers, f"divide_scope_mismatch:{node.node_id}")
                return None, reordered
            scope = left.scope
        elif operator is FactorOperator.NEGATE:
            child = child_states[0]
            semantic, scope = child.semantic_type, child.scope
        elif operator in {FactorOperator.CROSS_SECTION_RANK, FactorOperator.CROSS_SECTION_ZSCORE}:
            child = child_states[0]
            semantic, scope = FactorSemanticType.DIMENSIONLESS, FactorScope.CROSS_SECTIONAL
        elif operator is FactorOperator.CLIP:
            if node.lower_bound is None or node.upper_bound is None:
                return None, reordered
            child = child_states[0]
            semantic, scope = child.semantic_type, child.scope
        elif operator is FactorOperator.WINSORIZE:
            if node.lower_quantile is None or node.upper_quantile is None:
                return None, reordered
            child = child_states[0]
            semantic, scope = child.semantic_type, FactorScope.CROSS_SECTIONAL
        elif operator is FactorOperator.REGIME_GATE:
            if not node.regime_labels:
                return None, reordered
            child = child_states[0]
            if graph.regime_policy_id is None:
                _add(blockers, f"regime_policy_binding_required:{node.node_id}")
                return None, reordered
            semantic, scope = child.semantic_type, child.scope
        else:
            return None, reordered

    child_digests = [item.digest for item in child_states]
    if operator in _COMMUTATIVE_OPERATORS:
        sorted_digests = sorted(child_digests)
        reordered = child_digests != sorted_digests
        child_digests = sorted_digests
    digest = _canonical_hash(
        {
            "operator": operator.value,
            "inputs": child_digests,
            "parameters": _canonical_parameters(node),
        },
        prefix="us-a1-factor-node",
    )
    return (
        _NodeState(
            semantic_type=semantic,
            scope=scope,
            lookback_bars=lookback,
            depth=depth,
            digest=digest,
            required_inputs=required,
        ),
        reordered,
    )


def validate_factor_graph(graph: FactorGraphSpec) -> FactorGraphValidationEvidence:
    blockers: list[str] = []
    nodes = graph.nodes
    node_count = len(nodes)
    edge_count = sum(len(item.inputs) for item in nodes)
    if node_count == 0:
        _add(blockers, "graph_has_no_nodes")
    if node_count > graph.budget.max_nodes:
        _add(blockers, f"node_budget_exceeded:{node_count}>{graph.budget.max_nodes}")
    if edge_count > graph.budget.max_edges:
        _add(blockers, f"edge_budget_exceeded:{edge_count}>{graph.budget.max_edges}")

    ids = tuple(item.node_id for item in nodes)
    if len(ids) != len(set(ids)):
        _add(blockers, "duplicate_node_id")
    node_by_id = {item.node_id: item for item in nodes}
    if graph.output_node_id not in node_by_id:
        _add(blockers, f"output_node_missing:{graph.output_node_id}")

    for node in nodes:
        _validate_parameter_surface(node, blockers)
        if node.window_bars is not None and node.window_bars > graph.budget.max_window_bars:
            _add(
                blockers,
                f"window_budget_exceeded:{node.node_id}:{node.window_bars}>{graph.budget.max_window_bars}",
            )
        for reference in node.inputs:
            if reference not in node_by_id:
                _add(blockers, f"missing_input_node:{node.node_id}:{reference}")

    reachable: set[str] = set()
    if graph.output_node_id in node_by_id:
        stack = [graph.output_node_id]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            stack.extend(
                reference for reference in node_by_id[node_id].inputs if reference in node_by_id
            )
    for node_id in sorted(set(node_by_id).difference(reachable)):
        _add(blockers, f"unused_node:{node_id}")

    indegree: dict[str, int] = {node_id: 0 for node_id in node_by_id}
    children: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        if node.node_id not in indegree:
            continue
        for reference in node.inputs:
            if reference not in node_by_id:
                continue
            indegree[node.node_id] += 1
            children[reference].append(node.node_id)
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    topological: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        topological.append(node_id)
        for child in children.get(node_id, ()):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(topological) != len(node_by_id):
        _add(blockers, "graph_cycle_detected")

    states: dict[str, _NodeState] = {}
    digest_owner: dict[str, str] = {}
    reorder_count = 0
    regime_gate_count = 0
    if "graph_cycle_detected" not in blockers and len(ids) == len(set(ids)):
        for node_id in topological:
            node = node_by_id[node_id]
            child_states: list[_NodeState] = []
            for reference in node.inputs:
                state = states.get(reference)
                if state is None:
                    child_states = []
                    break
                child_states.append(state)
            if node.inputs and not child_states:
                continue
            state, reordered = _infer_node(node, tuple(child_states), graph, blockers)
            if state is None:
                continue
            states[node_id] = state
            reorder_count += int(reordered)
            if node.operator is FactorOperator.REGIME_GATE:
                regime_gate_count += 1
            owner = digest_owner.get(state.digest)
            if owner is not None:
                _add(blockers, f"duplicate_subexpression:{node_id}:{owner}")
            else:
                digest_owner[state.digest] = node_id
            if state.depth > graph.budget.max_depth:
                _add(
                    blockers,
                    f"depth_budget_exceeded:{node_id}:{state.depth}>{graph.budget.max_depth}",
                )
            if state.lookback_bars > graph.budget.max_lookback_bars:
                _add(
                    blockers,
                    "lookback_budget_exceeded:"
                    f"{node_id}:{state.lookback_bars}>{graph.budget.max_lookback_bars}",
                )
    if regime_gate_count > graph.budget.max_regime_gates:
        _add(
            blockers,
            f"regime_gate_budget_exceeded:{regime_gate_count}>{graph.budget.max_regime_gates}",
        )

    output_state = states.get(graph.output_node_id)
    if output_state is not None and output_state.semantic_type is not FactorSemanticType.DIMENSIONLESS:
        _add(blockers, f"factor_output_must_be_dimensionless:{output_state.semantic_type.value}")

    canonicalization: FactorCanonicalizationEvidence | None = None
    if not blockers and output_state is not None:
        candidate_id = _canonical_hash(
            {
                "root_digest": output_state.digest,
                "signal_interval": graph.signal_interval,
                "same_session_only": graph.same_session_only,
                "require_complete_bars": graph.require_complete_bars,
                "price_basis": graph.price_basis,
                "availability_policy": graph.availability_policy,
                "regime_policy_id": graph.regime_policy_id,
            },
            prefix="us-a1-factor-candidate",
        )
        canonicalization = FactorCanonicalizationEvidence(
            proposal_graph_id=graph.proposal_graph_id,
            candidate_id=candidate_id,
            root_digest=output_state.digest,
            canonical_node_digests=tuple(sorted(state.digest for state in states.values())),
            required_input_fields=tuple(sorted(item.value for item in output_state.required_inputs)),
            inferred_semantic_type=output_state.semantic_type,
            inferred_scope=output_state.scope,
            lookback_bars=output_state.lookback_bars,
            depth=output_state.depth,
            commutative_reorder_count=reorder_count,
        )
    return FactorGraphValidationEvidence(
        proposal_graph_id=graph.proposal_graph_id,
        valid=not blockers,
        node_count=node_count,
        edge_count=edge_count,
        reachable_node_count=len(reachable),
        blockers=tuple(blockers),
        canonicalization=canonicalization,
    )
