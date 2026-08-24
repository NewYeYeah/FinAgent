from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np

from finagent.domain.forecasts import AlphaForecast, RiskForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget

from .constrained import (
    ConstrainedMeanVarianceConfig,
    ConstrainedMeanVarianceOptimizer,
    EqualWeightOptimizer,
    MinimumVarianceOptimizer,
    RiskParityOptimizer,
)
from .constraints import PortfolioConstraintSet


class PortfolioConstructor(Protocol):
    def optimize(
        self,
        alpha: AlphaForecast,
        risk: RiskForecast,
        state: PortfolioState,
    ) -> PortfolioTarget: ...


@dataclass(frozen=True, slots=True)
class PortfolioBenchmarkMetrics:
    expected_return: float
    volatility: float
    turnover: float
    expected_transaction_cost: float
    expected_net_return: float
    gross_exposure: float
    net_exposure: float

    def __post_init__(self) -> None:
        values = (
            self.expected_return,
            self.volatility,
            self.turnover,
            self.expected_transaction_cost,
            self.expected_net_return,
            self.gross_exposure,
            self.net_exposure,
        )
        if not all(np.isfinite(value) for value in values):
            raise ValueError("portfolio benchmark metrics must be finite")
        if self.volatility < 0 or self.turnover < 0 or self.expected_transaction_cost < 0:
            raise ValueError("volatility/turnover/transaction cost must be >= 0")


@dataclass(frozen=True, slots=True)
class PortfolioBenchmarkResult:
    name: str
    target: PortfolioTarget
    metrics: PortfolioBenchmarkMetrics

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("benchmark name must be non-empty")


def evaluate_portfolio_target(
    target: PortfolioTarget,
    alpha: AlphaForecast,
    risk: RiskForecast,
    state: PortfolioState,
    *,
    transaction_cost_bps: float = 0.0,
) -> PortfolioBenchmarkMetrics:
    if transaction_cost_bps < 0 or not np.isfinite(transaction_cost_bps):
        raise ValueError("transaction_cost_bps must be finite and >= 0")
    if target.asof != alpha.asof or target.asof != risk.asof or state.asof != target.asof:
        raise ValueError("target/forecasts/state must share the same asof")
    assets = tuple(sorted(target.weights))
    if set(assets) != set(alpha.expected_returns) or set(assets) != set(risk.volatilities):
        raise ValueError("benchmark target and forecasts must share identical universes")
    weights = np.asarray([target.weights[asset] for asset in assets], dtype=float)
    current = np.asarray([state.weight(asset) for asset in assets], dtype=float)
    mu = np.asarray([alpha.expected_returns[asset] for asset in assets], dtype=float)
    sigma = np.asarray(
        [[risk.covariance[(left, right)] for right in assets] for left in assets],
        dtype=float,
    )
    expected_return = float(mu @ weights)
    variance = max(float(weights @ sigma @ weights), 0.0)
    volatility = float(np.sqrt(variance))
    turnover = 0.5 * float(np.abs(weights - current).sum())
    cost = turnover * float(transaction_cost_bps) / 10000.0
    return PortfolioBenchmarkMetrics(
        expected_return=expected_return,
        volatility=volatility,
        turnover=turnover,
        expected_transaction_cost=cost,
        expected_net_return=expected_return - cost,
        gross_exposure=target.gross_exposure,
        net_exposure=target.net_exposure,
    )


class PortfolioBenchmarkSuite:
    """Run multiple deterministic constructors on the exact same forecasts/state."""

    def __init__(
        self,
        constructors: Mapping[str, PortfolioConstructor],
        *,
        transaction_cost_bps: float = 5.0,
    ) -> None:
        if not constructors:
            raise ValueError("constructors cannot be empty")
        if transaction_cost_bps < 0 or not np.isfinite(transaction_cost_bps):
            raise ValueError("transaction_cost_bps must be finite and >= 0")
        normalized: dict[str, PortfolioConstructor] = {}
        for name, constructor in constructors.items():
            key = str(name).strip()
            if not key:
                raise ValueError("constructor names must be non-empty")
            if key in normalized:
                raise ValueError(f"duplicate constructor name {key!r}")
            if not hasattr(constructor, "optimize"):
                raise TypeError("portfolio constructors must expose optimize(alpha, risk, state)")
            normalized[key] = constructor
        self.constructors = normalized
        self.transaction_cost_bps = float(transaction_cost_bps)

    @classmethod
    def reference_suite(
        cls,
        *,
        constraints: PortfolioConstraintSet | None = None,
        transaction_cost_bps: float = 5.0,
        risk_aversion: float = 5.0,
    ) -> "PortfolioBenchmarkSuite":
        policy = constraints or PortfolioConstraintSet()
        return cls(
            {
                "equal_weight": EqualWeightOptimizer(policy),
                "minimum_variance": MinimumVarianceOptimizer(policy),
                "risk_parity": RiskParityOptimizer(policy),
                "mean_variance": ConstrainedMeanVarianceOptimizer(
                    policy,
                    ConstrainedMeanVarianceConfig(
                        risk_aversion=risk_aversion,
                        turnover_cost_bps=transaction_cost_bps,
                    ),
                ),
            },
            transaction_cost_bps=transaction_cost_bps,
        )

    def run(
        self,
        alpha: AlphaForecast,
        risk: RiskForecast,
        state: PortfolioState,
    ) -> tuple[PortfolioBenchmarkResult, ...]:
        results: list[PortfolioBenchmarkResult] = []
        for name, constructor in self.constructors.items():
            target = constructor.optimize(alpha, risk, state)
            metrics = evaluate_portfolio_target(
                target,
                alpha,
                risk,
                state,
                transaction_cost_bps=self.transaction_cost_bps,
            )
            results.append(PortfolioBenchmarkResult(name=name, target=target, metrics=metrics))
        return tuple(results)
