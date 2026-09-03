from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from finagent.brokers.mt5.capabilities import MT5CapabilityProbeReport
from finagent.brokers.mt5.clock import MT5BrokerClockEvidence
from finagent.brokers.mt5.feed_regime import MT5_FEED_REGIME_LANES
from finagent.realtime.events import (
    BarEvent,
    CanonicalRealtimeEvent,
    ConnectionEvent,
    ConnectionStatus,
    QuoteEvent,
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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _value(record: object, name: str) -> object:
    if isinstance(record, Mapping):
        return record.get(name)
    asdict = getattr(record, "_asdict", None)
    if callable(asdict):
        mapped = asdict()
        if isinstance(mapped, Mapping):
            return mapped.get(name)
    attribute = getattr(record, name, None)
    if attribute is not None:
        return attribute
    dynamic = cast(Any, record)
    try:
        return dynamic[name]
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    if isinstance(value, (int, float, str)):
        return float(value)
    item = getattr(value, "item", None)
    if callable(item):
        return _number(item(), field_name)
    raise TypeError(f"{field_name} must be numeric")


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be integer-like")
    if isinstance(value, (int, float, str)):
        return int(value)
    item = getattr(value, "item", None)
    if callable(item):
        return _integer(item(), field_name)
    raise TypeError(f"{field_name} must be integer-like")


def _epoch_msc(record: object, *, field_prefix: str) -> int:
    raw_msc = _value(record, "time_msc")
    if raw_msc is not None:
        parsed = _integer(raw_msc, f"{field_prefix}.time_msc")
        if parsed > 0:
            return parsed
    raw_seconds = _value(record, "time")
    if raw_seconds is None:
        raise ValueError(f"{field_prefix} requires time_msc or time")
    parsed_seconds = _integer(raw_seconds, f"{field_prefix}.time")
    if parsed_seconds <= 0:
        raise ValueError(f"{field_prefix}.time must be positive")
    return parsed_seconds * 1000


def _feed_lane(value: str) -> str:
    lane = value.strip()
    if lane not in MT5_FEED_REGIME_LANES:
        raise ValueError(f"unsupported MT5 feed regime lane {lane!r}")
    return lane


@dataclass(frozen=True, slots=True)
class MT5RealtimeAdapterPolicy:
    broker_server: str
    feed_lane: str
    quote_source: str = "mt5.readonly.quote"
    bar_source: str = "mt5.readonly.bar"
    connection_source: str = "mt5.readonly.connection"
    schema_version: str = "finagent.mt5-realtime-adapter-policy.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "broker_server",
            _text(self.broker_server, "broker_server"),
        )
        object.__setattr__(self, "feed_lane", _feed_lane(self.feed_lane))
        for field_name in ("quote_source", "bar_source", "connection_source"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name),
            )

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-realtime-adapter-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "broker_server": self.broker_server,
            "feed_lane": self.feed_lane,
            "quote_source": self.quote_source,
            "bar_source": self.bar_source,
            "connection_source": self.connection_source,
            "feed_lane_inferred": False,
            "read_only": True,
            "mutation_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5RealtimeAdapterReport:
    policy: MT5RealtimeAdapterPolicy
    capability_probe_id: str
    clock_evidence_id: str
    events: tuple[CanonicalRealtimeEvent, ...]
    generated_at: datetime
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.mt5-realtime-adapter-report.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_probe_id",
            _text(self.capability_probe_id, "capability_probe_id"),
        )
        object.__setattr__(
            self,
            "clock_evidence_id",
            _text(self.clock_evidence_id, "clock_evidence_id"),
        )
        object.__setattr__(self, "generated_at", _aware(self.generated_at, "generated_at"))
        source_ids = tuple(event.source_key for event in self.events)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("MT5 adapter report cannot repeat one source observation identity")
        object.__setattr__(
            self,
            "blockers",
            tuple(dict.fromkeys(item.strip() for item in self.blockers if item.strip())),
        )

    @property
    def passed(self) -> bool:
        return not self.blockers and bool(self.events)

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-realtime-adapter")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy": self.policy.to_dict(),
            "capability_probe_id": self.capability_probe_id,
            "clock_evidence_id": self.clock_evidence_id,
            "events": [event.to_dict() for event in self.events],
            "event_count": len(self.events),
            "generated_at": self.generated_at.isoformat(),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "implementation_ready_for_mt5_m1_acceptance": self.passed,
            "feed_lane_inferred": False,
            "read_only": True,
            "symbol_select_used": False,
            "order_send_used": False,
            "us_market_source_authority": False,
            "live_market_data_authority": False,
            "broker_account_authority": False,
            "execution_authority": False,
            "paper_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class MT5RealtimeMarketAdapter:
    """Map read-only MT5 polling observations into canonical realtime events.

    MT5 Python polling does not expose a durable provider-native event identifier. Therefore
    `source_event_id` intentionally identifies one *polling observation*, not an underlying
    exchange tick. The observation identity binds the raw broker timestamp, raw fields and
    caller-supplied receive timestamp. Re-reading an unchanged tick later is a new observation
    rather than a provider-identity conflict.
    """

    def __init__(
        self,
        policy: MT5RealtimeAdapterPolicy,
        clock_evidence: MT5BrokerClockEvidence,
    ) -> None:
        if not clock_evidence.passed:
            raise ValueError("MT5 realtime adapter requires passing broker-clock evidence")
        if clock_evidence.broker_server != policy.broker_server:
            raise ValueError("MT5 realtime adapter broker-server/clock mismatch")
        self._policy = policy
        self._clock = clock_evidence
        self._sequence_by_source: dict[str, int] = {}

    @property
    def policy(self) -> MT5RealtimeAdapterPolicy:
        return self._policy

    @property
    def clock_evidence(self) -> MT5BrokerClockEvidence:
        return self._clock

    def _sequence(self, source: str) -> int:
        value = self._sequence_by_source.get(source, 0)
        self._sequence_by_source[source] = value + 1
        return value

    def _observation_id(
        self,
        *,
        kind: str,
        symbol: str,
        raw_time_msc: int,
        received_at: datetime,
        raw_fields: Mapping[str, object],
    ) -> str:
        return _canonical_hash(
            {
                "broker_server": self._policy.broker_server,
                "feed_lane": self._policy.feed_lane,
                "kind": kind,
                "symbol": symbol,
                "raw_time_msc": raw_time_msc,
                "received_at": received_at.isoformat(),
                "raw_fields": dict(raw_fields),
            },
            prefix="mt5-observation",
        )

    def quote_event(
        self,
        symbol: str,
        tick: object,
        *,
        received_at: datetime,
    ) -> QuoteEvent:
        normalized_received = _aware(received_at, "received_at")
        rendered_symbol = _text(symbol, "symbol")
        raw_time_msc = _epoch_msc(tick, field_prefix="tick")
        bid = _number(_value(tick, "bid"), "tick.bid")
        ask = _number(_value(tick, "ask"), "tick.ask")
        last_raw = _value(tick, "last")
        last = None if last_raw is None else _number(last_raw, "tick.last")
        raw_fields: dict[str, object] = {
            "bid": bid,
            "ask": ask,
            "last": last,
        }
        source_event_id = self._observation_id(
            kind="quote",
            symbol=rendered_symbol,
            raw_time_msc=raw_time_msc,
            received_at=normalized_received,
            raw_fields=raw_fields,
        )
        return QuoteEvent(
            source=self._policy.quote_source,
            source_event_id=source_event_id,
            event_time=self._clock.normalize_epoch_msc(raw_time_msc),
            received_at=normalized_received,
            sequence=self._sequence(self._policy.quote_source),
            symbol=rendered_symbol,
            bid=bid,
            ask=ask,
            last=last,
        )

    def bar_event(
        self,
        symbol: str,
        rate: object,
        *,
        received_at: datetime,
        complete: bool,
        interval_seconds: int = 60,
    ) -> BarEvent:
        normalized_received = _aware(received_at, "received_at")
        rendered_symbol = _text(symbol, "symbol")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        raw_time_msc = _epoch_msc(rate, field_prefix="rate")
        open_price = _number(_value(rate, "open"), "rate.open")
        high = _number(_value(rate, "high"), "rate.high")
        low = _number(_value(rate, "low"), "rate.low")
        close = _number(_value(rate, "close"), "rate.close")
        tick_volume_raw = _value(rate, "tick_volume")
        volume = 0.0 if tick_volume_raw is None else _number(tick_volume_raw, "rate.tick_volume")
        raw_fields: dict[str, object] = {
            "interval_seconds": interval_seconds,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": volume,
            "complete": complete,
        }
        source_event_id = self._observation_id(
            kind="bar",
            symbol=rendered_symbol,
            raw_time_msc=raw_time_msc,
            received_at=normalized_received,
            raw_fields=raw_fields,
        )
        return BarEvent(
            source=self._policy.bar_source,
            source_event_id=source_event_id,
            event_time=self._clock.normalize_epoch_msc(raw_time_msc),
            received_at=normalized_received,
            sequence=self._sequence(self._policy.bar_source),
            symbol=rendered_symbol,
            interval_seconds=interval_seconds,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            complete=complete,
        )

    def connection_event(
        self,
        capability_probe: MT5CapabilityProbeReport,
        *,
        observed_at: datetime,
    ) -> ConnectionEvent:
        timestamp = _aware(observed_at, "observed_at")
        terminal = capability_probe.terminal
        if terminal.broker_server != self._policy.broker_server:
            raise ValueError("MT5 realtime adapter capability broker-server mismatch")
        status = (
            ConnectionStatus.CONNECTED
            if terminal.connected
            else ConnectionStatus.DISCONNECTED
        )
        source_event_id = _canonical_hash(
            {
                "broker_server": terminal.broker_server,
                "capability_probe_id": capability_probe.probe_id,
                "observed_at": timestamp.isoformat(),
                "connected": terminal.connected,
            },
            prefix="mt5-connection-observation",
        )
        return ConnectionEvent(
            source=self._policy.connection_source,
            source_event_id=source_event_id,
            event_time=timestamp,
            received_at=timestamp,
            sequence=self._sequence(self._policy.connection_source),
            connection_id=f"mt5:{terminal.broker_server}",
            status=status,
            reason="read-only MT5 terminal capability observation",
        )

    def build_report(
        self,
        capability_probe: MT5CapabilityProbeReport,
        events: tuple[CanonicalRealtimeEvent, ...],
        *,
        generated_at: datetime,
    ) -> MT5RealtimeAdapterReport:
        if capability_probe.terminal.broker_server != self._policy.broker_server:
            raise ValueError("MT5 realtime adapter report capability broker-server mismatch")
        if not capability_probe.read_only or capability_probe.mutation_authority:
            raise ValueError("MT5 realtime adapter requires read-only capability evidence")
        blockers: list[str] = []
        if not capability_probe.terminal.connected:
            blockers.append("terminal:not_connected")
        if not events:
            blockers.append("adapter:no_events")
        return MT5RealtimeAdapterReport(
            policy=self._policy,
            capability_probe_id=capability_probe.probe_id,
            clock_evidence_id=self._clock.evidence_id,
            events=events,
            generated_at=generated_at,
            blockers=tuple(blockers),
        )
