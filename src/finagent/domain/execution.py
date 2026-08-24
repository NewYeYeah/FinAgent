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
class ExecutionQuote:
    """A single executable price observation with field-level availability.

    Unlike ``PriceBar``, this object exposes only the price that can be used for
    execution at ``available_at``.  It therefore cannot leak a bar close/high/low
    into a next-open execution decision.
    """

    event_time: datetime
    available_at: datetime
    price: float
    volume: float = 0.0
    price_field: str = "open"

    def __post_init__(self) -> None:
        event_time = require_aware_datetime(self.event_time, "event_time")
        available_at = require_aware_datetime(self.available_at, "available_at")
        if available_at < event_time:
            raise ValueError("available_at cannot be earlier than event_time")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "price", require_positive(self.price, "price"))
        object.__setattr__(self, "volume", require_non_negative(self.volume, "volume"))
        object.__setattr__(self, "price_field", require_non_empty(self.price_field, "price_field"))


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """Executable prices visible at one execution instant."""

    asof: datetime
    quotes: Mapping[AssetId, ExecutionQuote]
    data_version: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        asof = require_aware_datetime(self.asof, "asof")
        quotes = freeze_mapping(self.quotes)
        if not quotes:
            raise ValueError("quotes cannot be empty")
        for asset, quote in quotes.items():
            if not isinstance(asset, AssetId):
                raise TypeError("quotes keys must be AssetId instances")
            if not isinstance(quote, ExecutionQuote):
                raise TypeError("quotes values must be ExecutionQuote instances")
            if quote.available_at > asof:
                raise ValueError(
                    f"execution look-ahead detected for {asset.key}: "
                    f"available_at={quote.available_at.isoformat()} > asof={asof.isoformat()}"
                )
        object.__setattr__(self, "asof", asof)
        object.__setattr__(self, "quotes", quotes)
        object.__setattr__(self, "data_version", require_non_empty(self.data_version, "data_version"))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    def price(self, asset: AssetId) -> float:
        try:
            return self.quotes[asset].price
        except KeyError as exc:
            raise KeyError(f"no execution quote for {asset.key}") from exc

    def volume(self, asset: AssetId) -> float:
        try:
            return self.quotes[asset].volume
        except KeyError as exc:
            raise KeyError(f"no execution quote for {asset.key}") from exc


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
