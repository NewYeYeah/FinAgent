from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from finagent.domain.assets import AssetId
from finagent.domain.forecasts import AlphaForecast, ModelRef, RiskForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget


@dataclass(frozen=True, slots=True)
class MeanVarianceConfig:
    risk_aversion: float = 5.0
    cash_weight: float = 0.0
    long_only: bool = True
    max_abs_weight: float = 1.0
    turnover_penalty: float = 0.0
    smoothing_epsilon: float = 1e-8

    def __post_init__(self) -> None:
        if self.risk_aversion <= 0:
            raise ValueError("risk_aversion must be > 0")
        if not np.isfinite(self.cash_weight):
            raise ValueError("cash_weight must be finite")
        if self.max_abs_weight <= 0:
            raise ValueError("max_abs_weight must be > 0")
        if self.turnover_penalty < 0:
            raise ValueError("turnover_penalty must be >= 0")
        if self.smoothing_epsilon <= 0:
            raise ValueError("smoothing_epsilon must be > 0")


class MeanVarianceOptimizer:
    """Constrained Markowitz optimiser with optional turnover penalty."""

    def __init__(self, config: MeanVarianceConfig | None = None) -> None:
        self.config = config or MeanVarianceConfig()

    @staticmethod
    def _current_weights(state: PortfolioState, assets: tuple[AssetId, ...]) -> np.ndarray:
        if state.nav <= 0:
            raise ValueError("portfolio NAV must be > 0")
        return np.asarray([state.weight(asset) for asset in assets], dtype=float)

    def optimize(
        self,
        alpha: AlphaForecast,
        risk: RiskForecast,
        state: PortfolioState,
    ) -> PortfolioTarget:
        if alpha.asof != risk.asof:
            raise ValueError("alpha and risk forecasts must share the same asof")
        if alpha.horizon != risk.horizon:
            raise ValueError("alpha and risk forecasts must share the same horizon")
        if state.asof != alpha.asof:
            raise ValueError("PortfolioState must be marked to forecast asof before optimization")

        assets = tuple(sorted(set(alpha.expected_returns) & set(risk.volatilities)))
        if not assets:
            raise ValueError("alpha and risk forecasts have no common assets")
        if set(assets) != set(alpha.expected_returns) or set(assets) != set(risk.volatilities):
            raise ValueError("Phase 1 optimizer requires identical alpha/risk universes")

        invested_weight = 1.0 - self.config.cash_weight
        if self.config.long_only and invested_weight < -1e-12:
            raise ValueError("long-only optimizer cannot use cash_weight > 1")
        if self.config.long_only and invested_weight > len(assets) * self.config.max_abs_weight + 1e-12:
            raise ValueError("max_abs_weight is too small to satisfy the invested-weight constraint")

        mu = np.asarray([alpha.expected_returns[asset] for asset in assets], dtype=float)
        sigma = np.asarray(
            [[risk.covariance[(left, right)] for right in assets] for left in assets],
            dtype=float,
        )
        current = self._current_weights(state, assets)

        if self.config.long_only:
            bounds = [(0.0, self.config.max_abs_weight) for _ in assets]
            start = np.full(len(assets), invested_weight / len(assets), dtype=float)
        else:
            bounds = [(-self.config.max_abs_weight, self.config.max_abs_weight) for _ in assets]
            start = current.copy()
            adjustment = (invested_weight - float(start.sum())) / len(assets)
            start += adjustment

        def objective(weights: np.ndarray) -> float:
            expected_term = -float(mu @ weights)
            risk_term = 0.5 * self.config.risk_aversion * float(weights @ sigma @ weights)
            if self.config.turnover_penalty:
                delta = weights - current
                turnover = np.sum(np.sqrt(delta * delta + self.config.smoothing_epsilon))
                return expected_term + risk_term + self.config.turnover_penalty * float(turnover)
            return expected_term + risk_term

        result = minimize(
            objective,
            start,
            method="SLSQP",
            bounds=bounds,
            constraints=[{"type": "eq", "fun": lambda w: float(np.sum(w) - invested_weight)}],
            options={"maxiter": 1000, "ftol": 1e-12},
        )
        if not result.success or not np.all(np.isfinite(result.x)):
            raise RuntimeError(f"mean-variance optimization failed: {result.message}")
        weights = np.asarray(result.x, dtype=float)
        # Remove tiny solver residuals while preserving the accounting identity.
        weights[np.abs(weights) < 1e-12] = 0.0
        residual = invested_weight - float(weights.sum())
        if abs(residual) > 0:
            idx = int(np.argmax(np.abs(weights))) if np.any(weights) else 0
            weights[idx] += residual

        return PortfolioTarget(
            asof=alpha.asof,
            weights={asset: float(weights[idx]) for idx, asset in enumerate(assets)},
            cash_weight=self.config.cash_weight,
            source=ModelRef(name="mean_variance", version="phase1"),
            metadata={
                "risk_aversion": repr(self.config.risk_aversion),
                "turnover_penalty": repr(self.config.turnover_penalty),
                "objective": repr(float(result.fun)),
            },
        )
