from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date

from finagent.domain.ashare_execution import (
    AshareAccountState,
    AshareBoard,
    AshareCompilationReport,
    AshareDailyExecutionSnapshot,
    AshareDesiredOrder,
    AshareExecutionCycle,
    AshareExecutionFill,
    AshareExecutionReport,
    AshareFeeBreakdown,
    AshareOrderDecision,
    AshareOrderDecisionStatus,
    AshareOrderReason,
    AsharePosition,
    infer_ashare_board,
)
from finagent.domain.assets import AssetId
from finagent.domain.orders import OrderIntent, OrderSide
from finagent.domain.portfolio import PortfolioTarget


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class AshareLotPolicy:
    regular_lot_size: int = 100
    star_minimum_buy: int = 200

    def __post_init__(self) -> None:
        if self.regular_lot_size < 1 or self.star_minimum_buy < 1:
            raise ValueError("A-share lot sizes must be positive")

    def round_buy(
        self,
        board: AshareBoard,
        requested: float,
    ) -> tuple[int, tuple[AshareOrderReason, ...]]:
        requested = float(requested)
        if not math.isfinite(requested) or requested <= 0:
            return 0, (AshareOrderReason.BELOW_MINIMUM_LOT,)
        integer = int(math.floor(requested + 1e-12))
        reasons: list[AshareOrderReason] = []
        if board is AshareBoard.SSE_STAR:
            quantity = integer if integer >= self.star_minimum_buy else 0
        else:
            quantity = (integer // self.regular_lot_size) * self.regular_lot_size
        if quantity <= 0:
            return 0, (AshareOrderReason.BELOW_MINIMUM_LOT,)
        if not math.isclose(quantity, requested, rel_tol=0.0, abs_tol=1e-9):
            reasons.append(AshareOrderReason.BUY_LOT_ROUNDED)
        return quantity, tuple(reasons)

    def round_sell(
        self,
        board: AshareBoard,
        requested: float,
        sellable: int,
    ) -> tuple[int, tuple[AshareOrderReason, ...]]:
        if sellable < 0:
            raise ValueError("sellable quantity must be non-negative")
        requested = float(requested)
        if not math.isfinite(requested) or requested <= 0 or sellable == 0:
            return 0, (AshareOrderReason.BELOW_MINIMUM_LOT,)
        capped = min(int(math.floor(requested + 1e-12)), sellable)
        if capped <= 0:
            return 0, (AshareOrderReason.BELOW_MINIMUM_LOT,)

        if capped >= sellable:
            quantity = sellable
        elif board is AshareBoard.SSE_STAR:
            quantity = capped if capped >= self.star_minimum_buy else 0
        else:
            lot = self.regular_lot_size
            remainder = sellable % lot
            candidates = [(capped // lot) * lot]
            if remainder > 0 and capped >= remainder:
                candidates.append(remainder + ((capped - remainder) // lot) * lot)
            quantity = max(value for value in candidates if value <= capped)

        if quantity <= 0:
            return 0, (AshareOrderReason.BELOW_MINIMUM_LOT,)
        reasons: list[AshareOrderReason] = []
        if not math.isclose(quantity, requested, rel_tol=0.0, abs_tol=1e-9):
            reasons.append(AshareOrderReason.SELL_LOT_ROUNDED)
        return quantity, tuple(reasons)


@dataclass(frozen=True, slots=True)
class AshareFeeSchedule:
    """Configurable A-share cash-equity fee schedule.

    Broker commission and its minimum are account-specific. Exchange/regulatory fee
    pass-through flags default to false because many retail commission schedules quote
    an all-in commission. Stamp duty and transfer fee remain explicit so buy/sell cost
    asymmetry cannot be hidden in one generic bps number.
    """

    broker_commission_rate: float = 0.0003
    minimum_broker_commission: float = 5.0
    stamp_duty_sell_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    sse_szse_handling_rate: float = 0.0000341
    bse_handling_rate: float = 0.000125
    regulatory_fee_rate: float = 0.00002
    pass_through_exchange_handling: bool = False
    pass_through_regulatory_fee: bool = False

    def __post_init__(self) -> None:
        for name in (
            "broker_commission_rate",
            "minimum_broker_commission",
            "stamp_duty_sell_rate",
            "transfer_fee_rate",
            "sse_szse_handling_rate",
            "bse_handling_rate",
            "regulatory_fee_rate",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)

    @property
    def schedule_id(self) -> str:
        digest = hashlib.sha256(_canonical_json(self.to_dict(include_id=False)).encode()).hexdigest()
        return f"ashare-fee-schedule-{digest[:24]}"

    def estimate(
        self,
        *,
        side: OrderSide,
        notional: float,
        board: AshareBoard,
    ) -> AshareFeeBreakdown:
        notional = float(notional)
        if not math.isfinite(notional) or notional < 0:
            raise ValueError("notional must be finite and non-negative")
        if notional == 0:
            return AshareFeeBreakdown()
        commission = max(
            self.minimum_broker_commission,
            notional * self.broker_commission_rate,
        )
        stamp = notional * self.stamp_duty_sell_rate if side is OrderSide.SELL else 0.0
        transfer = notional * self.transfer_fee_rate
        handling_rate = (
            self.bse_handling_rate
            if board is AshareBoard.BSE
            else self.sse_szse_handling_rate
        )
        handling = (
            notional * handling_rate if self.pass_through_exchange_handling else 0.0
        )
        regulatory = (
            notional * self.regulatory_fee_rate
            if self.pass_through_regulatory_fee
            else 0.0
        )
        return AshareFeeBreakdown(
            broker_commission=commission,
            stamp_duty=stamp,
            transfer_fee=transfer,
            exchange_handling_fee=handling,
            regulatory_fee=regulatory,
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "broker_commission_rate": self.broker_commission_rate,
            "minimum_broker_commission": self.minimum_broker_commission,
            "stamp_duty_sell_rate": self.stamp_duty_sell_rate,
            "transfer_fee_rate": self.transfer_fee_rate,
            "sse_szse_handling_rate": self.sse_szse_handling_rate,
            "bse_handling_rate": self.bse_handling_rate,
            "regulatory_fee_rate": self.regulatory_fee_rate,
            "pass_through_exchange_handling": self.pass_through_exchange_handling,
            "pass_through_regulatory_fee": self.pass_through_regulatory_fee,
        }
        if include_id:
            payload["schedule_id"] = self.schedule_id
        return payload


@dataclass(frozen=True, slots=True)
class AshareOrderCompilerConfig:
    require_prior_information: bool = True
    require_price_limits: bool = True
    minimum_notional: float = 0.0
    slippage_bps: float = 0.0
    quantity_tolerance: float = 1e-8

    def __post_init__(self) -> None:
        for name in ("minimum_notional", "slippage_bps", "quantity_tolerance"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)


class AshareInventoryLedger:
    """Immutable long-only A-share inventory ledger with explicit T+1 settlement."""

    zero_tolerance = 1e-8

    def roll_to_session(
        self,
        state: AshareAccountState,
        session_date: date,
    ) -> AshareAccountState:
        if session_date < state.session_date:
            raise ValueError("cannot roll A-share account backward")
        if session_date == state.session_date:
            return state
        positions = {
            asset: AsharePosition(
                total_quantity=position.total_quantity,
                sellable_quantity=position.total_quantity,
                unsettled_quantity=0,
            )
            for asset, position in state.positions.items()
        }
        return AshareAccountState(
            session_date=session_date,
            cash=state.cash,
            positions=positions,
            marks=state.marks,
            base_currency=state.base_currency,
            metadata={
                **dict(state.metadata),
                "settlement": "T+1 inventory rolled",
            },
        )

    def mark_to_snapshot(
        self,
        state: AshareAccountState,
        snapshot: AshareDailyExecutionSnapshot,
    ) -> AshareAccountState:
        state = self.roll_to_session(state, snapshot.session_date)
        marks = dict(state.marks)
        for asset, position in state.positions.items():
            if position.total_quantity == 0:
                continue
            try:
                marks[asset] = snapshot.mark(asset)
            except KeyError:
                if asset not in marks:
                    raise
        return AshareAccountState(
            session_date=snapshot.session_date,
            cash=state.cash,
            positions=state.positions,
            marks=marks,
            base_currency=state.base_currency,
            metadata=state.metadata,
        )

    def apply_execution(
        self,
        state: AshareAccountState,
        report: AshareExecutionReport,
        snapshot: AshareDailyExecutionSnapshot,
    ) -> AshareAccountState:
        if state.session_date != snapshot.session_date:
            raise ValueError("A-share account must be rolled to execution session")
        if report.session_date != snapshot.session_date:
            raise ValueError("A-share execution report session differs from snapshot")
        cash = float(state.cash)
        positions = dict(state.positions)

        for fill in report.fills:
            position = positions.get(fill.asset, AsharePosition(0, 0, 0))
            if fill.side is OrderSide.BUY:
                positions[fill.asset] = AsharePosition(
                    total_quantity=position.total_quantity + fill.quantity,
                    sellable_quantity=position.sellable_quantity,
                    unsettled_quantity=position.unsettled_quantity + fill.quantity,
                )
                cash -= fill.notional + fill.fees.total
            else:
                if fill.quantity > position.sellable_quantity:
                    raise ValueError("A-share sell fill exceeds T+1 sellable inventory")
                remaining_total = position.total_quantity - fill.quantity
                remaining_sellable = position.sellable_quantity - fill.quantity
                if remaining_total == 0:
                    positions.pop(fill.asset, None)
                else:
                    positions[fill.asset] = AsharePosition(
                        total_quantity=remaining_total,
                        sellable_quantity=remaining_sellable,
                        unsettled_quantity=position.unsettled_quantity,
                    )
                cash += fill.notional - fill.fees.total

        if cash < -self.zero_tolerance:
            raise ValueError("A-share execution produced negative cash")
        if abs(cash) <= self.zero_tolerance:
            cash = 0.0
        marks = dict(state.marks)
        for asset, position in positions.items():
            if position.total_quantity <= 0:
                continue
            try:
                marks[asset] = snapshot.mark(asset)
            except KeyError:
                if asset not in marks:
                    raise
        marks = {asset: mark for asset, mark in marks.items() if asset in positions}
        return AshareAccountState(
            session_date=snapshot.session_date,
            cash=cash,
            positions=positions,
            marks=marks,
            base_currency=state.base_currency,
            metadata={
                **dict(state.metadata),
                "last_execution_session": snapshot.session_date.isoformat(),
            },
        )


class AshareOrderCompiler:
    """Compile long-only target weights into A-share executable market orders."""

    VERSION = "ashare-order-compiler-v1"

    def __init__(
        self,
        *,
        config: AshareOrderCompilerConfig | None = None,
        lot_policy: AshareLotPolicy | None = None,
        fee_schedule: AshareFeeSchedule | None = None,
    ) -> None:
        self.config = config or AshareOrderCompilerConfig()
        self.lot_policy = lot_policy or AshareLotPolicy()
        self.fee_schedule = fee_schedule or AshareFeeSchedule()

    @staticmethod
    def _client_order_id(
        target: PortfolioTarget,
        snapshot: AshareDailyExecutionSnapshot,
        asset: AssetId,
        side: OrderSide,
        quantity: int,
    ) -> str:
        payload = {
            "target_asof": target.asof.isoformat(),
            "session_date": snapshot.session_date.isoformat(),
            "asset": asset.key,
            "side": side.value,
            "quantity": quantity,
        }
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
        return f"a3-{digest[:24]}"

    def _adverse_price(self, reference: float, side: OrderSide) -> float:
        rate = self.config.slippage_bps / 10_000.0
        return reference * (1.0 + rate if side is OrderSide.BUY else 1.0 - rate)

    def _decision(
        self,
        *,
        target: PortfolioTarget,
        snapshot: AshareDailyExecutionSnapshot,
        desired: AshareDesiredOrder,
        quantity: int,
        reasons: list[AshareOrderReason],
    ) -> AshareOrderDecision:
        if quantity <= 0:
            return AshareOrderDecision(
                desired=desired,
                status=AshareOrderDecisionStatus.REJECTED,
                executable_quantity=0,
                reason_codes=tuple(reason.value for reason in reasons),
                estimated_fees=AshareFeeBreakdown(),
            )
        board = infer_ashare_board(desired.asset)
        estimated_price = self._adverse_price(desired.reference_price, desired.side)
        fees = self.fee_schedule.estimate(
            side=desired.side,
            notional=estimated_price * quantity,
            board=board,
        )
        normalized = reasons or [AshareOrderReason.ACCEPTED]
        status = (
            AshareOrderDecisionStatus.ACCEPTED
            if normalized == [AshareOrderReason.ACCEPTED]
            else AshareOrderDecisionStatus.ADJUSTED
        )
        order = OrderIntent(
            asset=desired.asset,
            side=desired.side,
            quantity=float(quantity),
            created_at=target.asof,
            client_order_id=self._client_order_id(
                target,
                snapshot,
                desired.asset,
                desired.side,
                quantity,
            ),
            metadata={
                "a3_compiler": self.VERSION,
                "execution_session": snapshot.session_date.isoformat(),
                "requested_quantity": repr(desired.requested_quantity),
                "reference_price": repr(desired.reference_price),
                "estimated_fee_total": repr(fees.total),
                "reason_codes": ",".join(reason.value for reason in normalized),
            },
        )
        return AshareOrderDecision(
            desired=desired,
            status=status,
            executable_quantity=quantity,
            reason_codes=tuple(reason.value for reason in normalized),
            estimated_fees=fees,
            executable_order=order,
        )

    def _max_affordable_buy(
        self,
        *,
        board: AshareBoard,
        maximum: int,
        price: float,
        cash: float,
    ) -> int:
        if maximum <= 0 or cash <= 0:
            return 0
        if board is AshareBoard.SSE_STAR:
            minimum = self.lot_policy.star_minimum_buy
            if maximum < minimum:
                return 0
            low, high = minimum, maximum
            best = 0
            while low <= high:
                middle = (low + high) // 2
                fees = self.fee_schedule.estimate(
                    side=OrderSide.BUY,
                    notional=price * middle,
                    board=board,
                )
                if price * middle + fees.total <= cash + 1e-9:
                    best = middle
                    low = middle + 1
                else:
                    high = middle - 1
            return best

        lot = self.lot_policy.regular_lot_size
        maximum_lots = maximum // lot
        low, high = 1, maximum_lots
        best_lots = 0
        while low <= high:
            middle = (low + high) // 2
            quantity = middle * lot
            fees = self.fee_schedule.estimate(
                side=OrderSide.BUY,
                notional=price * quantity,
                board=board,
            )
            if price * quantity + fees.total <= cash + 1e-9:
                best_lots = middle
                low = middle + 1
            else:
                high = middle - 1
        return best_lots * lot

    def compile(
        self,
        target: PortfolioTarget,
        state: AshareAccountState,
        snapshot: AshareDailyExecutionSnapshot,
    ) -> AshareCompilationReport:
        if state.session_date != snapshot.session_date:
            raise ValueError("A-share account must be rolled to target execution session")
        if self.config.require_prior_information and target.asof >= snapshot.asof:
            raise ValueError(AshareOrderReason.TARGET_INFORMATION_NOT_PRIOR.value)
        if target.cash_weight < -target.weight_tolerance or any(
            weight < -target.weight_tolerance for weight in target.weights.values()
        ):
            raise ValueError(AshareOrderReason.LONG_ONLY_TARGET_REQUIRED.value)
        relevant_assets = set(target.weights) | set(state.positions)
        if not relevant_assets:
            raise ValueError("A-share target and account contain no assets")
        if set(relevant_assets) - set(snapshot.states):
            raise ValueError("A-share execution snapshot does not cover target/positions")

        nav = state.cash + sum(
            state.position(asset).total_quantity * snapshot.mark(asset)
            for asset in state.positions
        )
        if nav <= 0:
            raise ValueError("A-share pretrade NAV must be positive")

        sell_decisions: list[AshareOrderDecision] = []
        buy_specs: list[tuple[AshareDesiredOrder, int, list[AshareOrderReason]]] = []
        cash_after_sells = state.cash

        for asset in sorted(relevant_assets):
            market = snapshot.state(asset)
            price = market.execution_price or market.mark_price
            if price is None:
                target_quantity = 0.0
            else:
                target_quantity = target.weights.get(asset, 0.0) * nav / price
            current = state.position(asset).total_quantity
            delta = target_quantity - current
            if abs(delta) <= self.config.quantity_tolerance:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            requested = abs(delta)
            desired = AshareDesiredOrder(
                asset=asset,
                side=side,
                requested_quantity=requested,
                current_quantity=current,
                target_quantity=max(0.0, target_quantity),
                reference_price=price or 1.0,
            )
            blocked = market.block_reason(
                side,
                require_price_limits=self.config.require_price_limits,
            )
            if blocked is not None:
                decision = self._decision(
                    target=target,
                    snapshot=snapshot,
                    desired=desired,
                    quantity=0,
                    reasons=[blocked],
                )
                if side is OrderSide.SELL:
                    sell_decisions.append(decision)
                else:
                    buy_specs.append((desired, 0, [blocked]))
                continue

            assert price is not None
            board = market.board
            if side is OrderSide.SELL:
                position = state.position(asset)
                reasons: list[AshareOrderReason] = []
                capped = min(requested, float(position.sellable_quantity))
                if requested > position.sellable_quantity + self.config.quantity_tolerance:
                    reasons.append(AshareOrderReason.T1_SELLABLE_QUANTITY_CLIPPED)
                quantity, lot_reasons = self.lot_policy.round_sell(
                    board,
                    capped,
                    position.sellable_quantity,
                )
                reasons.extend(lot_reasons)
                if quantity <= 0 and not reasons:
                    reasons.append(AshareOrderReason.POSITION_NOT_AVAILABLE)
                if quantity > 0:
                    estimated_price = self._adverse_price(price, side)
                    notional = estimated_price * quantity
                    if notional < self.config.minimum_notional:
                        quantity = 0
                        reasons.append(AshareOrderReason.MINIMUM_NOTIONAL_NOT_MET)
                decision = self._decision(
                    target=target,
                    snapshot=snapshot,
                    desired=desired,
                    quantity=quantity,
                    reasons=reasons,
                )
                sell_decisions.append(decision)
                if decision.executable_order is not None:
                    proceeds = (
                        self._adverse_price(price, side) * quantity
                        - decision.estimated_fees.total
                    )
                    cash_after_sells += proceeds
            else:
                quantity, reasons_tuple = self.lot_policy.round_buy(board, requested)
                reasons = list(reasons_tuple)
                if quantity > 0:
                    estimated_price = self._adverse_price(price, side)
                    if estimated_price * quantity < self.config.minimum_notional:
                        quantity = 0
                        reasons.append(AshareOrderReason.MINIMUM_NOTIONAL_NOT_MET)
                buy_specs.append((desired, quantity, reasons))

        preliminary_cost = 0.0
        for desired, quantity, _ in buy_specs:
            if quantity <= 0:
                continue
            board = infer_ashare_board(desired.asset)
            price = self._adverse_price(desired.reference_price, OrderSide.BUY)
            fees = self.fee_schedule.estimate(
                side=OrderSide.BUY,
                notional=price * quantity,
                board=board,
            )
            preliminary_cost += price * quantity + fees.total
        scale = (
            min(1.0, max(0.0, cash_after_sells) / preliminary_cost)
            if preliminary_cost > 0
            else 1.0
        )

        buy_decisions: list[AshareOrderDecision] = []
        remaining_cash = max(0.0, cash_after_sells)
        for desired, original_quantity, reasons in sorted(
            buy_specs,
            key=lambda value: value[0].asset.key,
        ):
            if original_quantity <= 0:
                buy_decisions.append(
                    self._decision(
                        target=target,
                        snapshot=snapshot,
                        desired=desired,
                        quantity=0,
                        reasons=reasons or [AshareOrderReason.BELOW_MINIMUM_LOT],
                    )
                )
                continue
            board = infer_ashare_board(desired.asset)
            scaled_quantity, scaled_reasons = self.lot_policy.round_buy(
                board,
                original_quantity * scale,
            )
            if scaled_quantity < original_quantity:
                reasons.append(AshareOrderReason.INSUFFICIENT_CASH_SCALED)
            for reason in scaled_reasons:
                if reason not in reasons:
                    reasons.append(reason)
            price = self._adverse_price(desired.reference_price, OrderSide.BUY)
            affordable = self._max_affordable_buy(
                board=board,
                maximum=scaled_quantity,
                price=price,
                cash=remaining_cash,
            )
            if affordable < scaled_quantity:
                if AshareOrderReason.INSUFFICIENT_CASH_SCALED not in reasons:
                    reasons.append(AshareOrderReason.INSUFFICIENT_CASH_SCALED)
            quantity = affordable
            if quantity <= 0 and AshareOrderReason.BELOW_MINIMUM_LOT not in reasons:
                reasons.append(AshareOrderReason.BELOW_MINIMUM_LOT)
            decision = self._decision(
                target=target,
                snapshot=snapshot,
                desired=desired,
                quantity=quantity,
                reasons=reasons,
            )
            buy_decisions.append(decision)
            if decision.executable_order is not None:
                remaining_cash -= price * quantity + decision.estimated_fees.total

        decisions = tuple(sell_decisions + buy_decisions)
        orders = tuple(
            decision.executable_order
            for decision in decisions
            if decision.executable_order is not None
        )
        return AshareCompilationReport(
            target=target,
            session_date=snapshot.session_date,
            pretrade_nav=nav,
            available_cash_before_buys=cash_after_sells,
            decisions=decisions,
            orders=orders,
            metadata={
                "compiler": self.VERSION,
                "fee_schedule_id": self.fee_schedule.schedule_id,
                "slippage_bps": repr(self.config.slippage_bps),
                "cash_policy": "sell_proceeds_reusable_then_proportional_buy_scaling",
                "execution_scope": "long_only_A_share_cash_equity",
            },
        )


class AshareSimulatedExchange:
    """Execute already-compiled A-share orders at the exact session open."""

    VERSION = "ashare-simulated-exchange-v1"

    def __init__(
        self,
        *,
        fee_schedule: AshareFeeSchedule | None = None,
        lot_policy: AshareLotPolicy | None = None,
        slippage_bps: float = 0.0,
        require_price_limits: bool = True,
    ) -> None:
        self.fee_schedule = fee_schedule or AshareFeeSchedule()
        self.lot_policy = lot_policy or AshareLotPolicy()
        self.slippage_bps = float(slippage_bps)
        self.require_price_limits = bool(require_price_limits)
        if not math.isfinite(self.slippage_bps) or self.slippage_bps < 0:
            raise ValueError("slippage_bps must be finite and non-negative")

    def execute(
        self,
        compilation: AshareCompilationReport,
        snapshot: AshareDailyExecutionSnapshot,
    ) -> AshareExecutionReport:
        if compilation.session_date != snapshot.session_date:
            raise ValueError("A-share compilation session differs from execution snapshot")
        fills: list[AshareExecutionFill] = []
        rejections: dict[str, str] = {}
        slip_rate = self.slippage_bps / 10_000.0

        for order in compilation.orders:
            market = snapshot.state(order.asset)
            blocked = market.block_reason(
                order.side,
                require_price_limits=self.require_price_limits,
            )
            if blocked is not None:
                rejections[order.client_order_id] = (
                    f"{AshareOrderReason.EXCHANGE_REVALIDATION_FAILED.value}:"
                    f"{blocked.value}"
                )
                continue
            if market.execution_price is None:
                rejections[order.client_order_id] = (
                    AshareOrderReason.INVALID_EXECUTION_PRICE.value
                )
                continue
            rounded = round(order.quantity)
            if not math.isclose(order.quantity, rounded, rel_tol=0.0, abs_tol=1e-9):
                rejections[order.client_order_id] = "NON_INTEGER_A_SHARE_QUANTITY"
                continue
            quantity = int(rounded)
            if quantity <= 0:
                rejections[order.client_order_id] = "NON_POSITIVE_QUANTITY"
                continue
            sign = 1.0 if order.side is OrderSide.BUY else -1.0
            execution_price = market.execution_price * (1.0 + sign * slip_rate)
            notional = execution_price * quantity
            board = infer_ashare_board(order.asset)
            fees = self.fee_schedule.estimate(
                side=order.side,
                notional=notional,
                board=board,
            )
            fills.append(
                AshareExecutionFill(
                    client_order_id=order.client_order_id,
                    asset=order.asset,
                    side=order.side,
                    quantity=quantity,
                    reference_price=market.execution_price,
                    execution_price=execution_price,
                    executed_at=snapshot.asof,
                    fees=fees,
                    slippage=abs(execution_price - market.execution_price) * quantity,
                    metadata={
                        "exchange": self.VERSION,
                        "board": board.value,
                        "fee_schedule_id": self.fee_schedule.schedule_id,
                    },
                )
            )

        return AshareExecutionReport(
            session_date=snapshot.session_date,
            started_at=snapshot.asof,
            finished_at=snapshot.asof,
            orders=compilation.orders,
            fills=tuple(fills),
            rejections=rejections,
            metadata={
                "exchange": self.VERSION,
                "execution_price_field": "open",
                "slippage_bps": repr(self.slippage_bps),
                "fee_schedule_id": self.fee_schedule.schedule_id,
            },
        )


class AshareExecutionSession:
    """One deterministic A3 target-to-inventory execution cycle."""

    def __init__(
        self,
        *,
        compiler: AshareOrderCompiler | None = None,
        exchange: AshareSimulatedExchange | None = None,
        ledger: AshareInventoryLedger | None = None,
    ) -> None:
        self.compiler = compiler or AshareOrderCompiler()
        self.exchange = exchange or AshareSimulatedExchange(
            fee_schedule=self.compiler.fee_schedule,
            lot_policy=self.compiler.lot_policy,
            slippage_bps=self.compiler.config.slippage_bps,
            require_price_limits=self.compiler.config.require_price_limits,
        )
        self.ledger = ledger or AshareInventoryLedger()
        if not math.isclose(
            self.compiler.config.slippage_bps,
            self.exchange.slippage_bps,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("compiler and exchange slippage assumptions must match")
        if self.compiler.fee_schedule.schedule_id != self.exchange.fee_schedule.schedule_id:
            raise ValueError("compiler and exchange fee schedules must match")

    def run(
        self,
        target: PortfolioTarget,
        state: AshareAccountState,
        snapshot: AshareDailyExecutionSnapshot,
    ) -> AshareExecutionCycle:
        marked = self.ledger.mark_to_snapshot(state, snapshot)
        compilation = self.compiler.compile(target, marked, snapshot)
        execution = self.exchange.execute(compilation, snapshot)
        updated = self.ledger.apply_execution(marked, execution, snapshot)
        return AshareExecutionCycle(
            compilation=compilation,
            execution=execution,
            state_before=marked,
            state_after=updated,
        )
