from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeAlias


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: str, field_name: str) -> str:
    rendered = value.strip()
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _finite(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _positive(value: float, field_name: str) -> float:
    rendered = _finite(value, field_name)
    if rendered <= 0:
        raise ValueError(f"{field_name} must be positive")
    return rendered


def _non_negative(value: float, field_name: str) -> float:
    rendered = _finite(value, field_name)
    if rendered < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return rendered


class RealtimeEventKind(StrEnum):
    QUOTE = "QUOTE"
    BAR = "BAR"
    MARKET_STATUS = "MARKET_STATUS"
    ACCOUNT_STATUS = "ACCOUNT_STATUS"
    ORDER = "ORDER"
    TRADE = "TRADE"
    ORDER_ERROR = "ORDER_ERROR"
    CONNECTION = "CONNECTION"


class MarketSessionStatus(StrEnum):
    PREOPEN = "PREOPEN"
    OPEN = "OPEN"
    HALTED = "HALTED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class ConnectionStatus(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"


class OrderLifecycleStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True, kw_only=True)
class RealtimeEvent:
    source: str
    source_event_id: str
    event_time: datetime
    received_at: datetime
    sequence: int
    schema_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(
            self,
            "source_event_id",
            _text(self.source_event_id, "source_event_id"),
        )
        object.__setattr__(self, "event_time", _aware(self.event_time, "event_time"))
        object.__setattr__(self, "received_at", _aware(self.received_at, "received_at"))
        if self.sequence < 0:
            raise ValueError("sequence must be >= 0")
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    @property
    def kind(self) -> RealtimeEventKind:
        raise NotImplementedError

    @property
    def event_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="realtime-event")

    @property
    def source_key(self) -> str:
        return f"{self.source}:{self.source_event_id}"

    @property
    def latency_seconds(self) -> float:
        return (self.received_at - self.event_time).total_seconds()

    def payload_dict(self) -> dict[str, object]:
        raise NotImplementedError

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "source": self.source,
            "source_event_id": self.source_event_id,
            "event_time": self.event_time.isoformat(),
            "received_at": self.received_at.isoformat(),
            "sequence": self.sequence,
            "payload": self.payload_dict(),
        }
        if include_id:
            payload["event_id"] = self.event_id
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteEvent(RealtimeEvent):
    symbol: str
    bid: float
    ask: float
    last: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    schema_version: str = "finagent.realtime-quote-event.v1"

    def __post_init__(self) -> None:
        super(QuoteEvent, self).__post_init__()
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "bid", _non_negative(self.bid, "bid"))
        object.__setattr__(self, "ask", _non_negative(self.ask, "ask"))
        if self.bid > 0 and self.ask > 0 and self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        if self.last is not None:
            object.__setattr__(self, "last", _non_negative(self.last, "last"))
        if self.bid_size is not None:
            object.__setattr__(self, "bid_size", _non_negative(self.bid_size, "bid_size"))
        if self.ask_size is not None:
            object.__setattr__(self, "ask_size", _non_negative(self.ask_size, "ask_size"))

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.QUOTE

    def payload_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BarEvent(RealtimeEvent):
    symbol: str
    interval_seconds: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete: bool
    schema_version: str = "finagent.realtime-bar-event.v1"

    def __post_init__(self) -> None:
        super(BarEvent, self).__post_init__()
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        for field_name in ("open", "high", "low", "close"):
            object.__setattr__(
                self,
                field_name,
                _positive(float(getattr(self, field_name)), field_name),
            )
        object.__setattr__(self, "volume", _non_negative(self.volume, "volume"))
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high is inconsistent")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("bar low is inconsistent")

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.BAR

    def payload_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "interval_seconds": self.interval_seconds,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketStatusEvent(RealtimeEvent):
    market: str
    status: MarketSessionStatus
    schema_version: str = "finagent.realtime-market-status-event.v1"

    def __post_init__(self) -> None:
        super(MarketStatusEvent, self).__post_init__()
        object.__setattr__(self, "market", _text(self.market, "market"))

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.MARKET_STATUS

    def payload_dict(self) -> dict[str, object]:
        return {"market": self.market, "status": self.status.value}


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountStatusEvent(RealtimeEvent):
    account_id: str
    balance: float
    equity: float
    margin_used: float
    free_margin: float
    currency: str
    schema_version: str = "finagent.realtime-account-status-event.v1"

    def __post_init__(self) -> None:
        super(AccountStatusEvent, self).__post_init__()
        object.__setattr__(self, "account_id", _text(self.account_id, "account_id"))
        object.__setattr__(self, "balance", _finite(self.balance, "balance"))
        object.__setattr__(self, "equity", _finite(self.equity, "equity"))
        object.__setattr__(self, "margin_used", _non_negative(self.margin_used, "margin_used"))
        object.__setattr__(self, "free_margin", _finite(self.free_margin, "free_margin"))
        object.__setattr__(self, "currency", _text(self.currency, "currency").upper())

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.ACCOUNT_STATUS

    def payload_dict(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "balance": self.balance,
            "equity": self.equity,
            "margin_used": self.margin_used,
            "free_margin": self.free_margin,
            "currency": self.currency,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderEvent(RealtimeEvent):
    client_order_id: str
    broker_order_id: str | None
    symbol: str
    side: OrderSide
    requested_lots: float
    filled_lots: float
    status: OrderLifecycleStatus
    schema_version: str = "finagent.realtime-order-event.v1"

    def __post_init__(self) -> None:
        super(OrderEvent, self).__post_init__()
        object.__setattr__(
            self,
            "client_order_id",
            _text(self.client_order_id, "client_order_id"),
        )
        if self.broker_order_id is not None:
            object.__setattr__(
                self,
                "broker_order_id",
                _text(self.broker_order_id, "broker_order_id"),
            )
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(
            self,
            "requested_lots",
            _positive(self.requested_lots, "requested_lots"),
        )
        object.__setattr__(
            self,
            "filled_lots",
            _non_negative(self.filled_lots, "filled_lots"),
        )
        if self.filled_lots > self.requested_lots + 1e-12:
            raise ValueError("filled_lots cannot exceed requested_lots")

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.ORDER

    def payload_dict(self) -> dict[str, object]:
        return {
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "requested_lots": self.requested_lots,
            "filled_lots": self.filled_lots,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TradeEvent(RealtimeEvent):
    client_order_id: str
    broker_order_id: str | None
    broker_deal_id: str
    symbol: str
    side: OrderSide
    lots: float
    price: float
    commission: float = 0.0
    schema_version: str = "finagent.realtime-trade-event.v1"

    def __post_init__(self) -> None:
        super(TradeEvent, self).__post_init__()
        object.__setattr__(
            self,
            "client_order_id",
            _text(self.client_order_id, "client_order_id"),
        )
        if self.broker_order_id is not None:
            object.__setattr__(
                self,
                "broker_order_id",
                _text(self.broker_order_id, "broker_order_id"),
            )
        object.__setattr__(
            self,
            "broker_deal_id",
            _text(self.broker_deal_id, "broker_deal_id"),
        )
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "lots", _positive(self.lots, "lots"))
        object.__setattr__(self, "price", _positive(self.price, "price"))
        object.__setattr__(self, "commission", _non_negative(self.commission, "commission"))

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.TRADE

    def payload_dict(self) -> dict[str, object]:
        return {
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "broker_deal_id": self.broker_deal_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "lots": self.lots,
            "price": self.price,
            "commission": self.commission,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderErrorEvent(RealtimeEvent):
    client_order_id: str
    symbol: str
    code: str
    message: str
    retryable: bool
    schema_version: str = "finagent.realtime-order-error-event.v1"

    def __post_init__(self) -> None:
        super(OrderErrorEvent, self).__post_init__()
        object.__setattr__(
            self,
            "client_order_id",
            _text(self.client_order_id, "client_order_id"),
        )
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "code", _text(self.code, "code"))
        object.__setattr__(self, "message", _text(self.message, "message"))

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.ORDER_ERROR

    def payload_dict(self) -> dict[str, object]:
        return {
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectionEvent(RealtimeEvent):
    connection_id: str
    status: ConnectionStatus
    reason: str = ""
    schema_version: str = "finagent.realtime-connection-event.v1"

    def __post_init__(self) -> None:
        super(ConnectionEvent, self).__post_init__()
        object.__setattr__(
            self,
            "connection_id",
            _text(self.connection_id, "connection_id"),
        )
        object.__setattr__(self, "reason", self.reason.strip())

    @property
    def kind(self) -> RealtimeEventKind:
        return RealtimeEventKind.CONNECTION

    def payload_dict(self) -> dict[str, object]:
        return {
            "connection_id": self.connection_id,
            "status": self.status.value,
            "reason": self.reason,
        }


CanonicalRealtimeEvent: TypeAlias = (
    QuoteEvent
    | BarEvent
    | MarketStatusEvent
    | AccountStatusEvent
    | OrderEvent
    | TradeEvent
    | OrderErrorEvent
    | ConnectionEvent
)
