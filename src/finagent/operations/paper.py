from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from finagent.domain.execution import ExecutionSnapshot, Fill
from finagent.domain.orders import OrderIntent, OrderSide, OrderType
from finagent.domain.portfolio import PortfolioState

from .calendar import TradingSessionCalendar
from .corporate_actions import CorporateActionProcessor
from .domain import BrokerOrderStatus, CorporateAction, PaperBrokerCycle, PaperOrder
from .store import SQLitePaperBrokerStore


@dataclass(frozen=True, slots=True)
class PaperBrokerConfig:
    commission_bps: float = 0.0
    base_slippage_bps: float = 0.0
    impact_bps: float = 10.0
    max_participation_rate: float = 0.10

    def __post_init__(self) -> None:
        if min(self.commission_bps, self.base_slippage_bps, self.impact_bps) < 0:
            raise ValueError("paper-broker cost parameters must be >= 0")
        if not 0 < self.max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be in (0, 1]")


class PaperBroker:
    """Persistent deterministic paper venue with idempotent client order IDs."""

    def __init__(
        self,
        *,
        store: SQLitePaperBrokerStore,
        config: PaperBrokerConfig | None = None,
        calendar: TradingSessionCalendar | None = None,
    ) -> None:
        self.store = store
        self.config = config or PaperBrokerConfig()
        self.calendar = calendar

    def initialize_account(self, state: PortfolioState) -> PortfolioState:
        if self.store.has_account():
            existing = self.store.latest_account_snapshot()
            if existing != state:
                raise ValueError("paper account is already initialized with a different state")
            return existing
        self.store.save_account_snapshot(state, snapshot_key="initial")
        self.store.record_event(
            "account_initialized", state.asof,
            {"base_currency": state.base_currency, "cash": state.cash},
        )
        return state

    def submit(self, orders: Iterable[OrderIntent]) -> tuple[PaperOrder, ...]:
        account = self.store.latest_account_snapshot()
        output: list[PaperOrder] = []
        for intent in orders:
            if intent.asset.currency != account.base_currency:
                order = PaperOrder(
                    intent.client_order_id, intent.asset, intent.side, intent.quantity,
                    intent.created_at, intent.created_at,
                    status=BrokerOrderStatus.REJECTED,
                    rejection_reason="paper broker requires base-currency assets; FX translation is not enabled",
                    metadata=intent.metadata,
                )
            elif intent.order_type is not OrderType.MARKET:
                order = PaperOrder(
                    intent.client_order_id, intent.asset, intent.side, intent.quantity,
                    intent.created_at, intent.created_at,
                    status=BrokerOrderStatus.REJECTED,
                    rejection_reason="unsupported order type",
                    metadata=intent.metadata,
                )
            elif self.calendar is not None and not self.calendar.is_open(intent.created_at):
                order = PaperOrder(
                    intent.client_order_id, intent.asset, intent.side, intent.quantity,
                    intent.created_at, intent.created_at,
                    status=BrokerOrderStatus.REJECTED,
                    rejection_reason="outside trading session",
                    metadata=intent.metadata,
                )
            else:
                order = PaperOrder(
                    intent.client_order_id, intent.asset, intent.side, intent.quantity,
                    intent.created_at, intent.created_at, metadata=intent.metadata,
                )
            output.append(self.store.register_order(order))
        return tuple(output)

    def cancel(self, client_order_id: str, *, at: datetime) -> PaperOrder:
        order = self.store.get_order(client_order_id)
        if order.status.terminal:
            return order
        cancelled = PaperOrder(
            client_order_id=order.client_order_id,
            asset=order.asset,
            side=order.side,
            quantity=order.quantity,
            submitted_at=order.submitted_at,
            updated_at=at,
            status=BrokerOrderStatus.CANCELLED,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
            commission=order.commission,
            metadata=order.metadata,
        )
        self.store.update_order(cancelled)
        self.store.record_event("order_cancelled", at, {"client_order_id": client_order_id})
        return cancelled

    def process(self, snapshot: ExecutionSnapshot) -> PaperBrokerCycle:
        account = self.store.latest_account_snapshot()
        if account.asof > snapshot.asof:
            raise ValueError("execution snapshot cannot precede paper account")
        fills: list[Fill] = []
        touched: list[str] = []
        for order in self.store.list_open_orders():
            if snapshot.asof < order.submitted_at:
                continue
            try:
                quote = snapshot.quotes[order.asset]
            except KeyError:
                continue
            if quote.volume <= 0:
                continue
            fill_key = f"{order.client_order_id}:{snapshot.asof.isoformat()}"
            if self.store.has_fill(fill_key):
                continue
            executable = min(order.remaining_quantity, quote.volume * self.config.max_participation_rate)
            if executable <= 1e-15:
                continue
            participation = executable / quote.volume
            slip_bps = self.config.base_slippage_bps + self.config.impact_bps * math.sqrt(participation)
            sign = 1.0 if order.side is OrderSide.BUY else -1.0
            price = quote.price * (1.0 + sign * slip_bps / 10_000.0)
            commission = executable * price * self.config.commission_bps / 10_000.0
            fill = Fill(
                client_order_id=order.client_order_id,
                asset=order.asset,
                side=order.side,
                quantity=executable,
                price=price,
                executed_at=snapshot.asof,
                commission=commission,
                slippage=abs(price - quote.price) * executable,
                metadata={
                    "reference_price": repr(quote.price),
                    "price_field": quote.price_field,
                    "participation_rate": repr(participation),
                    "fill_key": fill_key,
                },
            )
            new_filled = order.filled_quantity + executable
            total_fill_notional = order.average_fill_price * order.filled_quantity + fill.price * executable
            avg = total_fill_notional / new_filled
            status = BrokerOrderStatus.FILLED if new_filled >= order.quantity - 1e-10 else BrokerOrderStatus.PARTIALLY_FILLED
            updated = PaperOrder(
                client_order_id=order.client_order_id,
                asset=order.asset,
                side=order.side,
                quantity=order.quantity,
                submitted_at=order.submitted_at,
                updated_at=snapshot.asof,
                status=status,
                filled_quantity=min(new_filled, order.quantity),
                average_fill_price=avg,
                commission=order.commission + commission,
                metadata=order.metadata,
            )
            account = self._apply_fill(account, fill, snapshot)
            applied = self.store.apply_fill_transition(
                fill_key=fill_key, fill=fill, updated_order=updated, account=account
            )
            if applied:
                fills.append(fill)
                touched.append(order.client_order_id)
            else:
                account = self.store.latest_account_snapshot()

        marked = self._mark_account(account, snapshot)
        self.store.save_account_snapshot(marked, snapshot_key=f"mark:{snapshot.asof.isoformat()}")
        return PaperBrokerCycle(snapshot.asof, tuple(fills), tuple(touched), marked.nav)

    def apply_corporate_action(
        self, action: CorporateAction, *, processor: CorporateActionProcessor | None = None
    ) -> PortfolioState:
        current = self.store.latest_account_snapshot()
        updated = (processor or CorporateActionProcessor()).apply(current, action)
        payload = {
            "action_id": action.action_id,
            "asset_key": action.asset.key,
            "action_type": action.action_type.value,
            "effective_at": action.effective_at.isoformat(),
            "ratio": action.ratio,
            "cash_amount": action.cash_amount,
        }
        self.store.apply_corporate_action(action_id=action.action_id, payload=payload, state=updated)
        return self.store.latest_account_snapshot()

    def account(self) -> PortfolioState:
        return self.store.latest_account_snapshot()

    @staticmethod
    def _apply_fill(state: PortfolioState, fill: Fill, snapshot: ExecutionSnapshot) -> PortfolioState:
        cash = state.cash
        positions = dict(state.positions)
        signed = fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
        positions[fill.asset] = positions.get(fill.asset, 0.0) + signed
        if abs(positions[fill.asset]) <= 1e-12:
            positions.pop(fill.asset, None)
        if fill.side is OrderSide.BUY:
            cash -= fill.notional + fill.commission
        else:
            cash += fill.notional - fill.commission
        marks = {}
        for asset, quantity in positions.items():
            if abs(quantity) <= 1e-12:
                continue
            marks[asset] = snapshot.price(asset) if asset in snapshot.quotes else state.marks[asset]
        return PortfolioState(
            asof=snapshot.asof,
            base_currency=state.base_currency,
            cash=cash,
            positions=positions,
            marks=marks,
        )

    @staticmethod
    def _mark_account(state: PortfolioState, snapshot: ExecutionSnapshot) -> PortfolioState:
        marks = dict(state.marks)
        for asset, quantity in state.positions.items():
            if abs(quantity) > 1e-12 and asset in snapshot.quotes:
                marks[asset] = snapshot.price(asset)
        return PortfolioState(
            asof=snapshot.asof,
            base_currency=state.base_currency,
            cash=state.cash,
            positions=state.positions,
            marks=marks,
        )
