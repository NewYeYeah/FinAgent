from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from finagent.domain.assets import AssetId
from finagent.domain.forecasts import AlphaForecast, ModelRef, RiskForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget

from .constraints import ConstraintCompiler, PortfolioConstraintSet


def _aligned_inputs(
    alpha: AlphaForecast,
    risk: RiskForecast,
    state: PortfolioState,
) -> tuple[tuple[AssetId, ...], np.ndarray, np.ndarray, np.ndarray]:
    if alpha.asof != risk.asof or alpha.horizon != risk.horizon:
        raise ValueError("alpha and risk forecasts must share asof and horizon")
    if state.asof != alpha.asof:
        raise ValueError("PortfolioState must be marked to forecast asof")
    assets = tuple(sorted(alpha.expected_returns))
    if not assets or set(assets) != set(risk.volatilities):
        raise ValueError("alpha and risk forecasts must have identical non-empty universes")
    if state.nav <= 0:
        raise ValueError("portfolio NAV must be > 0")
    mu = np.asarray([alpha.expected_returns[asset] for asset in assets], dtype=float)
    sigma = np.asarray(
        [[risk.covariance[(left, right)] for right in assets] for left in assets],
        dtype=float,
    )
    current = np.asarray([state.weight(asset) for asset in assets], dtype=float)
    return assets, mu, sigma, current


def _feasible_start(compiled, preferred: np.ndarray) -> np.ndarray:
    preferred = np.asarray(preferred, dtype=float)
    if preferred.shape != (len(compiled.assets),):
        raise ValueError("preferred start shape mismatch")
    clipped = np.asarray(
        [
            min(max(preferred[idx], lower), upper)
            for idx, (lower, upper) in enumerate(compiled.bounds)
        ],
        dtype=float,
    )
    result = minimize(
        lambda w: float(np.sum((w - preferred) ** 2)),
        clipped,
        method="SLSQP",
        bounds=compiled.bounds,
        constraints=list(compiled.scipy_constraints),
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    if not result.success or compiled.check(result.x, tolerance=1e-6):
        raise RuntimeError(f"portfolio constraints have no numerically feasible start: {result.message}")
    return np.asarray(result.x, dtype=float)


def _target(
    *,
    asof,
    assets: tuple[AssetId, ...],
    weights: np.ndarray,
    cash_weight: float,
    source_name: str,
    metadata: dict[str, str],
) -> PortfolioTarget:
    values = np.asarray(weights, dtype=float).copy()
    values[np.abs(values) < 1e-12] = 0.0
    residual = (1.0 - cash_weight) - float(values.sum())
    if abs(residual) > 0:
        idx = int(np.argmax(np.abs(values))) if np.any(values) else 0
        values[idx] += residual
    return PortfolioTarget(
        asof=asof,
        weights={asset: float(values[idx]) for idx, asset in enumerate(assets)},
        cash_weight=float(cash_weight),
        source=ModelRef(name=source_name, version="phase4"),
        metadata=metadata,
    )


@dataclass(frozen=True, slots=True)
class ConstrainedMeanVarianceConfig:
    risk_aversion: float = 5.0
    turnover_cost_bps: float = 0.0
    smoothing_epsilon: float = 1e-8

    def __post_init__(self) -> None:
        if self.risk_aversion <= 0 or not np.isfinite(self.risk_aversion):
            raise ValueError("risk_aversion must be finite and > 0")
        if self.turnover_cost_bps < 0 or not np.isfinite(self.turnover_cost_bps):
            raise ValueError("turnover_cost_bps must be finite and >= 0")
        if self.smoothing_epsilon <= 0 or not np.isfinite(self.smoothing_epsilon):
            raise ValueError("smoothing_epsilon must be finite and > 0")


class ConstrainedMeanVarianceOptimizer:
    """Cost-aware Markowitz optimizer over a compiled deterministic constraint set."""

    def __init__(
        self,
        constraints: PortfolioConstraintSet | None = None,
        config: ConstrainedMeanVarianceConfig | None = None,
        *,
        compiler: ConstraintCompiler | None = None,
    ) -> None:
        self.constraints = constraints or PortfolioConstraintSet()
        self.config = config or ConstrainedMeanVarianceConfig()
        self.compiler = compiler or ConstraintCompiler()

    def optimize(
        self,
        alpha: AlphaForecast,
        risk: RiskForecast,
        state: PortfolioState,
    ) -> PortfolioTarget:
        assets, mu, sigma, current = _aligned_inputs(alpha, risk, state)
        compiled = self.compiler.compile(
            assets,
            current_weights=current,
            policy=self.constraints,
        )
        preferred = current.copy()
        if not np.all(np.isfinite(preferred)) or abs(float(preferred.sum()) - self.constraints.invested_weight) > 0.25:
            preferred = np.full(len(assets), self.constraints.invested_weight / len(assets))
        start = _feasible_start(compiled, preferred)
        eps = self.config.smoothing_epsilon
        cost_rate = self.config.turnover_cost_bps / 10000.0

        def objective(weights: np.ndarray) -> float:
            expected = -float(mu @ weights)
            risk_term = 0.5 * self.config.risk_aversion * float(weights @ sigma @ weights)
            delta = weights - current
            smooth_turnover = 0.5 * float(np.sum(np.sqrt(delta * delta + eps * eps) - eps))
            return expected + risk_term + cost_rate * smooth_turnover

        result = minimize(
            objective,
            start,
            method="SLSQP",
            bounds=compiled.bounds,
            constraints=list(compiled.scipy_constraints),
            options={"maxiter": 2000, "ftol": 1e-12},
        )
        failures = compiled.check(result.x, tolerance=2e-6) if result.success else ("solver",)
        if not result.success or failures or not np.all(np.isfinite(result.x)):
            raise RuntimeError(
                f"constrained mean-variance optimization failed: {result.message}; failures={failures}"
            )
        actual_turnover = 0.5 * float(np.abs(np.asarray(result.x) - current).sum())
        return _target(
            asof=alpha.asof,
            assets=assets,
            weights=np.asarray(result.x, dtype=float),
            cash_weight=self.constraints.cash_weight,
            source_name="constrained_mean_variance",
            metadata={
                "risk_aversion": repr(self.config.risk_aversion),
                "turnover_cost_bps": repr(self.config.turnover_cost_bps),
                "turnover": repr(actual_turnover),
                "objective": repr(float(result.fun)),
            },
        )


class MinimumVarianceOptimizer:
    """Minimum-variance benchmark under the same compiled constraints."""

    def __init__(
        self,
        constraints: PortfolioConstraintSet | None = None,
        *,
        compiler: ConstraintCompiler | None = None,
    ) -> None:
        self.constraints = constraints or PortfolioConstraintSet()
        self.compiler = compiler or ConstraintCompiler()

    def optimize(self, alpha: AlphaForecast, risk: RiskForecast, state: PortfolioState) -> PortfolioTarget:
        assets, _, sigma, current = _aligned_inputs(alpha, risk, state)
        compiled = self.compiler.compile(assets, current_weights=current, policy=self.constraints)
        preferred = np.full(len(assets), self.constraints.invested_weight / len(assets))
        start = _feasible_start(compiled, preferred)
        result = minimize(
            lambda w: float(w @ sigma @ w),
            start,
            method="SLSQP",
            bounds=compiled.bounds,
            constraints=list(compiled.scipy_constraints),
            options={"maxiter": 2000, "ftol": 1e-12},
        )
        failures = compiled.check(result.x, tolerance=2e-6) if result.success else ("solver",)
        if not result.success or failures:
            raise RuntimeError(f"minimum-variance optimization failed: {result.message}; failures={failures}")
        return _target(
            asof=alpha.asof,
            assets=assets,
            weights=np.asarray(result.x, dtype=float),
            cash_weight=self.constraints.cash_weight,
            source_name="minimum_variance",
            metadata={"variance": repr(float(result.fun))},
        )


class RiskParityOptimizer:
    """Equal-risk-contribution benchmark for long-only portfolios."""

    def __init__(
        self,
        constraints: PortfolioConstraintSet | None = None,
        *,
        compiler: ConstraintCompiler | None = None,
    ) -> None:
        self.constraints = constraints or PortfolioConstraintSet()
        if not self.constraints.long_only:
            raise ValueError("reference risk-parity implementation requires long_only=True")
        self.compiler = compiler or ConstraintCompiler()

    def optimize(self, alpha: AlphaForecast, risk: RiskForecast, state: PortfolioState) -> PortfolioTarget:
        assets, _, sigma, current = _aligned_inputs(alpha, risk, state)
        compiled = self.compiler.compile(assets, current_weights=current, policy=self.constraints)
        preferred = np.full(len(assets), self.constraints.invested_weight / len(assets))
        start = _feasible_start(compiled, preferred)

        def objective(weights: np.ndarray) -> float:
            marginal = sigma @ weights
            contributions = weights * marginal
            total = float(contributions.sum())
            target = total / len(weights)
            return float(np.sum((contributions - target) ** 2))

        result = minimize(
            objective,
            start,
            method="SLSQP",
            bounds=compiled.bounds,
            constraints=list(compiled.scipy_constraints),
            options={"maxiter": 2000, "ftol": 1e-14},
        )
        failures = compiled.check(result.x, tolerance=2e-6) if result.success else ("solver",)
        if not result.success or failures:
            raise RuntimeError(f"risk-parity optimization failed: {result.message}; failures={failures}")
        return _target(
            asof=alpha.asof,
            assets=assets,
            weights=np.asarray(result.x, dtype=float),
            cash_weight=self.constraints.cash_weight,
            source_name="risk_parity",
            metadata={"risk_contribution_error": repr(float(result.fun))},
        )


class EqualWeightOptimizer:
    """Constrained equal-weight benchmark using the same feasibility contract."""

    def __init__(
        self,
        constraints: PortfolioConstraintSet | None = None,
        *,
        compiler: ConstraintCompiler | None = None,
    ) -> None:
        self.constraints = constraints or PortfolioConstraintSet()
        self.compiler = compiler or ConstraintCompiler()

    def optimize(self, alpha: AlphaForecast, risk: RiskForecast, state: PortfolioState) -> PortfolioTarget:
        assets, _, _, current = _aligned_inputs(alpha, risk, state)
        compiled = self.compiler.compile(assets, current_weights=current, policy=self.constraints)
        equal = np.full(len(assets), self.constraints.invested_weight / len(assets))
        weights = _feasible_start(compiled, equal)
        return _target(
            asof=alpha.asof,
            assets=assets,
            weights=weights,
            cash_weight=self.constraints.cash_weight,
            source_name="equal_weight",
            metadata={"constraint_adjusted": repr(not np.allclose(weights, equal, atol=1e-8))},
        )
