from __future__ import annotations

from itertools import permutations

import pytest

from finagent.research.us_a1_factor_graph import (
    FactorComplexityBudget,
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
from finagent.research.us_a1_legacy_graphs import legacy_a0_candidate_factor_graph
from finagent.research.us_agent_value_protocol import canonical_us_a0_primitive_vocabulary


def _momentum_graph(*, reverse_storage: bool = False, renamed: bool = False) -> FactorGraphSpec:
    input_id = "price-input-renamed" if renamed else "close"
    output_id = "factor-output-renamed" if renamed else "return"
    nodes = (
        FactorNode(
            node_id=input_id,
            operator=FactorOperator.INPUT,
            input_field=FactorInputField.CLOSE,
        ),
        FactorNode(
            node_id=output_id,
            operator=FactorOperator.SIMPLE_RETURN,
            inputs=(input_id,),
            window_bars=5,
        ),
    )
    if reverse_storage:
        nodes = tuple(reversed(nodes))
    return FactorGraphSpec(nodes=nodes, output_node_id=output_id)


def test_candidate_identity_is_independent_of_local_node_ids_and_storage_order() -> None:
    baseline = validate_factor_graph(_momentum_graph())
    reordered = validate_factor_graph(_momentum_graph(reverse_storage=True, renamed=True))

    assert baseline.valid and reordered.valid
    assert baseline.canonicalization is not None
    assert reordered.canonicalization is not None
    assert baseline.proposal_graph_id != reordered.proposal_graph_id
    assert baseline.canonicalization.candidate_id == reordered.canonicalization.candidate_id
    assert baseline.canonicalization.root_digest == reordered.canonicalization.root_digest
    assert baseline.canonicalization.lookback_bars == 5
    assert baseline.canonicalization.required_input_fields == ("close",)


def test_commutative_add_is_canonical_across_operand_order() -> None:
    nodes = (
        FactorNode(
            node_id="close",
            operator=FactorOperator.INPUT,
            input_field=FactorInputField.CLOSE,
        ),
        FactorNode(
            node_id="ret",
            operator=FactorOperator.SIMPLE_RETURN,
            inputs=("close",),
            window_bars=2,
        ),
        FactorNode(
            node_id="constant",
            operator=FactorOperator.CONSTANT,
            constant_value=0.25,
        ),
    )
    candidate_ids: set[str] = set()
    reorder_counts: list[int] = []
    for left, right in permutations(("ret", "constant")):
        graph = FactorGraphSpec(
            nodes=nodes
            + (
                FactorNode(
                    node_id="output",
                    operator=FactorOperator.ADD,
                    inputs=(left, right),
                ),
            ),
            output_node_id="output",
        )
        evidence = validate_factor_graph(graph)
        assert evidence.valid
        assert evidence.canonicalization is not None
        candidate_ids.add(evidence.canonicalization.candidate_id)
        reorder_counts.append(evidence.canonicalization.commutative_reorder_count)

    assert len(candidate_ids) == 1
    assert sorted(reorder_counts) == [0, 1]


def test_validator_fails_closed_on_cycle_unused_nodes_and_redundant_subexpressions() -> None:
    cycle = FactorGraphSpec(
        nodes=(
            FactorNode(node_id="a", operator=FactorOperator.NEGATE, inputs=("b",)),
            FactorNode(node_id="b", operator=FactorOperator.NEGATE, inputs=("a",)),
        ),
        output_node_id="a",
    )
    cycle_evidence = validate_factor_graph(cycle)
    assert not cycle_evidence.valid
    assert "graph_cycle_detected" in cycle_evidence.blockers

    redundant = FactorGraphSpec(
        nodes=(
            FactorNode(
                node_id="close-a",
                operator=FactorOperator.INPUT,
                input_field=FactorInputField.CLOSE,
            ),
            FactorNode(
                node_id="close-b",
                operator=FactorOperator.INPUT,
                input_field=FactorInputField.CLOSE,
            ),
            FactorNode(
                node_id="ret-a",
                operator=FactorOperator.SIMPLE_RETURN,
                inputs=("close-a",),
                window_bars=2,
            ),
            FactorNode(
                node_id="ret-b",
                operator=FactorOperator.SIMPLE_RETURN,
                inputs=("close-b",),
                window_bars=3,
            ),
            FactorNode(
                node_id="output",
                operator=FactorOperator.ADD,
                inputs=("ret-a", "ret-b"),
            ),
        ),
        output_node_id="output",
    )
    redundant_evidence = validate_factor_graph(redundant)
    assert not redundant_evidence.valid
    assert any(
        item.startswith("duplicate_subexpression:close-b:close-a")
        for item in redundant_evidence.blockers
    )

    unused = FactorGraphSpec(
        nodes=_momentum_graph().nodes
        + (
            FactorNode(
                node_id="unused",
                operator=FactorOperator.CONSTANT,
                constant_value=1.0,
            ),
        ),
        output_node_id="return",
    )
    unused_evidence = validate_factor_graph(unused)
    assert not unused_evidence.valid
    assert "unused_node:unused" in unused_evidence.blockers


def test_malformed_window_and_lag_nodes_return_blockers_instead_of_assertions() -> None:
    malformed_return = FactorGraphSpec(
        nodes=(
            FactorNode(
                node_id="close",
                operator=FactorOperator.INPUT,
                input_field=FactorInputField.CLOSE,
            ),
            FactorNode(
                node_id="return",
                operator=FactorOperator.SIMPLE_RETURN,
                inputs=("close",),
            ),
        ),
        output_node_id="return",
    )
    return_evidence = validate_factor_graph(malformed_return)
    assert not return_evidence.valid
    assert "window_bars_required:return" in return_evidence.blockers

    malformed_lag = FactorGraphSpec(
        nodes=(
            FactorNode(
                node_id="close",
                operator=FactorOperator.INPUT,
                input_field=FactorInputField.CLOSE,
            ),
            FactorNode(node_id="lag", operator=FactorOperator.LAG, inputs=("close",)),
        ),
        output_node_id="lag",
    )
    lag_evidence = validate_factor_graph(malformed_lag)
    assert not lag_evidence.valid
    assert "lag_bars_required:lag" in lag_evidence.blockers


def test_safe_divide_requires_explicit_zero_denominator_policy() -> None:
    graph = FactorGraphSpec(
        nodes=(
            FactorNode(
                node_id="high",
                operator=FactorOperator.INPUT,
                input_field=FactorInputField.HIGH,
            ),
            FactorNode(
                node_id="low",
                operator=FactorOperator.INPUT,
                input_field=FactorInputField.LOW,
            ),
            FactorNode(
                node_id="spread",
                operator=FactorOperator.SUBTRACT,
                inputs=("high", "low"),
            ),
            FactorNode(
                node_id="ratio",
                operator=FactorOperator.SAFE_DIVIDE,
                inputs=("spread", "high"),
            ),
        ),
        output_node_id="ratio",
    )
    evidence = validate_factor_graph(graph)
    assert not evidence.valid
    assert "denominator_policy_required:ratio" in evidence.blockers


def test_regime_gate_requires_an_explicit_policy_binding() -> None:
    nodes = _momentum_graph().nodes + (
        FactorNode(
            node_id="gated",
            operator=FactorOperator.REGIME_GATE,
            inputs=("return",),
            regime_labels=("HIGH_VOL",),
        ),
    )
    rejected = validate_factor_graph(FactorGraphSpec(nodes=nodes, output_node_id="gated"))
    assert not rejected.valid
    assert "regime_policy_binding_required:gated" in rejected.blockers

    accepted = validate_factor_graph(
        FactorGraphSpec(
            nodes=nodes,
            output_node_id="gated",
            regime_policy_id="us-r2-regime-policy-test",
        )
    )
    assert accepted.valid


def test_complexity_budget_is_checked_after_linear_graph_analysis() -> None:
    graph = FactorGraphSpec(
        nodes=_momentum_graph().nodes,
        output_node_id="return",
        budget=FactorComplexityBudget(
            max_nodes=2,
            max_edges=1,
            max_depth=1,
            max_window_bars=26,
            max_lookback_bars=4,
            max_regime_gates=0,
        ),
    )
    evidence = validate_factor_graph(graph)
    assert not evidence.valid
    assert "depth_budget_exceeded:return:2>1" in evidence.blockers
    assert "lookback_budget_exceeded:return:5>4" in evidence.blockers


def test_all_62_a0_candidates_have_valid_unique_a1_structural_representations() -> None:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    candidates = vocabulary.all_candidates()
    assert len(candidates) == 62

    canonical_ids: set[str] = set()
    for candidate in candidates:
        binding = legacy_a0_candidate_factor_graph(candidate)
        evidence = validate_factor_graph(binding.graph)
        assert evidence.valid, (candidate.structural_key, evidence.blockers)
        assert evidence.canonicalization is not None
        assert evidence.canonicalization.lookback_bars == candidate.window_bars
        assert evidence.canonicalization.required_input_fields == tuple(sorted(candidate.input_fields))
        canonical_ids.add(evidence.canonicalization.candidate_id)
        assert binding.to_dict()["numeric_parity_authority"] is False

    assert len(canonical_ids) == 62


def test_hypothesis_contract_is_structured_non_executable_metadata() -> None:
    evidence = validate_factor_graph(_momentum_graph())
    assert evidence.canonicalization is not None
    candidate_id = evidence.canonicalization.candidate_id
    hypothesis = FactorHypothesisSpec(
        candidate_id=candidate_id,
        summary="Short-horizon completed-bar returns may continue when order flow persists.",
        mechanism_category=FactorMechanismCategory.MOMENTUM,
        expected_direction=FactorExpectedDirection.POSITIVE,
        expected_regime_scope=("NORMAL", "HIGH_VOL"),
        required_input_fields=(FactorInputField.CLOSE,),
        falsification=FactorFalsificationSpec(
            criteria=(
                "Reject if independently evaluated out-of-sample sign stability is absent.",
                "Reject if the reviewed multiplicity-aware research gate fails.",
            ),
            invalidating_conditions=("Insufficient admitted regime coverage.",),
        ),
    )

    payload = hypothesis.to_dict()
    assert payload["candidate_id"] == candidate_id
    assert payload["stored_reasoning_scope"].endswith("no_chain_of_thought")
    assert payload["financial_data_access_authority"] is False
    assert payload["execution_authority"] is False


def test_graph_constructor_rejects_cross_session_or_non_raw_semantics() -> None:
    with pytest.raises(ValueError, match="same-session"):
        FactorGraphSpec(
            nodes=_momentum_graph().nodes,
            output_node_id="return",
            same_session_only=False,
        )
    with pytest.raises(ValueError, match="RAW/available_at"):
        FactorGraphSpec(
            nodes=_momentum_graph().nodes,
            output_node_id="return",
            price_basis="ADJUSTED",
        )


def test_division_fallback_policy_requires_finite_explicit_value() -> None:
    with pytest.raises(ValueError, match="fallback_value"):
        FactorDenominatorPolicy(
            epsilon=1e-15,
            action=FactorZeroDenominatorAction.CONSTANT,
        )
