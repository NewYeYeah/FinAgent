from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

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


def _canonical_hash(payload: object, *, prefix: str) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(rendered).hexdigest()[:24]}"


class AlphaImplementationReadiness(StrEnum):
    EXECUTABLE_OHLCV_PANEL = "EXECUTABLE_OHLCV_PANEL"
    REQUIRES_SESSION_ANCHOR_AGGREGATE = "REQUIRES_SESSION_ANCHOR_AGGREGATE"
    REQUIRES_CROSS_SESSION_DATA = "REQUIRES_CROSS_SESSION_DATA"
    REQUIRES_ORDER_FLOW_DATA = "REQUIRES_ORDER_FLOW_DATA"


@dataclass(frozen=True, slots=True)
class FrontierAlphaStrategySpec:
    slug: str
    title: str
    mechanism: str
    readiness: AlphaImplementationReadiness
    required_input_fields: tuple[str, ...]
    required_operators: tuple[str, ...]
    research_horizon: str
    primary_references: tuple[str, ...]
    falsification_criteria: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: str = "finagent.us-r3-frontier-alpha-strategy.v1"

    def __post_init__(self) -> None:
        for field_name in ("slug", "title", "mechanism", "research_horizon"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not self.primary_references or not self.falsification_criteria:
            raise ValueError("frontier strategy requires references and falsification criteria")

    @property
    def strategy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r3-alpha-strategy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "slug": self.slug,
            "title": self.title,
            "mechanism": self.mechanism,
            "readiness": self.readiness.value,
            "required_input_fields": list(self.required_input_fields),
            "required_operators": list(self.required_operators),
            "research_horizon": self.research_horizon,
            "primary_references": list(self.primary_references),
            "falsification_criteria": list(self.falsification_criteria),
            "limitations": list(self.limitations),
            "signal_interval": "15m",
            "same_session_only": True,
            "alpha_authority": False,
            "execution_authority": False,
        }
        if include_id:
            payload["strategy_id"] = self.strategy_id
        return payload


@dataclass(frozen=True, slots=True)
class FrontierAlphaCandidate:
    strategy: FrontierAlphaStrategySpec
    graph: FactorGraphSpec
    hypothesis: FactorHypothesisSpec
    schema_version: str = "finagent.us-r3-frontier-alpha-candidate.v1"

    def __post_init__(self) -> None:
        evidence = validate_factor_graph(self.graph)
        if not evidence.valid or evidence.canonicalization is None:
            raise ValueError(f"frontier candidate graph is invalid: {evidence.blockers}")
        if evidence.canonicalization.candidate_id != self.hypothesis.candidate_id:
            raise ValueError("frontier hypothesis candidate_id does not match graph")
        required = tuple(item.value for item in self.hypothesis.required_input_fields)
        if tuple(sorted(required)) != evidence.canonicalization.required_input_fields:
            raise ValueError("frontier hypothesis required inputs do not match graph")

    @property
    def candidate_id(self) -> str:
        return cast(str, self.hypothesis.candidate_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy": self.strategy.to_dict(),
            "graph": self.graph.to_dict(),
            "hypothesis": self.hypothesis.to_dict(),
            "candidate_id": self.candidate_id,
            "financial_performance_evaluated": False,
        }


_UNAVAILABLE = FactorDenominatorPolicy(
    epsilon=1e-12,
    action=FactorZeroDenominatorAction.UNAVAILABLE,
)


def _hypothesis(
    graph: FactorGraphSpec,
    *,
    summary: str,
    mechanism: FactorMechanismCategory,
    direction: FactorExpectedDirection,
    criteria: tuple[str, ...],
    invalidating_conditions: tuple[str, ...],
) -> FactorHypothesisSpec:
    evidence = validate_factor_graph(graph)
    if not evidence.valid or evidence.canonicalization is None:
        raise ValueError(f"cannot describe invalid frontier graph: {evidence.blockers}")
    return FactorHypothesisSpec(
        candidate_id=evidence.canonicalization.candidate_id,
        summary=summary,
        mechanism_category=mechanism,
        expected_direction=direction,
        expected_regime_scope=("all_preregistered_regimes",),
        required_input_fields=tuple(
            FactorInputField(item) for item in evidence.canonicalization.required_input_fields
        ),
        falsification=FactorFalsificationSpec(
            criteria=criteria,
            invalidating_conditions=invalidating_conditions,
        ),
    )


def volatility_scaled_momentum_graph() -> FactorGraphSpec:
    return FactorGraphSpec(
        nodes=(
            FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
            FactorNode("fast_return", FactorOperator.SIMPLE_RETURN, ("close",), window_bars=4),
            FactorNode("one_bar_return", FactorOperator.SIMPLE_RETURN, ("close",), window_bars=2),
            FactorNode("local_vol", FactorOperator.ROLLING_STD, ("one_bar_return",), window_bars=8),
            FactorNode(
                "scaled",
                FactorOperator.SAFE_DIVIDE,
                ("fast_return", "local_vol"),
                denominator_policy=_UNAVAILABLE,
            ),
            FactorNode(
                "winsorized",
                FactorOperator.WINSORIZE,
                ("scaled",),
                lower_quantile=0.05,
                upper_quantile=0.95,
            ),
            FactorNode("signal", FactorOperator.CROSS_SECTION_ZSCORE, ("winsorized",)),
        ),
        output_node_id="signal",
    )


def volume_conditioned_reversal_graph() -> FactorGraphSpec:
    return FactorGraphSpec(
        nodes=(
            FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
            FactorNode("volume", FactorOperator.INPUT, input_field=FactorInputField.VOLUME),
            FactorNode("return", FactorOperator.SIMPLE_RETURN, ("close",), window_bars=3),
            FactorNode("reversal", FactorOperator.NEGATE, ("return",)),
            FactorNode("mean_volume", FactorOperator.ROLLING_MEAN, ("volume",), window_bars=8),
            FactorNode(
                "relative_volume",
                FactorOperator.SAFE_DIVIDE,
                ("volume", "mean_volume"),
                denominator_policy=_UNAVAILABLE,
            ),
            FactorNode(
                "pressure_reversal",
                FactorOperator.MULTIPLY,
                ("reversal", "relative_volume"),
            ),
            FactorNode(
                "winsorized",
                FactorOperator.WINSORIZE,
                ("pressure_reversal",),
                lower_quantile=0.05,
                upper_quantile=0.95,
            ),
            FactorNode("signal", FactorOperator.CROSS_SECTION_RANK, ("winsorized",)),
        ),
        output_node_id="signal",
    )


def volume_confirmed_range_location_graph() -> FactorGraphSpec:
    return FactorGraphSpec(
        nodes=(
            FactorNode("high", FactorOperator.INPUT, input_field=FactorInputField.HIGH),
            FactorNode("low", FactorOperator.INPUT, input_field=FactorInputField.LOW),
            FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
            FactorNode("volume", FactorOperator.INPUT, input_field=FactorInputField.VOLUME),
            FactorNode("range_high", FactorOperator.ROLLING_MAX, ("high",), window_bars=8),
            FactorNode("range_low", FactorOperator.ROLLING_MIN, ("low",), window_bars=8),
            FactorNode("range_width", FactorOperator.SUBTRACT, ("range_high", "range_low")),
            FactorNode("above_low", FactorOperator.SUBTRACT, ("close", "range_low")),
            FactorNode(
                "range_location",
                FactorOperator.SAFE_DIVIDE,
                ("above_low", "range_width"),
                denominator_policy=_UNAVAILABLE,
            ),
            FactorNode("midpoint", FactorOperator.CONSTANT, constant_value=0.5),
            FactorNode(
                "centered_location",
                FactorOperator.SUBTRACT,
                ("range_location", "midpoint"),
            ),
            FactorNode("mean_volume", FactorOperator.ROLLING_MEAN, ("volume",), window_bars=8),
            FactorNode(
                "relative_volume",
                FactorOperator.SAFE_DIVIDE,
                ("volume", "mean_volume"),
                denominator_policy=_UNAVAILABLE,
            ),
            FactorNode(
                "confirmed_location",
                FactorOperator.MULTIPLY,
                ("centered_location", "relative_volume"),
            ),
            FactorNode(
                "winsorized",
                FactorOperator.WINSORIZE,
                ("confirmed_location",),
                lower_quantile=0.05,
                upper_quantile=0.95,
            ),
            FactorNode("signal", FactorOperator.CROSS_SECTION_ZSCORE, ("winsorized",)),
        ),
        output_node_id="signal",
    )


def _strategy_specs() -> tuple[FrontierAlphaStrategySpec, ...]:
    machine_learning_reference = "https://doi.org/10.1093/rfs/hhaa009"
    intraday_momentum_reference = "https://doi.org/10.1016/j.jfineco.2018.06.011"
    volatility_management_reference = "https://doi.org/10.1111/jofi.12513"
    private_information_reference = "https://doi.org/10.1093/rapstu/raaf009"
    intraday_seasonality_reference = "https://www.nber.org/papers/w30366"
    day_night_reference = "https://doi.org/10.1093/rfs/hhag036"
    return (
        FrontierAlphaStrategySpec(
            slug="volatility-scaled-cross-sectional-momentum",
            title="Volatility-scaled cross-sectional intraday momentum",
            mechanism="Nonlinear interaction of price trend and local realized volatility.",
            readiness=AlphaImplementationReadiness.EXECUTABLE_OHLCV_PANEL,
            required_input_fields=("close",),
            required_operators=(
                "SIMPLE_RETURN",
                "ROLLING_STD",
                "SAFE_DIVIDE",
                "WINSORIZE",
                "CROSS_SECTION_ZSCORE",
            ),
            research_horizon="same-session 60 trading minutes",
            primary_references=(machine_learning_reference, volatility_management_reference),
            falsification_criteria=("Fails frozen fold-regime RankIC and economic gates.",),
            limitations=(
                "Volatility scaling is a hypothesis transfer, not a claimed intraday replication.",
            ),
        ),
        FrontierAlphaStrategySpec(
            slug="volume-conditioned-liquidity-reversal",
            title="Volume-conditioned cross-sectional liquidity reversal",
            mechanism="Temporary price pressure should reverse more strongly when return and relative volume jointly spike.",
            readiness=AlphaImplementationReadiness.EXECUTABLE_OHLCV_PANEL,
            required_input_fields=("close", "volume"),
            required_operators=(
                "SIMPLE_RETURN",
                "NEGATE",
                "ROLLING_MEAN",
                "SAFE_DIVIDE",
                "MULTIPLY",
                "WINSORIZE",
                "CROSS_SECTION_RANK",
            ),
            research_horizon="same-session 60 trading minutes",
            primary_references=(private_information_reference, machine_learning_reference),
            falsification_criteria=(
                "Reversal is absent after frozen costs or unstable across regimes.",
            ),
            limitations=(
                "OHLCV relative volume is not order imbalance or private-information measurement.",
            ),
        ),
        FrontierAlphaStrategySpec(
            slug="volume-confirmed-range-location",
            title="Volume-confirmed range-location continuation",
            mechanism="Closing near a recent intraday range edge with elevated activity may identify persistent information incorporation.",
            readiness=AlphaImplementationReadiness.EXECUTABLE_OHLCV_PANEL,
            required_input_fields=("high", "low", "close", "volume"),
            required_operators=(
                "ROLLING_MIN",
                "ROLLING_MAX",
                "ROLLING_MEAN",
                "SAFE_DIVIDE",
                "MULTIPLY",
                "WINSORIZE",
                "CROSS_SECTION_ZSCORE",
            ),
            research_horizon="same-session 60 trading minutes",
            primary_references=(machine_learning_reference, intraday_momentum_reference),
            falsification_criteria=(
                "Continuation fails frequency/decay consistency or turnover-adjusted gates.",
            ),
            limitations=("Range location is only an OHLCV proxy for information arrival.",),
        ),
        FrontierAlphaStrategySpec(
            slug="opening-to-close-market-momentum",
            title="Opening-window to closing-window market momentum",
            mechanism="Early-session market return may predict the final trading window.",
            readiness=AlphaImplementationReadiness.REQUIRES_SESSION_ANCHOR_AGGREGATE,
            required_input_fields=("close", "volume"),
            required_operators=("SESSION_ANCHOR_RETURN", "MARKET_AGGREGATE"),
            research_horizon="first 30m signal to final 30m response",
            primary_references=(intraday_momentum_reference, intraday_seasonality_reference),
            falsification_criteria=(
                "No purged out-of-sample closing-window predictability after costs.",
            ),
            limitations=(
                "Current FactorGraph has no session-anchor or market-aggregate operator.",
            ),
        ),
        FrontierAlphaStrategySpec(
            slug="day-night-decomposed-momentum",
            title="Day/night decomposed momentum",
            mechanism="Intraday and overnight return components may carry different continuation and reversal information.",
            readiness=AlphaImplementationReadiness.REQUIRES_CROSS_SESSION_DATA,
            required_input_fields=("open", "close"),
            required_operators=("CROSS_SESSION_RETURN",),
            research_horizon="multi-session",
            primary_references=(day_night_reference,),
            falsification_criteria=("Day/night decomposition adds no stable OOS information.",),
            limitations=("Explicitly outside the accepted same-session RAW-price authority.",),
        ),
        FrontierAlphaStrategySpec(
            slug="order-flow-informed-reversal",
            title="Order-flow/private-information conditioned reversal",
            mechanism="Transient liquidity pressure should reverse differently from informed permanent price impact.",
            readiness=AlphaImplementationReadiness.REQUIRES_ORDER_FLOW_DATA,
            required_input_fields=("order_imbalance", "quotes", "trades"),
            required_operators=("PRIVATE_INFORMATION_PROXY",),
            research_horizon="intraday",
            primary_references=(private_information_reference,),
            falsification_criteria=(
                "Conditioning measure does not separate transient from permanent moves.",
            ),
            limitations=(
                "Not representable from the certified OHLCV corpus and not approximated silently.",
            ),
        ),
    )


def build_us_r3_frontier_alpha_catalog() -> tuple[FrontierAlphaStrategySpec, ...]:
    return tuple(sorted(_strategy_specs(), key=lambda item: item.slug))


def build_us_r3_executable_frontier_candidates() -> tuple[FrontierAlphaCandidate, ...]:
    strategies = {item.slug: item for item in _strategy_specs()}
    definitions = (
        (
            "volatility-scaled-cross-sectional-momentum",
            volatility_scaled_momentum_graph(),
            "Test whether recent price continuation survives cross-sectional volatility scaling.",
            FactorMechanismCategory.INTERACTION,
            FactorExpectedDirection.POSITIVE,
        ),
        (
            "volume-conditioned-liquidity-reversal",
            volume_conditioned_reversal_graph(),
            "Test whether high-relative-volume short moves contain a transient reversal component.",
            FactorMechanismCategory.LIQUIDITY_VOLUME,
            FactorExpectedDirection.POSITIVE,
        ),
        (
            "volume-confirmed-range-location",
            volume_confirmed_range_location_graph(),
            "Test whether relative-volume-confirmed range location predicts same-session continuation.",
            FactorMechanismCategory.INTERACTION,
            FactorExpectedDirection.POSITIVE,
        ),
    )
    result: list[FrontierAlphaCandidate] = []
    for slug, graph, summary, mechanism, direction in definitions:
        strategy = strategies[slug]
        hypothesis = _hypothesis(
            graph,
            summary=summary,
            mechanism=mechanism,
            direction=direction,
            criteria=strategy.falsification_criteria,
            invalidating_conditions=(
                "Any use of label, holdout, broker, MT5, or post-result threshold feedback invalidates the proposal.",
            ),
        )
        result.append(FrontierAlphaCandidate(strategy, graph, hypothesis))
    return tuple(result)
