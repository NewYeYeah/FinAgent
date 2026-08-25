from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from finagent.domain.execution import Fill
from finagent.domain.portfolio import PortfolioTarget

from .domain import ExecutionCostCalibration, ShadowComparison


@dataclass(frozen=True, slots=True)
class ShadowPortfolioMonitor:
    def compare(self, primary: PortfolioTarget, shadow: PortfolioTarget) -> ShadowComparison:
        if primary.asof != shadow.asof:
            raise ValueError("primary and shadow targets must share asof")
        assets = tuple(sorted(set(primary.weights) | set(shadow.weights)))
        left = np.asarray([primary.weights.get(asset, 0.0) for asset in assets], dtype=float)
        right = np.asarray([shadow.weights.get(asset, 0.0) for asset in assets], dtype=float)
        delta = right - left
        left_norm = float(np.linalg.norm(left))
        right_norm = float(np.linalg.norm(right))
        cosine = 1.0
        if left_norm > 0 and right_norm > 0:
            cosine = float(np.dot(left, right) / (left_norm * right_norm))
        elif left_norm > 0 or right_norm > 0:
            cosine = 0.0
        return ShadowComparison(
            asof=primary.asof,
            primary_source=f"{primary.source.name}:{primary.source.version}",
            shadow_source=f"{shadow.source.name}:{shadow.source.version}",
            max_abs_weight_difference=float(np.max(np.abs(delta))) if delta.size else 0.0,
            active_turnover=0.5 * float(np.abs(delta).sum()),
            cosine_similarity=float(np.clip(cosine, -1.0, 1.0)),
        )


@dataclass(frozen=True, slots=True)
class ExecutionCostCalibrator:
    def fit(self, fills: Sequence[Fill]) -> ExecutionCostCalibration:
        fills = tuple(fills)
        if not fills:
            raise ValueError("fills cannot be empty")
        total_notional = sum(fill.notional for fill in fills)
        if total_notional <= 0:
            raise ValueError("fill notional must be positive")
        weighted_slippage = 0.0
        weighted_commission = 0.0
        weighted_participation = 0.0
        for fill in fills:
            weight = fill.notional / total_notional
            reference = float(fill.metadata.get("reference_price", fill.price))
            if reference <= 0:
                raise ValueError("reference_price must be positive")
            slip_bps = abs(fill.price - reference) / reference * 10_000.0
            commission_bps = fill.commission / fill.notional * 10_000.0
            participation = float(fill.metadata.get("participation_rate", "0"))
            weighted_slippage += weight * slip_bps
            weighted_commission += weight * commission_bps
            weighted_participation += weight * max(participation, 0.0)
        return ExecutionCostCalibration(
            fill_count=len(fills),
            notional=total_notional,
            weighted_slippage_bps=weighted_slippage,
            weighted_commission_bps=weighted_commission,
            weighted_participation_rate=weighted_participation,
        )
