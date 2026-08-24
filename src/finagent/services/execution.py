from __future__ import annotations

from dataclasses import dataclass

from finagent.domain.execution import ExecutionReport, Fill, OrderRejection
from finagent.domain.market import MarketSnapshot
from finagent.domain.orders import OrderIntent, OrderSide, OrderType
from finagent.domain.portfolio import PortfolioState


@dataclass(frozen=True, slots=True)
class SimulatedExchange:
    """Minimal deterministic market-order simulator for Phase 0.5 tests.

    Slippage is applied symmetrically against the trader.  `Fill.slippage` is the
    total monetary slippage versus the snapshot close, not a per-unit value.
    """

    slippage_bps: float = 0.0
    commission_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps must be >= 0")
        if self.commission_bps < 0:
            raise ValueError("commission_bps must be >= 0")

    def execute(
        self,
        orders: tuple[OrderIntent, ...],
        snapshot: MarketSnapshot,
    ) -> ExecutionReport:
        fills: list[Fill] = []
        rejections: list[OrderRejection] = []
        slip_rate = self.slippage_bps / 10_000.0
        commission_rate = self.commission_bps / 10_000.0

        for order in orders:
            if order.order_type is not OrderType.MARKET:
                rejections.append(
                    OrderRejection(order.client_order_id, "unsupported order type")
                )
                continue
            try:
                reference_price = snapshot.price(order.asset)
            except KeyError:
                rejections.append(
                    OrderRejection(order.client_order_id, "missing market price")
                )
                continue

            sign = 1.0 if order.side is OrderSide.BUY else -1.0
            execution_price = reference_price * (1.0 + sign * slip_rate)
            notional = execution_price * order.quantity
            commission = abs(notional) * commission_rate
            slippage = abs(execution_price - reference_price) * order.quantity
            fills.append(
                Fill(
                    client_order_id=order.client_order_id,
                    asset=order.asset,
                    side=order.side,
                    quantity=order.quantity,
                    price=execution_price,
                    executed_at=snapshot.asof,
                    commission=commission,
                    slippage=slippage,
                    metadata={"reference_price": repr(reference_price)},
                )
            )

        return ExecutionReport(
            started_at=snapshot.asof,
            finished_at=snapshot.asof,
            orders=orders,
            fills=tuple(fills),
            rejections=tuple(rejections),
            metadata={
                "venue": "simulated",
                "slippage_bps": repr(self.slippage_bps),
                "commission_bps": repr(self.commission_bps),
            },
        )


@dataclass(frozen=True, slots=True)
class AccountLedger:
    """Apply fills to cash/positions and create a new immutable PortfolioState."""

    zero_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        if self.zero_tolerance < 0:
            raise ValueError("zero_tolerance must be >= 0")

    def mark_to_market(
        self,
        state: PortfolioState,
        snapshot: MarketSnapshot,
    ) -> PortfolioState:
        if state.asof > snapshot.asof:
            raise ValueError("state.asof cannot be after snapshot.asof")
        marks = dict(state.marks)
        for asset, quantity in state.positions.items():
            if abs(quantity) > self.zero_tolerance:
                marks[asset] = snapshot.price(asset)
        return PortfolioState(
            asof=snapshot.asof,
            base_currency=state.base_currency,
            cash=state.cash,
            positions=state.positions,
            marks=marks,
        )

    def apply_execution(
        self,
        state: PortfolioState,
        report: ExecutionReport,
        snapshot: MarketSnapshot,
    ) -> PortfolioState:
        if report.finished_at > snapshot.asof:
            raise ValueError("cannot value execution report using an earlier snapshot")
        cash = state.cash
        positions = dict(state.positions)

        for fill in report.fills:
            signed_quantity = fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
            positions[fill.asset] = positions.get(fill.asset, 0.0) + signed_quantity
            if abs(positions[fill.asset]) <= self.zero_tolerance:
                positions.pop(fill.asset, None)

            if fill.side is OrderSide.BUY:
                cash -= fill.notional + fill.commission
            else:
                cash += fill.notional - fill.commission

        marks: dict = {}
        for asset, quantity in positions.items():
            if abs(quantity) > self.zero_tolerance:
                marks[asset] = snapshot.price(asset)

        return PortfolioState(
            asof=snapshot.asof,
            base_currency=state.base_currency,
            cash=cash,
            positions=positions,
            marks=marks,
        )


@dataclass(frozen=True, slots=True)
class VolumeAwareSimulatedExchange:
    """Deterministic Phase 1 simulator with liquidity clipping and market impact.

    Orders are capped to ``max_participation_rate * snapshot.volume``. Adverse
    slippage in basis points is ``base_slippage_bps + impact_bps * sqrt(participation)``.
    This remains a research approximation, not an exchange microstructure model.
    """

    commission_bps: float = 0.0
    base_slippage_bps: float = 0.0
    impact_bps: float = 10.0
    max_participation_rate: float = 0.10

    def __post_init__(self) -> None:
        if self.commission_bps < 0 or self.base_slippage_bps < 0 or self.impact_bps < 0:
            raise ValueError("cost parameters must be >= 0")
        if not 0 < self.max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be in (0, 1]")

    def execute(
        self,
        orders: tuple[OrderIntent, ...],
        snapshot: MarketSnapshot,
    ) -> ExecutionReport:
        import math

        fills: list[Fill] = []
        rejections: list[OrderRejection] = []
        commission_rate = self.commission_bps / 10_000.0
        for order in orders:
            if order.order_type is not OrderType.MARKET:
                rejections.append(OrderRejection(order.client_order_id, "unsupported order type"))
                continue
            try:
                bar = snapshot.bars[order.asset]
            except KeyError:
                rejections.append(OrderRejection(order.client_order_id, "missing market bar"))
                continue
            if bar.volume <= 0:
                rejections.append(OrderRejection(order.client_order_id, "non-positive market volume"))
                continue
            max_quantity = bar.volume * self.max_participation_rate
            fill_quantity = min(order.quantity, max_quantity)
            if fill_quantity <= 0:
                rejections.append(OrderRejection(order.client_order_id, "zero executable quantity"))
                continue
            participation = fill_quantity / bar.volume
            slip_bps = self.base_slippage_bps + self.impact_bps * math.sqrt(participation)
            slip_rate = slip_bps / 10_000.0
            sign = 1.0 if order.side is OrderSide.BUY else -1.0
            reference_price = bar.close
            execution_price = reference_price * (1.0 + sign * slip_rate)
            notional = execution_price * fill_quantity
            commission = abs(notional) * commission_rate
            slippage = abs(execution_price - reference_price) * fill_quantity
            fills.append(
                Fill(
                    client_order_id=order.client_order_id,
                    asset=order.asset,
                    side=order.side,
                    quantity=fill_quantity,
                    price=execution_price,
                    executed_at=snapshot.asof,
                    commission=commission,
                    slippage=slippage,
                    metadata={
                        "reference_price": repr(reference_price),
                        "participation_rate": repr(participation),
                        "slippage_bps": repr(slip_bps),
                        "requested_quantity": repr(order.quantity),
                    },
                )
            )
        return ExecutionReport(
            started_at=snapshot.asof,
            finished_at=snapshot.asof,
            orders=orders,
            fills=tuple(fills),
            rejections=tuple(rejections),
            metadata={
                "venue": "volume_aware_simulated",
                "max_participation_rate": repr(self.max_participation_rate),
                "impact_bps": repr(self.impact_bps),
            },
        )
