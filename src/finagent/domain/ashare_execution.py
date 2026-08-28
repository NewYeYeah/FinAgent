from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Mapping

from ._validation import (
    freeze_mapping,
    require_aware_datetime,
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
)
from .assets import AssetId, AssetType
from .orders import OrderIntent, OrderSide
from .portfolio import PortfolioTarget


class AshareBoard(str, Enum):
    SSE_MAIN = "sse_main"
    SSE_STAR = "sse_star"
    SZSE_MAIN = "szse_main"
    SZSE_CHINEXT = "szse_chinext"
    BSE = "bse"


def infer_ashare_board(asset: AssetId) -> AshareBoard:
    """Map a canonical A-share equity identity to a trading board.

    The mapping is deliberately limited to the security-code families present in the
    frozen local dataset. Unsupported identities fail closed instead of inheriting
    generic cash-equity rules.
    """

    if asset.asset_type is not AssetType.EQUITY or asset.currency != "CNY":
        raise ValueError(f"A-share execution requires a CNY equity: {asset.key}")
    if asset.venue == "SSE":
        return (
            AshareBoard.SSE_STAR
            if asset.symbol.startswith(("688", "689"))
            else AshareBoard.SSE_MAIN
        )
    if asset.venue == "SZSE":
        return (
            AshareBoard.SZSE_CHINEXT
            if asset.symbol.startswith(("300", "301", "302"))
            else AshareBoard.SZSE_MAIN
        )
    if asset.venue == "BSE":
        return AshareBoard.BSE
    raise ValueError(f"unsupported A-share venue for execution: {asset.key}")


class AshareSessionStatus(str, Enum):
    TRADABLE = "tradable"
    SUSPENDED = "suspended"
    NO_SESSION_DATA = "no_session_data"
    INVALID_PRICE = "invalid_price"
    LIMITS_UNAVAILABLE = "limits_unavailable"


class AshareOrderDecisionStatus(str, Enum):
    ACCEPTED = "accepted"
    ADJUSTED = "adjusted"
    REJECTED = "rejected"
    NO_ACTION = "no_action"


class AshareOrderReason(str, Enum):
    ACCEPTED = "ACCEPTED"
    NO_TARGET_DELTA = "NO_TARGET_DELTA"
    LONG_ONLY_TARGET_REQUIRED = "LONG_ONLY_TARGET_REQUIRED"
    TARGET_INFORMATION_NOT_PRIOR = "TARGET_INFORMATION_NOT_PRIOR"
    NO_SESSION_DATA = "NO_SESSION_DATA"
    SUSPENDED = "SUSPENDED"
    INVALID_EXECUTION_PRICE = "INVALID_EXECUTION_PRICE"
    PRICE_LIMITS_UNAVAILABLE = "PRICE_LIMITS_UNAVAILABLE"
    BUY_BLOCKED_AT_LIMIT_UP = "BUY_BLOCKED_AT_LIMIT_UP"
    SELL_BLOCKED_AT_LIMIT_DOWN = "SELL_BLOCKED_AT_LIMIT_DOWN"
    T1_SELLABLE_QUANTITY_CLIPPED = "T1_SELLABLE_QUANTITY_CLIPPED"
    BUY_LOT_ROUNDED = "BUY_LOT_ROUNDED"
    SELL_LOT_ROUNDED = "SELL_LOT_ROUNDED"
    BELOW_MINIMUM_LOT = "BELOW_MINIMUM_LOT"
    INSUFFICIENT_CASH_SCALED = "INSUFFICIENT_CASH_SCALED"
    MINIMUM_NOTIONAL_NOT_MET = "MINIMUM_NOTIONAL_NOT_MET"
    POSITION_NOT_AVAILABLE = "POSITION_NOT_AVAILABLE"
    EXCHANGE_REVALIDATION_FAILED = "EXCHANGE_REVALIDATION_FAILED"


@dataclass(frozen=True, slots=True)
class AshareTradeability:
    asset: AssetId
    board: AshareBoard
    session_date: date
    observed_at: datetime
    status: AshareSessionStatus
    execution_price: float | None = None
    mark_price: float | None = None
    previous_close: float | None = None
    upper_limit: float | None = None
    lower_limit: float | None = None
    volume: float = 0.0
    is_st: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
    price_tolerance: float = 1e-8

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observed_at",
            require_aware_datetime(self.observed_at, "observed_at"),
        )
        if self.price_tolerance < 0 or not math.isfinite(self.price_tolerance):
            raise ValueError("price_tolerance must be finite and non-negative")
        for name in (
            "execution_price",
            "mark_price",
            "previous_close",
            "upper_limit",
            "lower_limit",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_positive(value, name))
        object.__setattr__(
            self,
            "volume",
            require_non_negative(self.volume, "volume"),
        )
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
        if self.status is AshareSessionStatus.TRADABLE and self.execution_price is None:
            raise ValueError("tradable A-share state requires execution_price")
        if self.status is AshareSessionStatus.SUSPENDED and self.volume > 0:
            raise ValueError("suspended A-share state cannot have positive volume")

    @property
    def at_upper_limit(self) -> bool:
        return bool(
            self.execution_price is not None
            and self.upper_limit is not None
            and self.execution_price >= self.upper_limit - self.price_tolerance
        )

    @property
    def at_lower_limit(self) -> bool:
        return bool(
            self.execution_price is not None
            and self.lower_limit is not None
            and self.execution_price <= self.lower_limit + self.price_tolerance
        )

    def block_reason(
        self,
        side: OrderSide,
        *,
        require_price_limits: bool = True,
    ) -> AshareOrderReason | None:
        if self.status is AshareSessionStatus.NO_SESSION_DATA:
            return AshareOrderReason.NO_SESSION_DATA
        if self.status is AshareSessionStatus.SUSPENDED:
            return AshareOrderReason.SUSPENDED
        if self.status is AshareSessionStatus.INVALID_PRICE:
            return AshareOrderReason.INVALID_EXECUTION_PRICE
        if self.status is AshareSessionStatus.LIMITS_UNAVAILABLE and require_price_limits:
            return AshareOrderReason.PRICE_LIMITS_UNAVAILABLE
        if self.execution_price is None:
            return AshareOrderReason.INVALID_EXECUTION_PRICE
        if side is OrderSide.BUY and self.at_upper_limit:
            return AshareOrderReason.BUY_BLOCKED_AT_LIMIT_UP
        if side is OrderSide.SELL and self.at_lower_limit:
            return AshareOrderReason.SELL_BLOCKED_AT_LIMIT_DOWN
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "asset": self.asset.key,
            "board": self.board.value,
            "session_date": self.session_date.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "status": self.status.value,
            "execution_price": self.execution_price,
            "mark_price": self.mark_price,
            "previous_close": self.previous_close,
            "upper_limit": self.upper_limit,
            "lower_limit": self.lower_limit,
            "volume": self.volume,
            "is_st": self.is_st,
            "at_upper_limit": self.at_upper_limit,
            "at_lower_limit": self.at_lower_limit,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AshareDailyExecutionSnapshot:
    session_date: date
    asof: datetime
    states: Mapping[AssetId, AshareTradeability]
    data_version: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asof", require_aware_datetime(self.asof, "asof"))
        values = freeze_mapping(self.states)
        if not values:
            raise ValueError("A-share execution snapshot requires states")
        for asset, state in values.items():
            if asset != state.asset:
                raise ValueError("A-share execution state key differs from state.asset")
            if state.session_date != self.session_date:
                raise ValueError("A-share execution states must share session_date")
            if state.observed_at > self.asof:
                raise ValueError("A-share execution state is not visible at snapshot asof")
        object.__setattr__(self, "states", values)
        object.__setattr__(
            self,
            "data_version",
            require_non_empty(self.data_version, "data_version"),
        )
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    def state(self, asset: AssetId) -> AshareTradeability:
        try:
            return self.states[asset]
        except KeyError as exc:
            raise KeyError(f"no A-share execution state for {asset.key}") from exc

    def mark(self, asset: AssetId) -> float:
        state = self.state(asset)
        if state.mark_price is None:
            raise KeyError(f"no A-share mark for {asset.key}")
        return state.mark_price

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "asof": self.asof.isoformat(),
            "data_version": self.data_version,
            "states": {
                asset.key: state.to_dict()
                for asset, state in sorted(self.states.items())
            },
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AsharePosition:
    total_quantity: int
    sellable_quantity: int
    unsettled_quantity: int = 0

    def __post_init__(self) -> None:
        values = (
            self.total_quantity,
            self.sellable_quantity,
            self.unsettled_quantity,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("A-share position quantities must be integers")
        if any(value < 0 for value in values):
            raise ValueError("A-share position quantities must be non-negative")
        if self.sellable_quantity + self.unsettled_quantity != self.total_quantity:
            raise ValueError(
                "A-share position requires sellable_quantity + unsettled_quantity "
                "= total_quantity"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "total_quantity": self.total_quantity,
            "sellable_quantity": self.sellable_quantity,
            "unsettled_quantity": self.unsettled_quantity,
        }


@dataclass(frozen=True, slots=True)
class AshareAccountState:
    session_date: date
    cash: float
    positions: Mapping[AssetId, AsharePosition] = field(default_factory=dict)
    marks: Mapping[AssetId, float] = field(default_factory=dict)
    base_currency: str = "CNY"
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash", require_finite(self.cash, "cash"))
        currency = require_non_empty(self.base_currency, "base_currency").upper()
        if currency != "CNY":
            raise ValueError("A-share account base_currency must be CNY")
        positions = freeze_mapping(self.positions)
        marks = {
            asset: require_positive(price, f"marks[{asset.key}]")
            for asset, price in self.marks.items()
        }
        missing = {
            asset
            for asset, position in positions.items()
            if position.total_quantity > 0 and asset not in marks
        }
        if missing:
            keys = ", ".join(sorted(asset.key for asset in missing))
            raise ValueError(f"A-share positions require marks; missing: {keys}")
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "marks", freeze_mapping(marks))
        object.__setattr__(self, "base_currency", currency)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def nav(self) -> float:
        return self.cash + sum(
            position.total_quantity * self.marks[asset]
            for asset, position in self.positions.items()
        )

    def position(self, asset: AssetId) -> AsharePosition:
        return self.positions.get(asset, AsharePosition(0, 0, 0))

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "cash": self.cash,
            "nav": self.nav,
            "base_currency": self.base_currency,
            "positions": {
                asset.key: position.to_dict()
                for asset, position in sorted(self.positions.items())
            },
            "marks": {
                asset.key: mark for asset, mark in sorted(self.marks.items())
            },
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AshareDesiredOrder:
    asset: AssetId
    side: OrderSide
    requested_quantity: float
    current_quantity: int
    target_quantity: float
    reference_price: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested_quantity",
            require_positive(self.requested_quantity, "requested_quantity"),
        )
        if self.current_quantity < 0:
            raise ValueError("current_quantity must be non-negative")
        object.__setattr__(
            self,
            "target_quantity",
            require_non_negative(self.target_quantity, "target_quantity"),
        )
        object.__setattr__(
            self,
            "reference_price",
            require_positive(self.reference_price, "reference_price"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "asset": self.asset.key,
            "side": self.side.value,
            "requested_quantity": self.requested_quantity,
            "current_quantity": self.current_quantity,
            "target_quantity": self.target_quantity,
            "reference_price": self.reference_price,
        }


@dataclass(frozen=True, slots=True)
class AshareFeeBreakdown:
    broker_commission: float = 0.0
    stamp_duty: float = 0.0
    transfer_fee: float = 0.0
    exchange_handling_fee: float = 0.0
    regulatory_fee: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "broker_commission",
            "stamp_duty",
            "transfer_fee",
            "exchange_handling_fee",
            "regulatory_fee",
        ):
            object.__setattr__(
                self,
                name,
                require_non_negative(getattr(self, name), name),
            )

    @property
    def total(self) -> float:
        return (
            self.broker_commission
            + self.stamp_duty
            + self.transfer_fee
            + self.exchange_handling_fee
            + self.regulatory_fee
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "broker_commission": self.broker_commission,
            "stamp_duty": self.stamp_duty,
            "transfer_fee": self.transfer_fee,
            "exchange_handling_fee": self.exchange_handling_fee,
            "regulatory_fee": self.regulatory_fee,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class AshareOrderDecision:
    desired: AshareDesiredOrder
    status: AshareOrderDecisionStatus
    executable_quantity: int
    reason_codes: tuple[str, ...]
    estimated_fees: AshareFeeBreakdown
    executable_order: OrderIntent | None = None

    def __post_init__(self) -> None:
        if self.executable_quantity < 0:
            raise ValueError("executable_quantity must be non-negative")
        reasons = tuple(require_non_empty(value, "reason code") for value in self.reason_codes)
        if not reasons:
            raise ValueError("A-share order decision requires reason_codes")
        object.__setattr__(self, "reason_codes", reasons)
        if self.executable_order is None and self.executable_quantity != 0:
            raise ValueError("non-zero executable_quantity requires executable_order")
        if self.executable_order is not None:
            if self.executable_order.asset != self.desired.asset:
                raise ValueError("executable order asset differs from desired order")
            if self.executable_order.side is not self.desired.side:
                raise ValueError("executable order side differs from desired order")
            if not math.isclose(
                self.executable_order.quantity,
                float(self.executable_quantity),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError("executable order quantity differs from decision")
        if self.status is AshareOrderDecisionStatus.REJECTED and self.executable_order is not None:
            raise ValueError("rejected A-share order cannot carry executable_order")

    @property
    def rejected_quantity(self) -> float:
        return max(0.0, self.desired.requested_quantity - self.executable_quantity)

    def to_dict(self) -> dict[str, object]:
        return {
            "desired": self.desired.to_dict(),
            "status": self.status.value,
            "executable_quantity": self.executable_quantity,
            "rejected_quantity": self.rejected_quantity,
            "reason_codes": list(self.reason_codes),
            "estimated_fees": self.estimated_fees.to_dict(),
            "client_order_id": (
                self.executable_order.client_order_id
                if self.executable_order is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class AshareCompilationReport:
    target: PortfolioTarget
    session_date: date
    pretrade_nav: float
    available_cash_before_buys: float
    decisions: tuple[AshareOrderDecision, ...]
    orders: tuple[OrderIntent, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pretrade_nav",
            require_positive(self.pretrade_nav, "pretrade_nav"),
        )
        object.__setattr__(
            self,
            "available_cash_before_buys",
            require_finite(
                self.available_cash_before_buys,
                "available_cash_before_buys",
            ),
        )
        decision_ids = {
            decision.executable_order.client_order_id
            for decision in self.decisions
            if decision.executable_order is not None
        }
        order_ids = {order.client_order_id for order in self.orders}
        if decision_ids != order_ids:
            raise ValueError("A-share compilation decisions and orders differ")
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def estimated_total_fees(self) -> float:
        return sum(decision.estimated_fees.total for decision in self.decisions)

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "pretrade_nav": self.pretrade_nav,
            "available_cash_before_buys": self.available_cash_before_buys,
            "estimated_total_fees": self.estimated_total_fees,
            "orders": [order.client_order_id for order in self.orders],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AshareExecutionFill:
    client_order_id: str
    asset: AssetId
    side: OrderSide
    quantity: int
    reference_price: float
    execution_price: float
    executed_at: datetime
    fees: AshareFeeBreakdown
    slippage: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            require_non_empty(self.client_order_id, "client_order_id"),
        )
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("A-share fill quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("A-share fill quantity must be positive")
        object.__setattr__(
            self,
            "reference_price",
            require_positive(self.reference_price, "reference_price"),
        )
        object.__setattr__(
            self,
            "execution_price",
            require_positive(self.execution_price, "execution_price"),
        )
        object.__setattr__(
            self,
            "executed_at",
            require_aware_datetime(self.executed_at, "executed_at"),
        )
        object.__setattr__(
            self,
            "slippage",
            require_non_negative(self.slippage, "slippage"),
        )
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def notional(self) -> float:
        return self.quantity * self.execution_price

    def to_dict(self) -> dict[str, object]:
        return {
            "client_order_id": self.client_order_id,
            "asset": self.asset.key,
            "side": self.side.value,
            "quantity": self.quantity,
            "reference_price": self.reference_price,
            "execution_price": self.execution_price,
            "executed_at": self.executed_at.isoformat(),
            "notional": self.notional,
            "fees": self.fees.to_dict(),
            "slippage": self.slippage,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AshareExecutionReport:
    session_date: date
    started_at: datetime
    finished_at: datetime
    orders: tuple[OrderIntent, ...]
    fills: tuple[AshareExecutionFill, ...]
    rejections: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        started = require_aware_datetime(self.started_at, "started_at")
        finished = require_aware_datetime(self.finished_at, "finished_at")
        if finished < started:
            raise ValueError("finished_at cannot be earlier than started_at")
        known = {order.client_order_id for order in self.orders}
        if any(fill.client_order_id not in known for fill in self.fills):
            raise ValueError("A-share fill references unknown order")
        if any(order_id not in known for order_id in self.rejections):
            raise ValueError("A-share rejection references unknown order")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        object.__setattr__(self, "rejections", freeze_mapping(self.rejections))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def total_fees(self) -> float:
        return sum(fill.fees.total for fill in self.fills)

    @property
    def total_slippage(self) -> float:
        return sum(fill.slippage for fill in self.fills)

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "orders": [order.client_order_id for order in self.orders],
            "fills": [fill.to_dict() for fill in self.fills],
            "rejections": dict(self.rejections),
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AshareExecutionCycle:
    compilation: AshareCompilationReport
    execution: AshareExecutionReport
    state_before: AshareAccountState
    state_after: AshareAccountState

    def to_dict(self) -> dict[str, object]:
        return {
            "compilation": self.compilation.to_dict(),
            "execution": self.execution.to_dict(),
            "state_before": self.state_before.to_dict(),
            "state_after": self.state_after.to_dict(),
        }
