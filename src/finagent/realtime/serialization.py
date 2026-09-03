from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from finagent.realtime.events import (
    AccountStatusEvent,
    BarEvent,
    CanonicalRealtimeEvent,
    ConnectionEvent,
    ConnectionStatus,
    MarketSessionStatus,
    MarketStatusEvent,
    OrderErrorEvent,
    OrderEvent,
    OrderLifecycleStatus,
    OrderSide,
    QuoteEvent,
    RealtimeEventKind,
    TradeEvent,
)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    return int(value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _optional_number(value: object, field_name: str) -> float | None:
    return None if value is None else _number(value, field_name)


def _optional_text(value: object, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name)


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def realtime_event_from_dict(document: Mapping[str, object]) -> CanonicalRealtimeEvent:
    kind = RealtimeEventKind(_text(document.get("kind"), "event.kind"))
    payload = _mapping(document.get("payload"), "event.payload")
    common: dict[str, object] = {
        "source": _text(document.get("source"), "event.source"),
        "source_event_id": _text(
            document.get("source_event_id"),
            "event.source_event_id",
        ),
        "event_time": _datetime(document.get("event_time"), "event.event_time"),
        "received_at": _datetime(document.get("received_at"), "event.received_at"),
        "sequence": _integer(document.get("sequence"), "event.sequence"),
    }
    if kind is RealtimeEventKind.QUOTE:
        event: CanonicalRealtimeEvent = QuoteEvent(
            **common,
            symbol=_text(payload.get("symbol"), "quote.symbol"),
            bid=_number(payload.get("bid"), "quote.bid"),
            ask=_number(payload.get("ask"), "quote.ask"),
            last=_optional_number(payload.get("last"), "quote.last"),
            bid_size=_optional_number(payload.get("bid_size"), "quote.bid_size"),
            ask_size=_optional_number(payload.get("ask_size"), "quote.ask_size"),
        )
    elif kind is RealtimeEventKind.BAR:
        event = BarEvent(
            **common,
            symbol=_text(payload.get("symbol"), "bar.symbol"),
            interval_seconds=_integer(
                payload.get("interval_seconds"),
                "bar.interval_seconds",
            ),
            open=_number(payload.get("open"), "bar.open"),
            high=_number(payload.get("high"), "bar.high"),
            low=_number(payload.get("low"), "bar.low"),
            close=_number(payload.get("close"), "bar.close"),
            volume=_number(payload.get("volume"), "bar.volume"),
            complete=_boolean(payload.get("complete"), "bar.complete"),
        )
    elif kind is RealtimeEventKind.MARKET_STATUS:
        event = MarketStatusEvent(
            **common,
            market=_text(payload.get("market"), "market_status.market"),
            status=MarketSessionStatus(
                _text(payload.get("status"), "market_status.status")
            ),
        )
    elif kind is RealtimeEventKind.ACCOUNT_STATUS:
        event = AccountStatusEvent(
            **common,
            account_id=_text(payload.get("account_id"), "account.account_id"),
            balance=_number(payload.get("balance"), "account.balance"),
            equity=_number(payload.get("equity"), "account.equity"),
            margin_used=_number(payload.get("margin_used"), "account.margin_used"),
            free_margin=_number(payload.get("free_margin"), "account.free_margin"),
            currency=_text(payload.get("currency"), "account.currency"),
        )
    elif kind is RealtimeEventKind.ORDER:
        event = OrderEvent(
            **common,
            client_order_id=_text(
                payload.get("client_order_id"),
                "order.client_order_id",
            ),
            broker_order_id=_optional_text(
                payload.get("broker_order_id"),
                "order.broker_order_id",
            ),
            symbol=_text(payload.get("symbol"), "order.symbol"),
            side=OrderSide(_text(payload.get("side"), "order.side")),
            requested_lots=_number(
                payload.get("requested_lots"),
                "order.requested_lots",
            ),
            filled_lots=_number(payload.get("filled_lots"), "order.filled_lots"),
            status=OrderLifecycleStatus(
                _text(payload.get("status"), "order.status")
            ),
        )
    elif kind is RealtimeEventKind.TRADE:
        event = TradeEvent(
            **common,
            client_order_id=_text(
                payload.get("client_order_id"),
                "trade.client_order_id",
            ),
            broker_order_id=_optional_text(
                payload.get("broker_order_id"),
                "trade.broker_order_id",
            ),
            broker_deal_id=_text(
                payload.get("broker_deal_id"),
                "trade.broker_deal_id",
            ),
            symbol=_text(payload.get("symbol"), "trade.symbol"),
            side=OrderSide(_text(payload.get("side"), "trade.side")),
            lots=_number(payload.get("lots"), "trade.lots"),
            price=_number(payload.get("price"), "trade.price"),
            commission=_number(payload.get("commission"), "trade.commission"),
        )
    elif kind is RealtimeEventKind.ORDER_ERROR:
        event = OrderErrorEvent(
            **common,
            client_order_id=_text(
                payload.get("client_order_id"),
                "order_error.client_order_id",
            ),
            symbol=_text(payload.get("symbol"), "order_error.symbol"),
            code=_text(payload.get("code"), "order_error.code"),
            message=_text(payload.get("message"), "order_error.message"),
            retryable=_boolean(payload.get("retryable"), "order_error.retryable"),
        )
    elif kind is RealtimeEventKind.CONNECTION:
        event = ConnectionEvent(
            **common,
            connection_id=_text(
                payload.get("connection_id"),
                "connection.connection_id",
            ),
            status=ConnectionStatus(
                _text(payload.get("status"), "connection.status")
            ),
            reason=str(payload.get("reason", "")),
        )
    else:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"unsupported realtime event kind: {kind}")

    schema = _text(document.get("schema_version"), "event.schema_version")
    if schema != event.schema_version:
        raise ValueError("realtime event schema_version mismatch")
    stored_id = _text(document.get("event_id"), "event.event_id")
    if stored_id != event.event_id:
        raise ValueError("realtime event content identity mismatch")
    return event
