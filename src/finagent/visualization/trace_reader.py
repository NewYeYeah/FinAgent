from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class TraceEvent:
    name: str
    at: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True, slots=True)
class TraceSpan:
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    started_at: str
    ended_at: str
    status: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[TraceEvent, ...] = ()
    error_type: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
        object.__setattr__(self, "events", tuple(self.events))

    @property
    def duration_ms(self) -> float | None:
        if not self.started_at or not self.ended_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.ended_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        return max(0.0, (end - start).total_seconds() * 1000.0)

    @property
    def is_error(self) -> bool:
        return self.status == "error"


@dataclass(frozen=True, slots=True)
class AgentTraceView:
    spans: tuple[TraceSpan, ...]
    warnings: tuple[str, ...] = ()
    source: str = ""

    def span(self, span_id: str) -> TraceSpan:
        for value in self.spans:
            if value.span_id == span_id:
                return value
        raise KeyError(span_id)

    def depth(self, span: TraceSpan) -> int:
        by_id = {value.span_id: value for value in self.spans}
        depth = 0
        parent = span.parent_span_id
        visited: set[str] = set()
        while parent and parent in by_id and parent not in visited:
            visited.add(parent)
            depth += 1
            parent = by_id[parent].parent_span_id
        return depth

    def rows(self) -> list[dict[str, object]]:
        return [
            {
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id or "",
                "depth": self.depth(span),
                "name": f"{'  ' * self.depth(span)}{span.name}",
                "kind": span.kind,
                "status": span.status,
                "started_at": span.started_at,
                "duration_ms": span.duration_ms,
                "error_type": span.error_type,
                "error": span.error,
            }
            for span in self.spans
        ]

    def llm_rows(self) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for span in self.spans:
            if span.kind.upper() != "LLM":
                continue
            attrs = span.attributes
            output.append(
                {
                    "span_id": span.span_id,
                    "name": span.name,
                    "status": span.status,
                    "model": attrs.get("llm.model_name", ""),
                    "prompt_tokens": _as_int(attrs.get("llm.token_count.prompt")),
                    "completion_tokens": _as_int(
                        attrs.get("llm.token_count.completion")
                    ),
                    "total_tokens": _as_int(attrs.get("llm.token_count.total")),
                    "reasoning_tokens": _as_int(attrs.get("finagent.reasoning_tokens")),
                    "provider_attempts": _as_int(
                        attrs.get("finagent.provider_attempts"), 1
                    ),
                    "finish_reason": attrs.get("finagent.finish_reason", ""),
                    "latency_ms": _as_float(
                        attrs.get("finagent.latency_ms"), span.duration_ms or 0.0
                    ),
                    "conformance_attempt": _as_int(
                        attrs.get("finagent.conformance_attempt"), 0
                    ),
                    "prompt_hash": attrs.get("finagent.prompt_hash", ""),
                }
            )
        return output

    @property
    def total_tokens(self) -> int:
        return sum(int(row["total_tokens"]) for row in self.llm_rows())

    @property
    def total_reasoning_tokens(self) -> int:
        return sum(int(row["reasoning_tokens"]) for row in self.llm_rows())

    @property
    def total_llm_latency_ms(self) -> float:
        return sum(float(row["latency_ms"]) for row in self.llm_rows())

    def event_rows(self) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for span in self.spans:
            for event in span.events:
                output.append(
                    {
                        "span_id": span.span_id,
                        "span_name": span.name,
                        "event": event.name,
                        "at": event.at,
                        "attributes": dict(event.attributes),
                    }
                )
        return output


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def parse_agent_trace(
    lines: str | bytes | Sequence[str],
    *,
    source: str = "memory",
) -> AgentTraceView:
    if isinstance(lines, bytes):
        values = lines.decode("utf-8").splitlines()
    elif isinstance(lines, str):
        values = lines.splitlines()
    else:
        values = list(lines)

    starts: dict[str, dict[str, Any]] = {}
    ends: dict[str, Mapping[str, Any]] = {}
    events: dict[str, list[TraceEvent]] = {}
    warnings: list[str] = []
    order: list[str] = []

    for line_number, raw_line in enumerate(values, start=1):
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            warnings.append(f"line {line_number}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(payload, Mapping):
            warnings.append(f"line {line_number}: trace record is not an object")
            continue
        event_type = str(payload.get("event", ""))
        span_id = str(payload.get("span_id", "") or "")
        if not span_id:
            warnings.append(f"line {line_number}: trace record is missing span_id")
            continue
        if event_type == "span_start":
            if span_id in starts:
                warnings.append(f"line {line_number}: duplicate span_start {span_id}")
                continue
            starts[span_id] = dict(payload)
            order.append(span_id)
            events.setdefault(span_id, [])
        elif event_type == "span_end":
            ends[span_id] = payload
        elif event_type == "event":
            name = str(payload.get("name", "event"))
            attributes = payload.get("attributes", {})
            if not isinstance(attributes, Mapping):
                attributes = {"value": attributes}
            events.setdefault(span_id, []).append(
                TraceEvent(
                    name=name,
                    at=str(payload.get("at", "")),
                    attributes=attributes,
                )
            )
        else:
            warnings.append(f"line {line_number}: unsupported trace event {event_type!r}")

    spans: list[TraceSpan] = []
    for span_id in order:
        start = starts[span_id]
        end = ends.get(span_id, {})
        attributes = start.get("attributes", {})
        if not isinstance(attributes, Mapping):
            attributes = {"value": attributes}
        merged = dict(attributes)
        retained_events: list[TraceEvent] = []
        for event in events.get(span_id, []):
            if event.name == "attributes":
                merged.update(event.attributes)
            else:
                retained_events.append(event)
        status = str(end.get("status", "open")) if end else "open"
        spans.append(
            TraceSpan(
                span_id=span_id,
                parent_span_id=(
                    str(start.get("parent_span_id"))
                    if start.get("parent_span_id")
                    else None
                ),
                name=str(start.get("name", "unnamed")),
                kind=str(start.get("kind", "INTERNAL")),
                started_at=str(start.get("at", "")),
                ended_at=str(end.get("at", "")),
                status=status,
                attributes=merged,
                events=tuple(retained_events),
                error_type=str(end.get("error_type", "")),
                error=str(end.get("error", "")),
            )
        )
    orphan_ends = set(ends) - set(starts)
    if orphan_ends:
        warnings.append(f"orphan span_end records: {len(orphan_ends)}")
    orphan_events = set(events) - set(starts)
    if orphan_events:
        warnings.append(f"orphan event span ids: {len(orphan_events)}")
    return AgentTraceView(spans=tuple(spans), warnings=tuple(warnings), source=source)


def load_agent_trace(path: str | Path) -> AgentTraceView:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    return parse_agent_trace(source.read_text(encoding="utf-8"), source=str(source))
