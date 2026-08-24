from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from ._validation import (
    freeze_mapping,
    require_aware_datetime,
    require_non_empty,
    require_non_negative,
    require_positive,
)
from .assets import AssetId
from .orders import OrderIntent, OrderSide


@dataclass(frozen=True, slots=True)
class Fill:
    client_order_id: str
    asset: AssetId
    side: OrderSide
    quantity: float
    price: float
    executed_at: datetime
    commission: float = 0.0
    slippage: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            require_non_empty(self.client_order_id, "client_order_id"),
        )
        object.__setattr__(self, "quantity", require_positive(self.quantity, "quantity"))
        object.__setattr__(self, "price", require_positive(self.price, "price"))
        object.__setattr__(self, "executed_at", require_aware_datetime(self.executed_at, "executed_at"))
        object.__setattr__(self, "commission", require_non_negative(self.commission, "commission"))
        object.__setattr__(self, "slippage", require_non_negative(self.slippage, "slippage"))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def notional(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True, slots=True)
class OrderRejection:
    client_order_id: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            require_non_empty(self.client_order_id, "client_order_id"),
        )
        object.__setattr__(self, "reason", require_non_empty(self.reason, "reason"))


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    started_at: datetime
    finished_at: datetime
    orders: tuple[OrderIntent, ...]
    fills: tuple[Fill, ...]
    rejections: tuple[OrderRejection, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        started_at = require_aware_datetime(self.started_at, "started_at")
        finished_at = require_aware_datetime(self.finished_at, "finished_at")
        if finished_at < started_at:
            raise ValueError("finished_at cannot be earlier than started_at")
        known_order_ids = {order.client_order_id for order in self.orders}
        for fill in self.fills:
            if fill.client_order_id not in known_order_ids:
                raise ValueError(f"fill references unknown order {fill.client_order_id}")
        for rejection in self.rejections:
            if rejection.client_order_id not in known_order_ids:
                raise ValueError(f"rejection references unknown order {rejection.client_order_id}")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
