from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from finagent.domain.assets import AssetId
from finagent.domain.portfolio import PortfolioState, PortfolioTarget


@dataclass(frozen=True, slots=True)
class PortfolioScenario:
    name: str
    asset_returns: Mapping[AssetId, float]

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("scenario name must be non-empty")
        normalized = {asset: float(value) for asset, value in self.asset_returns.items()}
        if not normalized or not all(np.isfinite(value) for value in normalized.values()):
            raise ValueError("scenario returns must be non-empty and finite")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "asset_returns", normalized)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    portfolio_return: float

    def __post_init__(self) -> None:
        if not self.name.strip() or not np.isfinite(self.portfolio_return):
            raise ValueError("invalid scenario result")


@dataclass(frozen=True, slots=True)
class StressTestReport:
    results: tuple[ScenarioResult, ...]

    def __post_init__(self) -> None:
        if not self.results:
            raise ValueError("stress report cannot be empty")

    @property
    def worst(self) -> ScenarioResult:
        return min(self.results, key=lambda result: result.portfolio_return)


class PortfolioStressTester:
    """Deterministic instantaneous scenario evaluator for target weights."""

    def evaluate(
        self,
        target: PortfolioTarget,
        scenarios: Sequence[PortfolioScenario],
    ) -> StressTestReport:
        scenarios = tuple(scenarios)
        if not scenarios:
            raise ValueError("scenarios cannot be empty")
        universe = set(target.weights)
        output: list[ScenarioResult] = []
        for scenario in scenarios:
            missing = universe - set(scenario.asset_returns)
            if missing:
                keys = ", ".join(sorted(asset.key for asset in missing))
                raise ValueError(f"scenario {scenario.name!r} missing assets: {keys}")
            value = sum(
                target.weights[asset] * scenario.asset_returns[asset]
                for asset in target.weights
            )
            output.append(ScenarioResult(scenario.name, float(value)))
        return StressTestReport(tuple(output))


@dataclass(frozen=True, slots=True)
class RebalanceDecision:
    rebalance: bool
    turnover: float
    max_weight_drift: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.turnover < 0 or self.max_weight_drift < 0:
            raise ValueError("rebalance diagnostics must be >= 0")
        if self.rebalance and not self.reasons:
            raise ValueError("rebalance=True requires at least one reason")


@dataclass(frozen=True, slots=True)
class DriftRebalancePolicy:
    """Trigger a rebalance only when deterministic drift/turnover thresholds justify it."""

    max_weight_drift: float = 0.05
    min_turnover: float = 0.01
    force_turnover: float = 0.25

    def __post_init__(self) -> None:
        if self.max_weight_drift < 0 or self.min_turnover < 0 or self.force_turnover < 0:
            raise ValueError("rebalance thresholds must be >= 0")
        if self.force_turnover < self.min_turnover:
            raise ValueError("force_turnover must be >= min_turnover")

    def decide(self, target: PortfolioTarget, state: PortfolioState) -> RebalanceDecision:
        if target.asof != state.asof:
            raise ValueError("target and state must share the same asof")
        assets = tuple(sorted(set(target.weights) | set(state.positions)))
        current = np.asarray([state.weight(asset) for asset in assets], dtype=float)
        desired = np.asarray([target.weights.get(asset, 0.0) for asset in assets], dtype=float)
        drift = np.abs(desired - current)
        turnover = 0.5 * float(drift.sum())
        max_drift = float(drift.max()) if drift.size else 0.0
        reasons: list[str] = []
        if turnover >= self.force_turnover:
            reasons.append("force_turnover")
        elif turnover >= self.min_turnover and max_drift >= self.max_weight_drift:
            reasons.append("weight_drift")
        return RebalanceDecision(
            rebalance=bool(reasons),
            turnover=turnover,
            max_weight_drift=max_drift,
            reasons=tuple(reasons),
        )
