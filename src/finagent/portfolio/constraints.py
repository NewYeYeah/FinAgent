from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

import numpy as np

from finagent.domain.assets import AssetId


@dataclass(frozen=True, slots=True)
class GroupExposureLimit:
    group: str
    min_weight: float = -1.0
    max_weight: float = 1.0

    def __post_init__(self) -> None:
        group = self.group.strip()
        if not group:
            raise ValueError("group must be non-empty")
        if not np.isfinite(self.min_weight) or not np.isfinite(self.max_weight):
            raise ValueError("group exposure limits must be finite")
        if self.min_weight > self.max_weight:
            raise ValueError("group min_weight cannot exceed max_weight")
        object.__setattr__(self, "group", group)


@dataclass(frozen=True, slots=True)
class LinearExposureLimit:
    """Linear factor/style/benchmark-relative exposure constraint."""

    name: str
    loadings: Mapping[AssetId, float]
    min_exposure: float
    max_exposure: float
    relative_to_benchmark: bool = False

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("exposure name must be non-empty")
        if not self.loadings:
            raise ValueError("linear exposure loadings cannot be empty")
        normalized = {asset: float(value) for asset, value in self.loadings.items()}
        if not all(np.isfinite(value) for value in normalized.values()):
            raise ValueError("linear exposure loadings must be finite")
        if not np.isfinite(self.min_exposure) or not np.isfinite(self.max_exposure):
            raise ValueError("linear exposure limits must be finite")
        if self.min_exposure > self.max_exposure:
            raise ValueError("min_exposure cannot exceed max_exposure")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "loadings", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class PortfolioConstraintSet:
    """Declarative portfolio constraints compiled into deterministic optimizer rules."""

    cash_weight: float = 0.0
    long_only: bool = True
    min_weight: float | None = None
    max_weight: float = 1.0
    gross_limit: float | None = 1.0
    turnover_limit: float | None = None
    asset_bounds: Mapping[AssetId, tuple[float, float]] = field(default_factory=dict)
    benchmark_weights: Mapping[AssetId, float] = field(default_factory=dict)
    active_weight_bounds: Mapping[AssetId, tuple[float, float]] = field(default_factory=dict)
    trade_weight_limits: Mapping[AssetId, float] = field(default_factory=dict)
    group_membership: Mapping[AssetId, str] = field(default_factory=dict)
    group_limits: Mapping[str, GroupExposureLimit] = field(default_factory=dict)
    linear_exposure_limits: Mapping[str, LinearExposureLimit] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not np.isfinite(self.cash_weight):
            raise ValueError("cash_weight must be finite")
        if self.max_weight <= 0 or not np.isfinite(self.max_weight):
            raise ValueError("max_weight must be finite and > 0")
        if self.min_weight is not None and not np.isfinite(self.min_weight):
            raise ValueError("min_weight must be finite when supplied")
        if self.gross_limit is not None and (
            self.gross_limit <= 0 or not np.isfinite(self.gross_limit)
        ):
            raise ValueError("gross_limit must be finite and > 0 when supplied")
        if self.turnover_limit is not None and (
            self.turnover_limit < 0 or not np.isfinite(self.turnover_limit)
        ):
            raise ValueError("turnover_limit must be finite and >= 0 when supplied")

        bounds: dict[AssetId, tuple[float, float]] = {}
        for asset, pair in self.asset_bounds.items():
            if len(pair) != 2:
                raise ValueError("asset_bounds values must be (lower, upper)")
            lower, upper = float(pair[0]), float(pair[1])
            if not np.isfinite(lower) or not np.isfinite(upper) or lower > upper:
                raise ValueError(f"invalid asset bounds for {asset.key}")
            if self.long_only and lower < -1e-15:
                raise ValueError("long-only constraints cannot contain negative asset lower bounds")
            bounds[asset] = (lower, upper)

        benchmark = {asset: float(value) for asset, value in self.benchmark_weights.items()}
        if not all(np.isfinite(value) for value in benchmark.values()):
            raise ValueError("benchmark weights must be finite")

        active_bounds: dict[AssetId, tuple[float, float]] = {}
        for asset, pair in self.active_weight_bounds.items():
            if len(pair) != 2:
                raise ValueError("active_weight_bounds values must be (lower, upper)")
            lower, upper = float(pair[0]), float(pair[1])
            if not np.isfinite(lower) or not np.isfinite(upper) or lower > upper:
                raise ValueError(f"invalid active bounds for {asset.key}")
            if asset not in benchmark:
                raise ValueError("active_weight_bounds require benchmark_weights for the same asset")
            active_bounds[asset] = (lower, upper)

        trade_limits = {asset: float(value) for asset, value in self.trade_weight_limits.items()}
        if any(value < 0 or not np.isfinite(value) for value in trade_limits.values()):
            raise ValueError("trade_weight_limits must be finite and >= 0")

        membership = {asset: str(group).strip() for asset, group in self.group_membership.items()}
        if any(not group for group in membership.values()):
            raise ValueError("group membership names must be non-empty")
        limits: dict[str, GroupExposureLimit] = {}
        for group, limit in self.group_limits.items():
            if not isinstance(limit, GroupExposureLimit):
                raise TypeError("group_limits values must be GroupExposureLimit")
            key = str(group).strip()
            if key != limit.group:
                raise ValueError("group_limits key must match GroupExposureLimit.group")
            limits[key] = limit

        linear: dict[str, LinearExposureLimit] = {}
        for name, limit in self.linear_exposure_limits.items():
            if not isinstance(limit, LinearExposureLimit):
                raise TypeError("linear_exposure_limits values must be LinearExposureLimit")
            key = str(name).strip()
            if key != limit.name:
                raise ValueError("linear_exposure_limits key must match LinearExposureLimit.name")
            if limit.relative_to_benchmark and not benchmark:
                raise ValueError("benchmark-relative exposure limits require benchmark_weights")
            linear[key] = limit

        object.__setattr__(self, "asset_bounds", MappingProxyType(bounds))
        object.__setattr__(self, "benchmark_weights", MappingProxyType(benchmark))
        object.__setattr__(self, "active_weight_bounds", MappingProxyType(active_bounds))
        object.__setattr__(self, "trade_weight_limits", MappingProxyType(trade_limits))
        object.__setattr__(self, "group_membership", MappingProxyType(membership))
        object.__setattr__(self, "group_limits", MappingProxyType(limits))
        object.__setattr__(self, "linear_exposure_limits", MappingProxyType(linear))

    @property
    def invested_weight(self) -> float:
        return 1.0 - self.cash_weight

    def bound_for(self, asset: AssetId) -> tuple[float, float]:
        if asset in self.asset_bounds:
            lower, upper = self.asset_bounds[asset]
        else:
            lower = 0.0 if self.long_only else -self.max_weight
            if self.min_weight is not None:
                lower = max(lower, self.min_weight) if self.long_only else self.min_weight
            upper = self.max_weight
        if asset in self.active_weight_bounds:
            benchmark = self.benchmark_weights[asset]
            active_lower, active_upper = self.active_weight_bounds[asset]
            lower = max(lower, benchmark + active_lower)
            upper = min(upper, benchmark + active_upper)
        if lower > upper:
            raise ValueError(f"combined absolute/active bounds are infeasible for {asset.key}")
        return float(lower), float(upper)


@dataclass(frozen=True, slots=True)
class CompiledPortfolioConstraints:
    assets: tuple[AssetId, ...]
    bounds: tuple[tuple[float, float], ...]
    scipy_constraints: tuple[dict[str, object], ...]
    policy: PortfolioConstraintSet
    current_weights: np.ndarray

    def __post_init__(self) -> None:
        current = np.asarray(self.current_weights, dtype=float)
        if current.shape != (len(self.assets),) or not np.all(np.isfinite(current)):
            raise ValueError("current_weights must match assets and be finite")
        current = np.array(current, copy=True)
        current.setflags(write=False)
        object.__setattr__(self, "current_weights", current)

    def _linear_exposure(self, weights: np.ndarray, limit: LinearExposureLimit) -> float:
        exposure = sum(limit.loadings.get(asset, 0.0) * weights[idx] for idx, asset in enumerate(self.assets))
        if limit.relative_to_benchmark:
            benchmark = sum(
                limit.loadings.get(asset, 0.0) * self.policy.benchmark_weights.get(asset, 0.0)
                for asset in self.assets
            )
            exposure -= benchmark
        return float(exposure)

    def check(self, weights: np.ndarray, *, tolerance: float = 1e-7) -> tuple[str, ...]:
        values = np.asarray(weights, dtype=float)
        if values.shape != (len(self.assets),) or not np.all(np.isfinite(values)):
            return ("weights_shape_or_finiteness",)
        failures: list[str] = []
        if abs(float(values.sum()) - self.policy.invested_weight) > tolerance:
            failures.append("invested_weight")
        for index, (lower, upper) in enumerate(self.bounds):
            if values[index] < lower - tolerance or values[index] > upper + tolerance:
                failures.append(f"asset_bound:{self.assets[index].key}")
        if self.policy.gross_limit is not None:
            if float(np.abs(values).sum()) > self.policy.gross_limit + tolerance:
                failures.append("gross_limit")
        if self.policy.turnover_limit is not None:
            turnover = 0.5 * float(np.abs(values - self.current_weights).sum())
            if turnover > self.policy.turnover_limit + tolerance:
                failures.append("turnover_limit")
        for idx, asset in enumerate(self.assets):
            trade_limit = self.policy.trade_weight_limits.get(asset)
            if trade_limit is not None and abs(values[idx] - self.current_weights[idx]) > trade_limit + tolerance:
                failures.append(f"trade_weight_limit:{asset.key}")
        for group, limit in self.policy.group_limits.items():
            indices = [
                idx
                for idx, asset in enumerate(self.assets)
                if self.policy.group_membership.get(asset) == group
            ]
            exposure = float(values[indices].sum()) if indices else 0.0
            if exposure < limit.min_weight - tolerance:
                failures.append(f"group_min:{group}")
            if exposure > limit.max_weight + tolerance:
                failures.append(f"group_max:{group}")
        for name, limit in self.policy.linear_exposure_limits.items():
            exposure = self._linear_exposure(values, limit)
            if exposure < limit.min_exposure - tolerance:
                failures.append(f"linear_min:{name}")
            if exposure > limit.max_exposure + tolerance:
                failures.append(f"linear_max:{name}")
        return tuple(failures)


class ConstraintCompiler:
    """Compile declarative limits into SciPy-SLSQP bounds and constraints."""

    def compile(
        self,
        assets: tuple[AssetId, ...],
        *,
        current_weights: np.ndarray,
        policy: PortfolioConstraintSet,
    ) -> CompiledPortfolioConstraints:
        if not assets or len(set(assets)) != len(assets):
            raise ValueError("assets must be non-empty and unique")
        current = np.asarray(current_weights, dtype=float)
        if current.shape != (len(assets),) or not np.all(np.isfinite(current)):
            raise ValueError("current_weights must have shape (len(assets),)")
        bounds = tuple(policy.bound_for(asset) for asset in assets)
        lower_sum = sum(lower for lower, _ in bounds)
        upper_sum = sum(upper for _, upper in bounds)
        if policy.invested_weight < lower_sum - 1e-12 or policy.invested_weight > upper_sum + 1e-12:
            raise ValueError("asset bounds cannot satisfy invested-weight identity")
        if policy.gross_limit is not None and abs(policy.invested_weight) > policy.gross_limit + 1e-12:
            raise ValueError("gross_limit cannot satisfy invested-weight identity")

        constraints: list[dict[str, object]] = [
            {
                "type": "eq",
                "fun": lambda w, target=policy.invested_weight: float(np.sum(w) - target),
            }
        ]
        if policy.gross_limit is not None:
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, limit=policy.gross_limit: float(limit - np.abs(w).sum()),
                }
            )
        if policy.turnover_limit is not None:
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, limit=policy.turnover_limit, cur=current.copy(): float(
                        limit - 0.5 * np.abs(w - cur).sum()
                    ),
                }
            )
        for idx, asset in enumerate(assets):
            trade_limit = policy.trade_weight_limits.get(asset)
            if trade_limit is not None:
                constraints.append(
                    {
                        "type": "ineq",
                        "fun": lambda w, i=idx, limit=trade_limit, cur=float(current[idx]): float(
                            limit - abs(w[i] - cur)
                        ),
                    }
                )
        for group, limit in policy.group_limits.items():
            indices = tuple(
                idx
                for idx, asset in enumerate(assets)
                if policy.group_membership.get(asset) == group
            )
            if not indices:
                raise ValueError(f"group limit {group!r} has no assets in optimizer universe")
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, idx=indices, lower=limit.min_weight: float(
                        np.sum(w[list(idx)]) - lower
                    ),
                }
            )
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, idx=indices, upper=limit.max_weight: float(
                        upper - np.sum(w[list(idx)])
                    ),
                }
            )
        for name, limit in policy.linear_exposure_limits.items():
            loadings = np.asarray([limit.loadings.get(asset, 0.0) for asset in assets], dtype=float)
            benchmark = 0.0
            if limit.relative_to_benchmark:
                benchmark = float(
                    sum(
                        limit.loadings.get(asset, 0.0) * policy.benchmark_weights.get(asset, 0.0)
                        for asset in assets
                    )
                )
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, loading=loadings.copy(), lower=limit.min_exposure, base=benchmark: float(
                        loading @ w - base - lower
                    ),
                }
            )
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, loading=loadings.copy(), upper=limit.max_exposure, base=benchmark: float(
                        upper - (loading @ w - base)
                    ),
                }
            )

        return CompiledPortfolioConstraints(
            assets=assets,
            bounds=bounds,
            scipy_constraints=tuple(constraints),
            policy=policy,
            current_weights=current,
        )
