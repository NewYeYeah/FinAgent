from __future__ import annotations

from dataclasses import dataclass

from finagent.domain.assets import AssetId
from finagent.domain.forecasts import ModelRef
from finagent.domain.market import MarketSnapshot
from finagent.domain.orders import OrderIntent, OrderSide
from finagent.domain.portfolio import (
    PortfolioState,
    PortfolioTarget,
    RiskDecision,
    RiskStatus,
    RiskViolation,
)


@dataclass(frozen=True, slots=True)
class EqualWeightTargetBuilder:
    """Deterministic smoke-test portfolio constructor.

    This is not intended to be the production optimizer.  It exists so the domain
    kernel can be exercised without AR/GARCH/optimizer dependencies in Phase 0.5.
    """

    source: ModelRef = ModelRef(name="equal_weight", version="phase0.5")

    def build(
        self,
        snapshot: MarketSnapshot,
        assets: tuple[AssetId, ...],
        cash_weight: float = 0.0,
    ) -> PortfolioTarget:
        if not assets:
            raise ValueError("assets cannot be empty")
        if len(set(assets)) != len(assets):
            raise ValueError("assets cannot contain duplicates")
        for asset in assets:
            snapshot.price(asset)
        invested_weight = 1.0 - float(cash_weight)
        per_asset = invested_weight / len(assets)
        return PortfolioTarget(
            asof=snapshot.asof,
            weights={asset: per_asset for asset in assets},
            cash_weight=cash_weight,
            source=self.source,
            metadata={"builder": "equal_weight"},
        )


@dataclass(frozen=True, slots=True)
class StaticRiskGate:
    """Simple hard-constraint gate with explicit, non-mutating decisions."""

    max_gross_exposure: float = 1.0
    max_abs_weight: float = 1.0
    min_cash_weight: float | None = None
    violation_status: RiskStatus = RiskStatus.REQUIRE_RESOLVE

    def __post_init__(self) -> None:
        if self.max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be > 0")
        if self.max_abs_weight <= 0:
            raise ValueError("max_abs_weight must be > 0")
        if self.violation_status is RiskStatus.APPROVE:
            raise ValueError("violation_status cannot be APPROVE")

    def assess(
        self,
        target: PortfolioTarget,
        state: PortfolioState,
        snapshot: MarketSnapshot,
    ) -> RiskDecision:
        if target.asof != snapshot.asof:
            raise ValueError("target.asof must equal snapshot.asof")
        if state.asof > snapshot.asof:
            raise ValueError("state.asof cannot be after snapshot.asof")

        violations: list[RiskViolation] = []
        if target.gross_exposure > self.max_gross_exposure + target.weight_tolerance:
            violations.append(
                RiskViolation(
                    code="MAX_GROSS_EXPOSURE",
                    message="target gross exposure exceeds configured limit",
                    observed=target.gross_exposure,
                    limit=self.max_gross_exposure,
                )
            )

        for asset, weight in target.weights.items():
            if abs(weight) > self.max_abs_weight + target.weight_tolerance:
                violations.append(
                    RiskViolation(
                        code="MAX_ABS_WEIGHT",
                        message=f"absolute target weight exceeds configured limit for {asset.key}",
                        observed=abs(weight),
                        limit=self.max_abs_weight,
                    )
                )

        if self.min_cash_weight is not None and target.cash_weight < self.min_cash_weight:
            violations.append(
                RiskViolation(
                    code="MIN_CASH_WEIGHT",
                    message="target cash weight is below configured minimum",
                    observed=target.cash_weight,
                    limit=self.min_cash_weight,
                )
            )

        if violations:
            return RiskDecision(
                status=self.violation_status,
                violations=tuple(violations),
                checked_at=snapshot.asof,
            )
        return RiskDecision(status=RiskStatus.APPROVE, checked_at=snapshot.asof)


@dataclass(frozen=True, slots=True)
class OrderPlanner:
    """Translate an approved target into broker-agnostic market order intents."""

    min_notional: float = 0.0
    quantity_precision: int = 8

    def __post_init__(self) -> None:
        if self.min_notional < 0:
            raise ValueError("min_notional must be >= 0")
        if self.quantity_precision < 0:
            raise ValueError("quantity_precision must be >= 0")

    def plan(
        self,
        target: PortfolioTarget,
        state: PortfolioState,
        snapshot: MarketSnapshot,
        risk_decision: RiskDecision,
    ) -> tuple[OrderIntent, ...]:
        if risk_decision.status is not RiskStatus.APPROVE:
            raise PermissionError(
                f"portfolio target is not approved by risk gate: {risk_decision.status.value}"
            )
        if target.asof != snapshot.asof:
            raise ValueError("target.asof must equal snapshot.asof")
        if state.asof > snapshot.asof:
            raise ValueError("state.asof cannot be after snapshot.asof")

        relevant_assets = set(target.weights) | {
            asset for asset, quantity in state.positions.items() if abs(quantity) > 1e-15
        }
        for asset in relevant_assets:
            if asset.currency != state.base_currency:
                raise ValueError(
                    f"Phase 0.5 planner requires base-currency marks; {asset.key} is not {state.base_currency}"
                )
            snapshot.price(asset)

        nav = state.cash + sum(
            quantity * snapshot.price(asset) for asset, quantity in state.positions.items()
        )
        if nav <= 0:
            raise ValueError(f"portfolio NAV must be > 0 to generate weight targets, got {nav}")

        orders: list[OrderIntent] = []
        for asset in sorted(relevant_assets):
            price = snapshot.price(asset)
            current_value = state.positions.get(asset, 0.0) * price
            target_value = target.weights.get(asset, 0.0) * nav
            delta_value = target_value - current_value
            if abs(delta_value) < self.min_notional or abs(delta_value) <= 1e-12:
                continue
            quantity = round(abs(delta_value / price), self.quantity_precision)
            if quantity <= 0:
                continue
            orders.append(
                OrderIntent(
                    asset=asset,
                    side=OrderSide.BUY if delta_value > 0 else OrderSide.SELL,
                    quantity=quantity,
                    created_at=snapshot.asof,
                    metadata={
                        "target_weight": repr(target.weights.get(asset, 0.0)),
                        "reference_price": repr(price),
                    },
                )
            )
        return tuple(orders)
