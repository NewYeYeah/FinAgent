from __future__ import annotations

from dataclasses import dataclass

from finagent.research.us_a1_factor_graph import (
    FactorDenominatorPolicy,
    FactorGraphSpec,
    FactorInputField,
    FactorNode,
    FactorOperator,
    FactorZeroDenominatorAction,
)
from finagent.research.us_agent_value_protocol import USAgentValueCandidateSpec
from finagent.research.us_baselines import USBaselineFeatureKind


@dataclass(frozen=True, slots=True)
class LegacyA0FactorGraphBinding:
    a0_candidate_id: str
    a0_structural_key: str
    graph: FactorGraphSpec
    representation_scope: str = "structural_representation_only_numeric_parity_deferred_to_us_a1_1"

    def __post_init__(self) -> None:
        if not self.a0_candidate_id.strip() or not self.a0_structural_key.strip():
            raise ValueError("legacy A0 graph binding identities must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "a0_candidate_id": self.a0_candidate_id,
            "a0_structural_key": self.a0_structural_key,
            "graph": self.graph.to_dict(),
            "representation_scope": self.representation_scope,
            "numeric_parity_authority": False,
        }


def _input(node_id: str, field: FactorInputField) -> FactorNode:
    return FactorNode(node_id=node_id, operator=FactorOperator.INPUT, input_field=field)


def _constant(node_id: str, value: float) -> FactorNode:
    return FactorNode(node_id=node_id, operator=FactorOperator.CONSTANT, constant_value=value)


def _unavailable_division() -> FactorDenominatorPolicy:
    return FactorDenominatorPolicy(
        epsilon=0.0,
        action=FactorZeroDenominatorAction.UNAVAILABLE,
    )


def legacy_a0_candidate_factor_graph(
    candidate: USAgentValueCandidateSpec,
) -> LegacyA0FactorGraphBinding:
    kind = candidate.kind
    window = candidate.window_bars

    if kind in {USBaselineFeatureKind.REVERSAL, USBaselineFeatureKind.MOMENTUM}:
        nodes_list = [
            _input("close", FactorInputField.CLOSE),
            FactorNode(
                node_id="return",
                operator=FactorOperator.SIMPLE_RETURN,
                inputs=("close",),
                window_bars=window,
            ),
        ]
        if kind is USBaselineFeatureKind.REVERSAL:
            nodes_list.append(
                FactorNode(node_id="output", operator=FactorOperator.NEGATE, inputs=("return",))
            )
            output = "output"
        else:
            output = "return"
        nodes = tuple(nodes_list)
    elif kind is USBaselineFeatureKind.RANGE_MEAN:
        nodes = (
            _input("high", FactorInputField.HIGH),
            _input("low", FactorInputField.LOW),
            _input("close", FactorInputField.CLOSE),
            FactorNode(
                node_id="range",
                operator=FactorOperator.SUBTRACT,
                inputs=("high", "low"),
            ),
            FactorNode(
                node_id="normalized_range",
                operator=FactorOperator.SAFE_DIVIDE,
                inputs=("range", "close"),
                denominator_policy=_unavailable_division(),
            ),
            FactorNode(
                node_id="output",
                operator=FactorOperator.ROLLING_MEAN,
                inputs=("normalized_range",),
                window_bars=window,
            ),
        )
        output = "output"
    elif kind is USBaselineFeatureKind.RETURN_VOLATILITY:
        nodes = (
            _input("close", FactorInputField.CLOSE),
            FactorNode(
                node_id="log_return",
                operator=FactorOperator.LOG_RETURN,
                inputs=("close",),
                window_bars=2,
            ),
            FactorNode(
                node_id="output",
                operator=FactorOperator.ROLLING_STD,
                inputs=("log_return",),
                window_bars=window - 1,
            ),
        )
        output = "output"
    elif kind is USBaselineFeatureKind.VOLUME_SURPRISE:
        nodes = (
            _input("volume", FactorInputField.VOLUME),
            FactorNode(
                node_id="reference_mean",
                operator=FactorOperator.ROLLING_MEAN,
                inputs=("volume",),
                window_bars=window - 1,
            ),
            FactorNode(
                node_id="prior_reference_mean",
                operator=FactorOperator.LAG,
                inputs=("reference_mean",),
                lag_bars=1,
            ),
            FactorNode(
                node_id="ratio",
                operator=FactorOperator.SAFE_DIVIDE,
                inputs=("volume", "prior_reference_mean"),
                denominator_policy=_unavailable_division(),
            ),
            _constant("one", 1.0),
            FactorNode(
                node_id="output",
                operator=FactorOperator.SUBTRACT,
                inputs=("ratio", "one"),
            ),
        )
        output = "output"
    elif kind is USBaselineFeatureKind.CLOSE_LOCATION:
        half_fallback = FactorDenominatorPolicy(
            epsilon=1e-15,
            action=FactorZeroDenominatorAction.CONSTANT,
            fallback_value=0.5,
        )
        nodes = (
            _input("high", FactorInputField.HIGH),
            _input("low", FactorInputField.LOW),
            _input("close", FactorInputField.CLOSE),
            FactorNode(
                node_id="spread",
                operator=FactorOperator.SUBTRACT,
                inputs=("high", "low"),
            ),
            FactorNode(
                node_id="close_from_low",
                operator=FactorOperator.SUBTRACT,
                inputs=("close", "low"),
            ),
            FactorNode(
                node_id="location",
                operator=FactorOperator.SAFE_DIVIDE,
                inputs=("close_from_low", "spread"),
                denominator_policy=half_fallback,
            ),
            _constant("half", 0.5),
            FactorNode(
                node_id="output",
                operator=FactorOperator.SUBTRACT,
                inputs=("location", "half"),
            ),
        )
        output = "output"
    else:
        raise ValueError(f"unsupported legacy US-A0 candidate kind: {kind.value}")

    return LegacyA0FactorGraphBinding(
        a0_candidate_id=candidate.candidate_id,
        a0_structural_key=candidate.structural_key,
        graph=FactorGraphSpec(nodes=nodes, output_node_id=output),
    )
