from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum

from finagent.realtime.events import (
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


class ReplayScenario(StrEnum):
    NORMAL = "NORMAL"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    STALE_QUOTE = "STALE_QUOTE"
    DISCONNECT_RECONNECT = "DISCONNECT_RECONNECT"


@dataclass(frozen=True, slots=True)
class ReplayBatch:
    scenario: ReplayScenario
    events: tuple[CanonicalRealtimeEvent, ...]
    schema_version: str = "finagent.realtime-replay-batch.v1"

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("replay batch cannot be empty")

    @property
    def batch_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="realtime-replay-batch")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "scenario": self.scenario.value,
            "events": [event.to_dict() for event in self.events],
            "replay_only": True,
            "market_data_authority": False,
            "execution_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["batch_id"] = self.batch_id
        return payload


class ReplayGateway:
    """Deterministically transforms canonical events into replay/fault streams.

    The gateway never changes the authoritative source payload semantics except for the
    explicitly requested engineering fault. It is a development fixture and has no broker or
    project-stage authority.
    """

    def __init__(self, events: tuple[CanonicalRealtimeEvent, ...]) -> None:
        if not events:
            raise ValueError("ReplayGateway requires at least one canonical event")
        self._events = events

    def build(
        self,
        scenario: ReplayScenario,
        *,
        stale_delay_seconds: int = 120,
    ) -> ReplayBatch:
        if stale_delay_seconds <= 0:
            raise ValueError("stale_delay_seconds must be positive")
        if scenario is ReplayScenario.NORMAL:
            output = self._events
        elif scenario is ReplayScenario.DUPLICATE:
            output = self._duplicate()
        elif scenario is ReplayScenario.OUT_OF_ORDER:
            output = self._out_of_order()
        elif scenario is ReplayScenario.STALE_QUOTE:
            output = self._stale_quote(stale_delay_seconds)
        elif scenario is ReplayScenario.DISCONNECT_RECONNECT:
            output = self._disconnect_reconnect()
        else:  # pragma: no cover - StrEnum exhaustiveness guard
            raise ValueError(f"unsupported replay scenario: {scenario}")
        return ReplayBatch(scenario=scenario, events=output)

    def _duplicate(self) -> tuple[CanonicalRealtimeEvent, ...]:
        index = 1 if len(self._events) > 1 else 0
        output = list(self._events)
        output.insert(index + 1, self._events[index])
        return tuple(output)

    def _out_of_order(self) -> tuple[CanonicalRealtimeEvent, ...]:
        if len(self._events) < 2:
            raise ValueError("OUT_OF_ORDER replay requires at least two events")
        output = list(self._events)
        output[0], output[1] = output[1], output[0]
        return tuple(output)

    def _stale_quote(self, stale_delay_seconds: int) -> tuple[CanonicalRealtimeEvent, ...]:
        output = list(self._events)
        for index, event in enumerate(output):
            if isinstance(event, QuoteEvent):
                output[index] = replace(
                    event,
                    received_at=event.received_at + timedelta(seconds=stale_delay_seconds),
                )
                return tuple(output)
        raise ValueError("STALE_QUOTE replay requires at least one QuoteEvent")

    def _disconnect_reconnect(self) -> tuple[CanonicalRealtimeEvent, ...]:
        pivot = max(1, len(self._events) // 2)
        anchor = self._events[pivot - 1]
        reconnect_anchor = self._events[min(pivot, len(self._events) - 1)]
        disconnected = ConnectionEvent(
            source="replay.control",
            source_event_id=f"disconnect-{anchor.event_id}",
            event_time=anchor.event_time,
            received_at=anchor.received_at,
            sequence=0,
            connection_id="replay-connection",
            status=ConnectionStatus.DISCONNECTED,
            reason="deterministic replay fault",
        )
        reconnected = ConnectionEvent(
            source="replay.control",
            source_event_id=f"reconnect-{reconnect_anchor.event_id}",
            event_time=reconnect_anchor.event_time,
            received_at=reconnect_anchor.received_at,
            sequence=1,
            connection_id="replay-connection",
            status=ConnectionStatus.CONNECTED,
            reason="deterministic replay recovery",
        )
        return (
            *self._events[:pivot],
            disconnected,
            reconnected,
            *self._events[pivot:],
        )
