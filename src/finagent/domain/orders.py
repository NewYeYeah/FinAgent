from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping
from uuid import uuid4

from ._validation import (
    freeze_mapping,
    require_aware_datetime,
    require_non_empty,
    require_positive,
)
from .assets import AssetId


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Broker-agnostic requested order generated from an approved portfolio target."""

    asset: AssetId
    side: OrderSide
    quantity: float
    created_at: datetime
    order_type: OrderType = OrderType.MARKET
    client_order_id: str = field(default_factory=lambda: uuid4().hex)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", require_positive(self.quantity, "quantity"))
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))
        object.__setattr__(
            self,
            "client_order_id",
            require_non_empty(self.client_order_id, "client_order_id"),
        )
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
