from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.realtime.events import (
    AccountStatusEvent,
    BarEvent,
    CanonicalRealtimeEvent,
    ConnectionEvent,
    MarketStatusEvent,
    OrderErrorEvent,
    OrderEvent,
    OrderSide,
    QuoteEvent,
    RealtimeEvent,
    TradeEvent,
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _newer(candidate: RealtimeEvent, current: RealtimeEvent) -> bool:
    return (
        candidate.event_time,
        candidate.sequence,
        candidate.received_at,
        candidate.event_id,
    ) > (
        current.event_time,
        current.sequence,
        current.received_at,
        current.event_id,
    )


@dataclass(frozen=True, slots=True)
class RealtimeProjectionConfig:
    stale_after_seconds: float = 60.0
    maximum_future_skew_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if self.maximum_future_skew_seconds < 0:
            raise ValueError("maximum_future_skew_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class RealtimeProjectionSnapshot:
    quotes: tuple[tuple[str, dict[str, object]], ...]
    bars: tuple[tuple[str, dict[str, object]], ...]
    market_statuses: tuple[tuple[str, dict[str, object]], ...]
    accounts: tuple[tuple[str, dict[str, object]], ...]
    orders: tuple[tuple[str, dict[str, object]], ...]
    trades: tuple[tuple[str, dict[str, object]], ...]
    order_errors: tuple[tuple[str, dict[str, object]], ...]
    connections: tuple[tuple[str, dict[str, object]], ...]
    portfolio_lots: tuple[tuple[str, float], ...]
    applied_event_count: int
    duplicate_event_count: int
    out_of_order_event_count: int
    stale_event_count: int
    future_event_count: int
    last_sequence_by_source: tuple[tuple[str, int], ...]
    event_log_digest: str
    schema_version: str = "finagent.realtime-projection-snapshot.v1"

    def _semantic_payload(self) -> dict[str, object]:
        return {
            "quotes": [[key, value] for key, value in self.quotes],
            "bars": [[key, value] for key, value in self.bars],
            "market_statuses": [[key, value] for key, value in self.market_statuses],
            "accounts": [[key, value] for key, value in self.accounts],
            "orders": [[key, value] for key, value in self.orders],
            "trades": [[key, value] for key, value in self.trades],
            "order_errors": [[key, value] for key, value in self.order_errors],
            "connections": [[key, value] for key, value in self.connections],
            "portfolio_lots": [[key, value] for key, value in self.portfolio_lots],
        }

    @property
    def semantic_state_id(self) -> str:
        return _canonical_hash(self._semantic_payload(), prefix="realtime-semantic-state")

    @property
    def snapshot_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="realtime-projection")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            **self._semantic_payload(),
            "applied_event_count": self.applied_event_count,
            "duplicate_event_count": self.duplicate_event_count,
            "out_of_order_event_count": self.out_of_order_event_count,
            "stale_event_count": self.stale_event_count,
            "future_event_count": self.future_event_count,
            "last_sequence_by_source": [
                [source, sequence] for source, sequence in self.last_sequence_by_source
            ],
            "event_log_digest": self.event_log_digest,
            "semantic_state_id": self.semantic_state_id,
            "replay_reconstructable": True,
            "market_data_authority": False,
            "broker_account_authority": False,
            "execution_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


class RealtimeProjector:
    """Idempotent reducer for canonical realtime events.

    Exact duplicate event IDs are ignored for semantic state but counted in health diagnostics.
    Reuse of one `(source, source_event_id)` with different content fails closed. Sequence
    regressions are recorded as out-of-order diagnostics; older market/account/order events do
    not overwrite newer semantic state.
    """

    def __init__(self, config: RealtimeProjectionConfig | None = None) -> None:
        self._config = config or RealtimeProjectionConfig()
        self._seen_event_ids: set[str] = set()
        self._source_keys: dict[str, str] = {}
        self._applied_event_ids: list[str] = []
        self._last_sequence_by_source: dict[str, int] = {}
        self._duplicate_event_count = 0
        self._out_of_order_event_count = 0
        self._stale_event_count = 0
        self._future_event_count = 0
        self._quotes: dict[str, QuoteEvent] = {}
        self._bars: dict[str, BarEvent] = {}
        self._market_statuses: dict[str, MarketStatusEvent] = {}
        self._accounts: dict[str, AccountStatusEvent] = {}
        self._orders: dict[str, OrderEvent] = {}
        self._trades: dict[str, TradeEvent] = {}
        self._order_errors: dict[str, OrderErrorEvent] = {}
        self._connections: dict[str, ConnectionEvent] = {}
        self._portfolio_lots: dict[str, float] = {}

    def apply(self, event: CanonicalRealtimeEvent) -> bool:
        if event.event_id in self._seen_event_ids:
            self._duplicate_event_count += 1
            return False
        existing_event_id = self._source_keys.get(event.source_key)
        if existing_event_id is not None and existing_event_id != event.event_id:
            raise ValueError(
                "source_event_id conflict: identical provider identity has different content"
            )

        previous_sequence = self._last_sequence_by_source.get(event.source)
        if previous_sequence is not None and event.sequence <= previous_sequence:
            self._out_of_order_event_count += 1
        self._last_sequence_by_source[event.source] = max(
            event.sequence,
            previous_sequence if previous_sequence is not None else event.sequence,
        )
        if event.latency_seconds > self._config.stale_after_seconds:
            self._stale_event_count += 1
        if event.latency_seconds < -self._config.maximum_future_skew_seconds:
            self._future_event_count += 1

        self._seen_event_ids.add(event.event_id)
        self._source_keys[event.source_key] = event.event_id
        self._applied_event_ids.append(event.event_id)
        self._reduce(event)
        return True

    def apply_all(self, events: tuple[CanonicalRealtimeEvent, ...]) -> int:
        applied = 0
        for event in events:
            if self.apply(event):
                applied += 1
        return applied

    def _reduce(self, event: CanonicalRealtimeEvent) -> None:
        if isinstance(event, QuoteEvent):
            current_quote = self._quotes.get(event.symbol)
            if current_quote is None or _newer(event, current_quote):
                self._quotes[event.symbol] = event
            return
        if isinstance(event, BarEvent):
            key = f"{event.symbol}:{event.interval_seconds}"
            current_bar = self._bars.get(key)
            if current_bar is None or _newer(event, current_bar):
                self._bars[key] = event
            return
        if isinstance(event, MarketStatusEvent):
            current_market_status = self._market_statuses.get(event.market)
            if current_market_status is None or _newer(event, current_market_status):
                self._market_statuses[event.market] = event
            return
        if isinstance(event, AccountStatusEvent):
            current_account = self._accounts.get(event.account_id)
            if current_account is None or _newer(event, current_account):
                self._accounts[event.account_id] = event
            return
        if isinstance(event, OrderEvent):
            current_order = self._orders.get(event.client_order_id)
            if current_order is None or _newer(event, current_order):
                self._orders[event.client_order_id] = event
            return
        if isinstance(event, TradeEvent):
            existing_trade = self._trades.get(event.broker_deal_id)
            if existing_trade is not None and existing_trade.event_id != event.event_id:
                raise ValueError("broker_deal_id conflict")
            if existing_trade is None:
                self._trades[event.broker_deal_id] = event
                sign = 1.0 if event.side is OrderSide.BUY else -1.0
                self._portfolio_lots[event.symbol] = (
                    self._portfolio_lots.get(event.symbol, 0.0) + sign * event.lots
                )
                if abs(self._portfolio_lots[event.symbol]) <= 1e-12:
                    self._portfolio_lots.pop(event.symbol)
            return
        if isinstance(event, OrderErrorEvent):
            current_order_error = self._order_errors.get(event.client_order_id)
            if current_order_error is None or _newer(event, current_order_error):
                self._order_errors[event.client_order_id] = event
            return
        if isinstance(event, ConnectionEvent):
            current_connection = self._connections.get(event.connection_id)
            if current_connection is None or _newer(event, current_connection):
                self._connections[event.connection_id] = event
            return
        raise TypeError(f"unsupported canonical realtime event: {type(event).__name__}")

    def snapshot(self) -> RealtimeProjectionSnapshot:
        event_log_digest = _canonical_hash(
            self._applied_event_ids,
            prefix="realtime-event-log",
        )
        return RealtimeProjectionSnapshot(
            quotes=tuple(
                (key, event.to_dict()) for key, event in sorted(self._quotes.items())
            ),
            bars=tuple((key, event.to_dict()) for key, event in sorted(self._bars.items())),
            market_statuses=tuple(
                (key, event.to_dict())
                for key, event in sorted(self._market_statuses.items())
            ),
            accounts=tuple(
                (key, event.to_dict()) for key, event in sorted(self._accounts.items())
            ),
            orders=tuple((key, event.to_dict()) for key, event in sorted(self._orders.items())),
            trades=tuple((key, event.to_dict()) for key, event in sorted(self._trades.items())),
            order_errors=tuple(
                (key, event.to_dict())
                for key, event in sorted(self._order_errors.items())
            ),
            connections=tuple(
                (key, event.to_dict())
                for key, event in sorted(self._connections.items())
            ),
            portfolio_lots=tuple(sorted(self._portfolio_lots.items())),
            applied_event_count=len(self._applied_event_ids),
            duplicate_event_count=self._duplicate_event_count,
            out_of_order_event_count=self._out_of_order_event_count,
            stale_event_count=self._stale_event_count,
            future_event_count=self._future_event_count,
            last_sequence_by_source=tuple(sorted(self._last_sequence_by_source.items())),
            event_log_digest=event_log_digest,
        )


def rebuild_projection(
    events: tuple[CanonicalRealtimeEvent, ...],
    *,
    config: RealtimeProjectionConfig | None = None,
) -> RealtimeProjectionSnapshot:
    projector = RealtimeProjector(config)
    projector.apply_all(events)
    return projector.snapshot()
