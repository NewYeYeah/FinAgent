from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from finagent.realtime.events import (
    AccountStatusEvent,
    CanonicalRealtimeEvent,
    OrderErrorEvent,
    OrderEvent,
    OrderLifecycleStatus,
    OrderSide,
    QuoteEvent,
    TradeEvent,
)
from finagent.realtime.projections import RealtimeProjectionSnapshot
from finagent.realtime.serialization import realtime_event_from_dict


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


def _positive(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered) or rendered <= 0:
        raise ValueError(f"{field_name} must be positive and finite")
    return rendered


def _non_negative(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered) or rendered < 0:
        raise ValueError(f"{field_name} must be non-negative and finite")
    return rendered


def _finite(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


class OrderCommandPort(Protocol):
    def submit(
        self,
        command: MT5PaperOrderCommand,
        *,
        at: datetime,
    ) -> tuple[CanonicalRealtimeEvent, ...]: ...

    def cancel(
        self,
        client_order_id: str,
        *,
        at: datetime,
    ) -> tuple[CanonicalRealtimeEvent, ...]: ...


class BrokerEventSource(Protocol):
    def events(self) -> tuple[CanonicalRealtimeEvent, ...]: ...


class BrokerQueryPort(Protocol):
    def snapshot(self) -> MT5PaperBrokerSnapshot: ...


class MT5PaperReconciliationState(StrEnum):
    CONSISTENT = "CONSISTENT"
    DRIFT = "DRIFT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MT5PaperExecutionPolicy:
    account_id: str = "mt5-paper-replay"
    source: str = "mt5.paper.replay"
    maximum_quote_age_seconds: float = 60.0
    maximum_future_quote_skew_seconds: float = 5.0
    maximum_order_notional: float = 100_000.0
    maximum_gross_notional: float = 500_000.0
    maximum_daily_loss_fraction: float = 0.05
    allow_short: bool = True
    schema_version: str = "finagent.mt5-paper-execution-policy.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _text(self.account_id, "account_id"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        if self.maximum_quote_age_seconds <= 0:
            raise ValueError("maximum_quote_age_seconds must be positive")
        if self.maximum_future_quote_skew_seconds < 0:
            raise ValueError("maximum_future_quote_skew_seconds must be non-negative")
        if self.maximum_order_notional <= 0 or self.maximum_gross_notional <= 0:
            raise ValueError("notional limits must be positive")
        if not 0 <= self.maximum_daily_loss_fraction < 1:
            raise ValueError("maximum_daily_loss_fraction must be in [0, 1)")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-paper-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "account_id": self.account_id,
            "source": self.source,
            "maximum_quote_age_seconds": self.maximum_quote_age_seconds,
            "maximum_future_quote_skew_seconds": self.maximum_future_quote_skew_seconds,
            "maximum_order_notional": self.maximum_order_notional,
            "maximum_gross_notional": self.maximum_gross_notional,
            "maximum_daily_loss_fraction": self.maximum_daily_loss_fraction,
            "allow_short": self.allow_short,
            "paper_only": True,
            "order_send_authority": False,
            "live_capital_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5PaperOrderCommand:
    client_order_id: str
    symbol: str
    side: OrderSide
    lots: float
    contract_size: float
    created_at: datetime
    schema_version: str = "finagent.mt5-paper-order-command.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            _text(self.client_order_id, "client_order_id"),
        )
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "lots", _positive(self.lots, "lots"))
        object.__setattr__(
            self,
            "contract_size",
            _positive(self.contract_size, "contract_size"),
        )
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))

    @property
    def command_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-paper-command")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "lots": self.lots,
            "contract_size": self.contract_size,
            "created_at": self.created_at.isoformat(),
        }
        if include_id:
            payload["command_id"] = self.command_id
        return payload

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> MT5PaperOrderCommand:
        schema = str(document.get("schema_version", "")).strip()
        if schema != "finagent.mt5-paper-order-command.v1":
            raise ValueError(f"unsupported MT5 paper order command schema: {schema}")
        command = cls(
            client_order_id=str(document.get("client_order_id", "")),
            symbol=str(document.get("symbol", "")),
            side=OrderSide(str(document.get("side", ""))),
            lots=float(document.get("lots", 0.0)),
            contract_size=float(document.get("contract_size", 0.0)),
            created_at=datetime.fromisoformat(str(document.get("created_at", ""))),
        )
        stored_id = document.get("command_id")
        if stored_id is not None and str(stored_id) != command.command_id:
            raise ValueError("stored MT5 paper command_id does not match command content")
        return command


@dataclass(frozen=True, slots=True)
class MT5PaperOrderRecord:
    client_order_id: str
    command_id: str
    broker_order_id: str | None
    symbol: str
    side: OrderSide
    requested_lots: float
    filled_lots: float
    contract_size: float
    status: OrderLifecycleStatus
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            _text(self.client_order_id, "client_order_id"),
        )
        object.__setattr__(self, "command_id", _text(self.command_id, "command_id"))
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
        object.__setattr__(
            self,
            "contract_size",
            _positive(self.contract_size, "contract_size"),
        )
        object.__setattr__(self, "updated_at", _aware(self.updated_at, "updated_at"))

    @property
    def remaining_lots(self) -> float:
        return max(self.requested_lots - self.filled_lots, 0.0)

    def to_dict(self) -> dict[str, object]:
        return {
            "client_order_id": self.client_order_id,
            "command_id": self.command_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "requested_lots": self.requested_lots,
            "filled_lots": self.filled_lots,
            "contract_size": self.contract_size,
            "status": self.status.value,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class MT5PaperIncident:
    incident_type: str
    at: datetime
    actor: str
    reason: str
    schema_version: str = "finagent.mt5-paper-incident.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "incident_type",
            _text(self.incident_type, "incident_type"),
        )
        object.__setattr__(self, "at", _aware(self.at, "at"))
        object.__setattr__(self, "actor", _text(self.actor, "actor"))
        object.__setattr__(self, "reason", _text(self.reason, "reason"))

    @property
    def incident_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-paper-incident")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "incident_type": self.incident_type,
            "at": self.at.isoformat(),
            "actor": self.actor,
            "reason": self.reason,
        }
        if include_id:
            payload["incident_id"] = self.incident_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5PaperBrokerSnapshot:
    policy_id: str
    orders: tuple[MT5PaperOrderRecord, ...]
    broker_deal_ids: tuple[str, ...]
    positions: tuple[tuple[str, float], ...]
    account_id: str
    session_start_equity: float
    equity: float
    kill_switch_halted: bool
    incident_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    schema_version: str = "finagent.mt5-paper-broker-snapshot.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(self, "account_id", _text(self.account_id, "account_id"))
        object.__setattr__(
            self,
            "session_start_equity",
            _positive(self.session_start_equity, "session_start_equity"),
        )
        object.__setattr__(self, "equity", _finite(self.equity, "equity"))

    @property
    def snapshot_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-paper-snapshot")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "orders": [item.to_dict() for item in self.orders],
            "broker_deal_ids": list(self.broker_deal_ids),
            "positions": [[symbol, lots] for symbol, lots in self.positions],
            "account_id": self.account_id,
            "session_start_equity": self.session_start_equity,
            "equity": self.equity,
            "kill_switch_halted": self.kill_switch_halted,
            "incident_ids": list(self.incident_ids),
            "event_ids": list(self.event_ids),
            "paper_only": True,
            "order_send_authority": False,
            "live_capital_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5PaperReconciliationReport:
    state: MT5PaperReconciliationState
    issues: tuple[str, ...]
    projection_semantic_state_id: str
    broker_snapshot_id: str | None
    generated_at: datetime
    schema_version: str = "finagent.mt5-paper-reconciliation-report.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "projection_semantic_state_id",
            _text(self.projection_semantic_state_id, "projection_semantic_state_id"),
        )
        object.__setattr__(self, "generated_at", _aware(self.generated_at, "generated_at"))
        normalized = tuple(dict.fromkeys(item.strip() for item in self.issues if item.strip()))
        if self.state is MT5PaperReconciliationState.CONSISTENT and normalized:
            raise ValueError("CONSISTENT reconciliation cannot carry issues")
        if self.state is not MT5PaperReconciliationState.CONSISTENT and not normalized:
            raise ValueError("non-consistent reconciliation requires issues")
        object.__setattr__(self, "issues", normalized)

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-paper-reconciliation")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "issues": list(self.issues),
            "projection_semantic_state_id": self.projection_semantic_state_id,
            "broker_snapshot_id": self.broker_snapshot_id,
            "generated_at": self.generated_at.isoformat(),
            "paper_only": True,
            "broker_state_proven": self.state is MT5PaperReconciliationState.CONSISTENT,
            "order_send_authority": False,
            "live_capital_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class MT5PaperReplayBroker(OrderCommandPort, BrokerEventSource, BrokerQueryPort):
    """Replay-first broker lifecycle for MT5-E1/MT5-O1 engineering validation.

    The class deliberately has no MetaTrader5 module dependency and no `order_send` surface.
    Commands are idempotent by client_order_id + content identity. Broker lifecycle events use
    the canonical RT-R0 event contract and can be persisted to/recovered from an append-only
    JSONL journal.
    """

    def __init__(
        self,
        *,
        policy: MT5PaperExecutionPolicy | None = None,
        session_start_equity: float = 100_000.0,
    ) -> None:
        self._policy = policy or MT5PaperExecutionPolicy()
        self._session_start_equity = _positive(
            session_start_equity,
            "session_start_equity",
        )
        self._equity = self._session_start_equity
        self._commands: dict[str, MT5PaperOrderCommand] = {}
        self._orders: dict[str, MT5PaperOrderRecord] = {}
        self._events: list[CanonicalRealtimeEvent] = []
        self._deals: dict[str, TradeEvent] = {}
        self._positions: dict[str, float] = {}
        self._quotes: dict[str, QuoteEvent] = {}
        self._contract_size_by_symbol: dict[str, float] = {}
        self._sequence = 0
        self._broker_order_counter = 0
        self._kill_switch_halted = False
        self._incidents: list[MT5PaperIncident] = []
        self._journal: list[dict[str, object]] = []

    @property
    def policy(self) -> MT5PaperExecutionPolicy:
        return self._policy

    @property
    def kill_switch_halted(self) -> bool:
        return self._kill_switch_halted

    @property
    def incidents(self) -> tuple[MT5PaperIncident, ...]:
        return tuple(self._incidents)

    def observe_quote(self, event: QuoteEvent) -> None:
        current = self._quotes.get(event.symbol)
        if current is None or (
            event.event_time,
            event.received_at,
            event.sequence,
            event.event_id,
        ) > (
            current.event_time,
            current.received_at,
            current.sequence,
            current.event_id,
        ):
            self._quotes[event.symbol] = event

    def _next_sequence(self) -> int:
        value = self._sequence
        self._sequence += 1
        return value

    def _source_event_id(self, payload: Mapping[str, object]) -> str:
        return _canonical_hash(payload, prefix="mt5-paper-source-event")

    def _append_event(self, event: CanonicalRealtimeEvent) -> None:
        self._events.append(event)
        self._journal.append({"type": "event", "document": event.to_dict()})

    def _record_command(self, command: MT5PaperOrderCommand) -> None:
        self._commands[command.client_order_id] = command
        self._journal.append({"type": "command", "document": command.to_dict()})

    def _record_incident(self, incident: MT5PaperIncident) -> None:
        self._incidents.append(incident)
        self._journal.append({"type": "incident", "document": incident.to_dict()})

    def _order_event(
        self,
        record: MT5PaperOrderRecord,
        *,
        status: OrderLifecycleStatus,
        at: datetime,
        transition: str,
    ) -> OrderEvent:
        timestamp = _aware(at, "at")
        return OrderEvent(
            source=self._policy.source,
            source_event_id=self._source_event_id(
                {
                    "transition": transition,
                    "client_order_id": record.client_order_id,
                    "broker_order_id": record.broker_order_id,
                    "status": status.value,
                    "filled_lots": record.filled_lots,
                    "at": timestamp.isoformat(),
                }
            ),
            event_time=timestamp,
            received_at=timestamp,
            sequence=self._next_sequence(),
            client_order_id=record.client_order_id,
            broker_order_id=record.broker_order_id,
            symbol=record.symbol,
            side=record.side,
            requested_lots=record.requested_lots,
            filled_lots=record.filled_lots,
            status=status,
        )

    def _reject_new_command(
        self,
        command: MT5PaperOrderCommand,
        *,
        at: datetime,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> tuple[CanonicalRealtimeEvent, ...]:
        timestamp = _aware(at, "at")
        record = MT5PaperOrderRecord(
            client_order_id=command.client_order_id,
            command_id=command.command_id,
            broker_order_id=None,
            symbol=command.symbol,
            side=command.side,
            requested_lots=command.lots,
            filled_lots=0.0,
            contract_size=command.contract_size,
            status=OrderLifecycleStatus.REJECTED,
            updated_at=timestamp,
        )
        self._orders[command.client_order_id] = record
        error = OrderErrorEvent(
            source=self._policy.source,
            source_event_id=self._source_event_id(
                {
                    "transition": "REJECT_ERROR",
                    "client_order_id": command.client_order_id,
                    "code": code,
                    "at": timestamp.isoformat(),
                }
            ),
            event_time=timestamp,
            received_at=timestamp,
            sequence=self._next_sequence(),
            client_order_id=command.client_order_id,
            symbol=command.symbol,
            code=code,
            message=message,
            retryable=retryable,
        )
        rejected = self._order_event(
            record,
            status=OrderLifecycleStatus.REJECTED,
            at=timestamp,
            transition="REJECTED",
        )
        self._append_event(error)
        self._append_event(rejected)
        return (error, rejected)

    def _latest_midpoint(self, symbol: str, *, at: datetime) -> tuple[float | None, str | None]:
        quote = self._quotes.get(symbol)
        if quote is None:
            return None, "quote:missing"
        timestamp = _aware(at, "at")
        age = (timestamp - quote.event_time).total_seconds()
        if age > self._policy.maximum_quote_age_seconds:
            return None, "quote:stale"
        if age < -self._policy.maximum_future_quote_skew_seconds:
            return None, "quote:future"
        if quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid:
            return None, "quote:invalid_bid_ask"
        return (quote.bid + quote.ask) / 2.0, None

    def _gross_notional(self, *, at: datetime) -> float | None:
        total = 0.0
        for symbol, lots in self._positions.items():
            midpoint, blocker = self._latest_midpoint(symbol, at=at)
            if blocker is not None or midpoint is None:
                return None
            contract_size = self._contract_size_by_symbol.get(symbol)
            if contract_size is None:
                return None
            total += abs(lots) * contract_size * midpoint
        return total

    def _command_blocker(
        self,
        command: MT5PaperOrderCommand,
        *,
        at: datetime,
    ) -> tuple[str, str] | None:
        if self._kill_switch_halted:
            return "KILL_SWITCH_HALTED", "kill switch is halted"
        if self._session_start_equity <= 0:
            return "INVALID_SESSION_EQUITY", "session start equity is invalid"
        loss_fraction = max(
            (self._session_start_equity - self._equity) / self._session_start_equity,
            0.0,
        )
        if loss_fraction > self._policy.maximum_daily_loss_fraction:
            return "DAILY_LOSS_LIMIT", "daily loss limit exceeded"
        midpoint, quote_blocker = self._latest_midpoint(command.symbol, at=at)
        if quote_blocker is not None or midpoint is None:
            return "QUOTE_GATE", quote_blocker or "quote unavailable"
        order_notional = command.lots * command.contract_size * midpoint
        if order_notional > self._policy.maximum_order_notional:
            return "ORDER_NOTIONAL_LIMIT", "order notional exceeds policy limit"
        gross = self._gross_notional(at=at)
        if gross is None:
            return "GROSS_NOTIONAL_UNKNOWN", "gross notional cannot be proven from fresh quotes"
        current = self._positions.get(command.symbol, 0.0)
        signed = command.lots if command.side is OrderSide.BUY else -command.lots
        proposed_symbol = current + signed
        if not self._policy.allow_short and proposed_symbol < -1e-12:
            return "SHORT_NOT_ALLOWED", "policy does not allow short exposure"
        current_symbol_notional = abs(current) * command.contract_size * midpoint
        proposed_symbol_notional = abs(proposed_symbol) * command.contract_size * midpoint
        proposed_gross = gross - current_symbol_notional + proposed_symbol_notional
        if proposed_gross > self._policy.maximum_gross_notional:
            return "GROSS_NOTIONAL_LIMIT", "proposed gross notional exceeds policy limit"
        return None

    def submit(
        self,
        command: MT5PaperOrderCommand,
        *,
        at: datetime,
    ) -> tuple[CanonicalRealtimeEvent, ...]:
        timestamp = _aware(at, "at")
        existing_command = self._commands.get(command.client_order_id)
        if existing_command is not None:
            if existing_command.command_id != command.command_id:
                raise ValueError(
                    "client_order_id conflict: same client identity has different command content"
                )
            return ()
        existing_contract_size = self._contract_size_by_symbol.get(command.symbol)
        if (
            existing_contract_size is not None
            and existing_contract_size != command.contract_size
        ):
            raise ValueError("contract_size changed for one symbol inside the PAPER session")
        self._contract_size_by_symbol[command.symbol] = command.contract_size
        self._record_command(command)
        blocker = self._command_blocker(command, at=timestamp)
        if blocker is not None:
            return self._reject_new_command(
                command,
                at=timestamp,
                code=blocker[0],
                message=blocker[1],
            )

        self._broker_order_counter += 1
        broker_order_id = f"paper-order-{self._broker_order_counter:06d}"
        submitted_record = MT5PaperOrderRecord(
            client_order_id=command.client_order_id,
            command_id=command.command_id,
            broker_order_id=broker_order_id,
            symbol=command.symbol,
            side=command.side,
            requested_lots=command.lots,
            filled_lots=0.0,
            contract_size=command.contract_size,
            status=OrderLifecycleStatus.SUBMITTED,
            updated_at=timestamp,
        )
        submitted = self._order_event(
            submitted_record,
            status=OrderLifecycleStatus.SUBMITTED,
            at=timestamp,
            transition="SUBMITTED",
        )
        acknowledged_record = MT5PaperOrderRecord(
            client_order_id=command.client_order_id,
            command_id=command.command_id,
            broker_order_id=broker_order_id,
            symbol=command.symbol,
            side=command.side,
            requested_lots=command.lots,
            filled_lots=0.0,
            contract_size=command.contract_size,
            status=OrderLifecycleStatus.ACKNOWLEDGED,
            updated_at=timestamp,
        )
        acknowledged = self._order_event(
            acknowledged_record,
            status=OrderLifecycleStatus.ACKNOWLEDGED,
            at=timestamp,
            transition="ACKNOWLEDGED",
        )
        self._orders[command.client_order_id] = acknowledged_record
        self._append_event(submitted)
        self._append_event(acknowledged)
        return (submitted, acknowledged)

    def apply_fill(
        self,
        client_order_id: str,
        *,
        broker_deal_id: str,
        lots: float,
        price: float,
        at: datetime,
        commission: float = 0.0,
    ) -> tuple[CanonicalRealtimeEvent, ...]:
        order_id = _text(client_order_id, "client_order_id")
        deal_id = _text(broker_deal_id, "broker_deal_id")
        fill_lots = _positive(lots, "lots")
        fill_price = _positive(price, "price")
        fill_commission = _non_negative(commission, "commission")
        timestamp = _aware(at, "at")
        existing_deal = self._deals.get(deal_id)
        if existing_deal is not None:
            expected = (
                existing_deal.client_order_id,
                existing_deal.lots,
                existing_deal.price,
                existing_deal.commission,
            )
            candidate = (order_id, fill_lots, fill_price, fill_commission)
            if expected != candidate:
                raise ValueError("broker_deal_id conflict: deal identity has different content")
            return ()
        record = self._orders.get(order_id)
        if record is None:
            raise KeyError(order_id)
        if record.status in {
            OrderLifecycleStatus.REJECTED,
            OrderLifecycleStatus.CANCELLED,
            OrderLifecycleStatus.EXPIRED,
            OrderLifecycleStatus.FILLED,
        }:
            raise ValueError("cannot fill a terminal order")
        if fill_lots > record.remaining_lots + 1e-12:
            raise ValueError("fill exceeds remaining order quantity")

        trade = TradeEvent(
            source=self._policy.source,
            source_event_id=self._source_event_id(
                {
                    "transition": "TRADE",
                    "broker_deal_id": deal_id,
                    "client_order_id": order_id,
                    "lots": fill_lots,
                    "price": fill_price,
                    "commission": fill_commission,
                    "at": timestamp.isoformat(),
                }
            ),
            event_time=timestamp,
            received_at=timestamp,
            sequence=self._next_sequence(),
            client_order_id=order_id,
            broker_order_id=record.broker_order_id,
            broker_deal_id=deal_id,
            symbol=record.symbol,
            side=record.side,
            lots=fill_lots,
            price=fill_price,
            commission=fill_commission,
        )
        new_filled = min(record.filled_lots + fill_lots, record.requested_lots)
        status = (
            OrderLifecycleStatus.FILLED
            if new_filled >= record.requested_lots - 1e-12
            else OrderLifecycleStatus.PARTIALLY_FILLED
        )
        updated = MT5PaperOrderRecord(
            client_order_id=record.client_order_id,
            command_id=record.command_id,
            broker_order_id=record.broker_order_id,
            symbol=record.symbol,
            side=record.side,
            requested_lots=record.requested_lots,
            filled_lots=new_filled,
            contract_size=record.contract_size,
            status=status,
            updated_at=timestamp,
        )
        order_event = self._order_event(
            updated,
            status=status,
            at=timestamp,
            transition=status.value,
        )
        sign = 1.0 if record.side is OrderSide.BUY else -1.0
        self._positions[record.symbol] = self._positions.get(record.symbol, 0.0) + sign * fill_lots
        if abs(self._positions[record.symbol]) <= 1e-12:
            self._positions.pop(record.symbol)
        self._orders[order_id] = updated
        self._deals[deal_id] = trade
        self._append_event(trade)
        self._append_event(order_event)
        return (trade, order_event)

    def reject(
        self,
        client_order_id: str,
        *,
        code: str,
        message: str,
        at: datetime,
        retryable: bool = False,
    ) -> tuple[CanonicalRealtimeEvent, ...]:
        order_id = _text(client_order_id, "client_order_id")
        record = self._orders.get(order_id)
        if record is None:
            raise KeyError(order_id)
        if record.status is OrderLifecycleStatus.REJECTED:
            return ()
        if record.status in {
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.CANCELLED,
            OrderLifecycleStatus.EXPIRED,
        }:
            raise ValueError("cannot reject a terminal non-rejected order")
        timestamp = _aware(at, "at")
        updated = MT5PaperOrderRecord(
            client_order_id=record.client_order_id,
            command_id=record.command_id,
            broker_order_id=record.broker_order_id,
            symbol=record.symbol,
            side=record.side,
            requested_lots=record.requested_lots,
            filled_lots=record.filled_lots,
            contract_size=record.contract_size,
            status=OrderLifecycleStatus.REJECTED,
            updated_at=timestamp,
        )
        error = OrderErrorEvent(
            source=self._policy.source,
            source_event_id=self._source_event_id(
                {
                    "transition": "BROKER_REJECT_ERROR",
                    "client_order_id": order_id,
                    "code": code,
                    "at": timestamp.isoformat(),
                }
            ),
            event_time=timestamp,
            received_at=timestamp,
            sequence=self._next_sequence(),
            client_order_id=order_id,
            symbol=record.symbol,
            code=_text(code, "code"),
            message=_text(message, "message"),
            retryable=retryable,
        )
        rejected = self._order_event(
            updated,
            status=OrderLifecycleStatus.REJECTED,
            at=timestamp,
            transition="BROKER_REJECTED",
        )
        self._orders[order_id] = updated
        self._append_event(error)
        self._append_event(rejected)
        return (error, rejected)

    def _terminal_transition(
        self,
        client_order_id: str,
        *,
        at: datetime,
        status: OrderLifecycleStatus,
    ) -> tuple[CanonicalRealtimeEvent, ...]:
        order_id = _text(client_order_id, "client_order_id")
        record = self._orders.get(order_id)
        if record is None:
            raise KeyError(order_id)
        if record.status is status:
            return ()
        if record.status in {
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.REJECTED,
            OrderLifecycleStatus.CANCELLED,
            OrderLifecycleStatus.EXPIRED,
        }:
            return ()
        timestamp = _aware(at, "at")
        updated = MT5PaperOrderRecord(
            client_order_id=record.client_order_id,
            command_id=record.command_id,
            broker_order_id=record.broker_order_id,
            symbol=record.symbol,
            side=record.side,
            requested_lots=record.requested_lots,
            filled_lots=record.filled_lots,
            contract_size=record.contract_size,
            status=status,
            updated_at=timestamp,
        )
        event = self._order_event(
            updated,
            status=status,
            at=timestamp,
            transition=status.value,
        )
        self._orders[order_id] = updated
        self._append_event(event)
        return (event,)

    def cancel(
        self,
        client_order_id: str,
        *,
        at: datetime,
    ) -> tuple[CanonicalRealtimeEvent, ...]:
        return self._terminal_transition(
            client_order_id,
            at=at,
            status=OrderLifecycleStatus.CANCELLED,
        )

    def expire(
        self,
        client_order_id: str,
        *,
        at: datetime,
    ) -> tuple[CanonicalRealtimeEvent, ...]:
        return self._terminal_transition(
            client_order_id,
            at=at,
            status=OrderLifecycleStatus.EXPIRED,
        )

    def publish_account_status(self, *, at: datetime) -> AccountStatusEvent:
        timestamp = _aware(at, "at")
        event = AccountStatusEvent(
            source=self._policy.source,
            source_event_id=self._source_event_id(
                {
                    "transition": "ACCOUNT_STATUS",
                    "account_id": self._policy.account_id,
                    "equity": self._equity,
                    "at": timestamp.isoformat(),
                }
            ),
            event_time=timestamp,
            received_at=timestamp,
            sequence=self._next_sequence(),
            account_id=self._policy.account_id,
            balance=self._equity,
            equity=self._equity,
            margin_used=0.0,
            free_margin=self._equity,
            currency="USD",
        )
        self._append_event(event)
        return event

    def mark_equity(self, equity: float, *, at: datetime) -> AccountStatusEvent:
        self._equity = _finite(equity, "equity")
        self._journal.append(
            {
                "type": "equity",
                "document": {"equity": self._equity, "at": _aware(at, "at").isoformat()},
            }
        )
        return self.publish_account_status(at=at)

    def trip_kill_switch(
        self,
        *,
        at: datetime,
        reason: str,
        actor: str = "system",
    ) -> MT5PaperIncident:
        timestamp = _aware(at, "at")
        if self._kill_switch_halted:
            return self._incidents[-1]
        self._kill_switch_halted = True
        incident = MT5PaperIncident(
            incident_type="KILL_SWITCH_TRIPPED",
            at=timestamp,
            actor=actor,
            reason=reason,
        )
        self._record_incident(incident)
        return incident

    def reset_kill_switch(
        self,
        *,
        at: datetime,
        actor: str,
        reason: str,
    ) -> MT5PaperIncident:
        timestamp = _aware(at, "at")
        self._kill_switch_halted = False
        incident = MT5PaperIncident(
            incident_type="KILL_SWITCH_RESET",
            at=timestamp,
            actor=actor,
            reason=reason,
        )
        self._record_incident(incident)
        return incident

    def events(self) -> tuple[CanonicalRealtimeEvent, ...]:
        return tuple(self._events)

    def order(self, client_order_id: str) -> MT5PaperOrderRecord:
        return self._orders[_text(client_order_id, "client_order_id")]

    def snapshot(self) -> MT5PaperBrokerSnapshot:
        return MT5PaperBrokerSnapshot(
            policy_id=self._policy.policy_id,
            orders=tuple(self._orders[key] for key in sorted(self._orders)),
            broker_deal_ids=tuple(sorted(self._deals)),
            positions=tuple(sorted(self._positions.items())),
            account_id=self._policy.account_id,
            session_start_equity=self._session_start_equity,
            equity=self._equity,
            kill_switch_halted=self._kill_switch_halted,
            incident_ids=tuple(item.incident_id for item in self._incidents),
            event_ids=tuple(item.event_id for item in self._events),
        )

    def write_journal(self, path: Path) -> None:
        destination = path.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "".join(
                json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
                for record in self._journal
            ),
            encoding="utf-8",
        )

    @classmethod
    def recover_from_journal(
        cls,
        path: Path,
        *,
        policy: MT5PaperExecutionPolicy,
        session_start_equity: float,
    ) -> MT5PaperReplayBroker:
        source = path.expanduser().resolve()
        broker = cls(policy=policy, session_start_equity=session_start_equity)
        if not source.exists():
            raise FileNotFoundError(source)
        records = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for raw in records:
            if not isinstance(raw, Mapping):
                raise TypeError("journal record must be a mapping")
            record_type = str(raw.get("type", "")).strip()
            document = raw.get("document")
            if not isinstance(document, Mapping):
                raise TypeError("journal record document must be a mapping")
            if record_type == "command":
                command = MT5PaperOrderCommand.from_dict(document)
                existing = broker._commands.get(command.client_order_id)
                if existing is not None and existing.command_id != command.command_id:
                    raise ValueError("journal client_order_id conflict")
                broker._commands[command.client_order_id] = command
                broker._contract_size_by_symbol.setdefault(
                    command.symbol,
                    command.contract_size,
                )
            elif record_type == "event":
                event = realtime_event_from_dict(document)
                broker._events.append(event)
                broker._sequence = max(broker._sequence, event.sequence + 1)
                broker._apply_recovered_event(event)
            elif record_type == "incident":
                incident = MT5PaperIncident(
                    incident_type=str(document.get("incident_type", "")),
                    at=datetime.fromisoformat(str(document.get("at", ""))),
                    actor=str(document.get("actor", "")),
                    reason=str(document.get("reason", "")),
                )
                stored_id = document.get("incident_id")
                if stored_id is not None and str(stored_id) != incident.incident_id:
                    raise ValueError("stored incident identity mismatch")
                broker._incidents.append(incident)
                broker._kill_switch_halted = incident.incident_type == "KILL_SWITCH_TRIPPED"
            elif record_type == "equity":
                broker._equity = _finite(float(document.get("equity", 0.0)), "equity")
            else:
                raise ValueError(f"unsupported MT5 paper journal record type: {record_type}")
            broker._journal.append(dict(raw))
        broker._broker_order_counter = max(
            (
                int(record.broker_order_id.rsplit("-", 1)[1])
                for record in broker._orders.values()
                if record.broker_order_id is not None
                and record.broker_order_id.startswith("paper-order-")
            ),
            default=0,
        )
        return broker

    def _apply_recovered_event(self, event: CanonicalRealtimeEvent) -> None:
        if isinstance(event, OrderEvent):
            command = self._commands.get(event.client_order_id)
            if command is None:
                raise ValueError("journal order event has no preceding command record")
            self._orders[event.client_order_id] = MT5PaperOrderRecord(
                client_order_id=event.client_order_id,
                command_id=command.command_id,
                broker_order_id=event.broker_order_id,
                symbol=event.symbol,
                side=event.side,
                requested_lots=event.requested_lots,
                filled_lots=event.filled_lots,
                contract_size=command.contract_size,
                status=event.status,
                updated_at=event.event_time,
            )
        elif isinstance(event, TradeEvent):
            existing = self._deals.get(event.broker_deal_id)
            if existing is not None and existing.event_id != event.event_id:
                raise ValueError("journal broker_deal_id conflict")
            if existing is None:
                self._deals[event.broker_deal_id] = event
                sign = 1.0 if event.side is OrderSide.BUY else -1.0
                self._positions[event.symbol] = self._positions.get(event.symbol, 0.0) + sign * event.lots
                if abs(self._positions[event.symbol]) <= 1e-12:
                    self._positions.pop(event.symbol)
        elif isinstance(event, AccountStatusEvent):
            if event.account_id == self._policy.account_id:
                self._equity = event.equity


def reconcile_mt5_paper_projection(
    projection: RealtimeProjectionSnapshot,
    broker_snapshot: MT5PaperBrokerSnapshot | None,
    *,
    generated_at: datetime,
) -> MT5PaperReconciliationReport:
    if broker_snapshot is None:
        return MT5PaperReconciliationReport(
            state=MT5PaperReconciliationState.UNKNOWN,
            issues=("broker_snapshot:unavailable",),
            projection_semantic_state_id=projection.semantic_state_id,
            broker_snapshot_id=None,
            generated_at=generated_at,
        )

    issues: list[str] = []
    projected_orders = {key: value for key, value in projection.orders}
    broker_orders = {item.client_order_id: item for item in broker_snapshot.orders}
    if set(projected_orders) != set(broker_orders):
        issues.append("orders:identity_set_mismatch")
    for client_order_id in sorted(set(projected_orders) & set(broker_orders)):
        projected_payload = projected_orders[client_order_id].get("payload")
        if not isinstance(projected_payload, Mapping):
            issues.append(f"order:{client_order_id}:projection_payload_unavailable")
            continue
        actual = broker_orders[client_order_id]
        if str(projected_payload.get("status")) != actual.status.value:
            issues.append(f"order:{client_order_id}:status_mismatch")
        if str(projected_payload.get("broker_order_id")) != str(actual.broker_order_id):
            issues.append(f"order:{client_order_id}:broker_order_id_mismatch")
        try:
            projected_filled = float(projected_payload.get("filled_lots", 0.0))
        except (TypeError, ValueError):
            issues.append(f"order:{client_order_id}:filled_lots_unavailable")
        else:
            if abs(projected_filled - actual.filled_lots) > 1e-12:
                issues.append(f"order:{client_order_id}:filled_lots_mismatch")

    projected_deals = {key for key, _ in projection.trades}
    if projected_deals != set(broker_snapshot.broker_deal_ids):
        issues.append("deals:identity_set_mismatch")

    projected_positions = dict(projection.portfolio_lots)
    broker_positions = dict(broker_snapshot.positions)
    if set(projected_positions) != set(broker_positions):
        issues.append("positions:symbol_set_mismatch")
    for symbol in sorted(set(projected_positions) & set(broker_positions)):
        if abs(projected_positions[symbol] - broker_positions[symbol]) > 1e-12:
            issues.append(f"position:{symbol}:lots_mismatch")

    projected_accounts = {key: value for key, value in projection.accounts}
    account_document = projected_accounts.get(broker_snapshot.account_id)
    unknown = False
    if account_document is None:
        issues.append("account:projection_unavailable")
        unknown = True
    else:
        account_payload = account_document.get("payload")
        if not isinstance(account_payload, Mapping):
            issues.append("account:projection_payload_unavailable")
            unknown = True
        else:
            try:
                projected_equity = float(account_payload.get("equity", 0.0))
            except (TypeError, ValueError):
                issues.append("account:equity_unavailable")
                unknown = True
            else:
                if abs(projected_equity - broker_snapshot.equity) > 1e-9:
                    issues.append("account:equity_mismatch")

    if unknown:
        state = MT5PaperReconciliationState.UNKNOWN
    elif issues:
        state = MT5PaperReconciliationState.DRIFT
    else:
        state = MT5PaperReconciliationState.CONSISTENT
    return MT5PaperReconciliationReport(
        state=state,
        issues=tuple(issues),
        projection_semantic_state_id=projection.semantic_state_id,
        broker_snapshot_id=broker_snapshot.snapshot_id,
        generated_at=generated_at,
    )
