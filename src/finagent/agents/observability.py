from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Mapping


_CURRENT_SPAN: ContextVar[str | None] = ContextVar("finagent_agent_span", default=None)


def _safe_attribute(value: object) -> str | bool | int | float:
    if isinstance(value, (str, bool, int, float)):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _trim(value: object, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass(frozen=True, slots=True)
class AgentObservabilityConfig:
    enabled: bool = False
    backend: str = "jsonl"
    jsonl_path: str = ".finagent/agent-traces.jsonl"
    otlp_endpoint: str = "http://localhost:6006/v1/traces"
    project_name: str = "finagent"
    capture_content: bool = False
    max_content_chars: int = 50_000

    def __post_init__(self) -> None:
        if self.backend not in {"jsonl", "phoenix", "both"}:
            raise ValueError("observability backend must be jsonl, phoenix, or both")
        if self.max_content_chars < 1000:
            raise ValueError("max_content_chars must be >= 1000")
        if self.enabled and self.backend in {"phoenix", "both"} and not self.otlp_endpoint:
            raise ValueError("otlp_endpoint is required for Phoenix/OTLP tracing")
        if not self.project_name.strip():
            raise ValueError("project_name cannot be empty")


class AgentSpan:
    def __init__(self, tracer: AgentTracer, span_id: str, otel_span=None) -> None:
        self._tracer = tracer
        self.span_id = span_id
        self._otel_span = otel_span

    def set_attributes(self, values: Mapping[str, object]) -> None:
        if self._otel_span is not None:
            for key, value in values.items():
                self._otel_span.set_attribute(str(key), _safe_attribute(value))
        self._tracer.event("attributes", values)

    def event(self, name: str, values: Mapping[str, object] | None = None) -> None:
        self._tracer.event(name, values or {})


class AgentTracer:
    """Small vendor-neutral trace surface for FinAgent Agent/LLM workflows.

    JSONL is always local. Phoenix integration uses standard OTLP/OpenTelemetry and
    OpenInference span-kind attributes, so the same instrumentation can later target
    another OTLP backend such as Langfuse without changing research code.

    Hidden model reasoning is never recorded. Only explicit prompts/responses may be
    captured when ``capture_content`` is enabled.
    """

    def __init__(self, config: AgentObservabilityConfig = AgentObservabilityConfig()) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._jsonl_path: Path | None = None
        self._otel_provider = None
        self._otel_tracer = None
        if not config.enabled:
            return
        if config.backend in {"jsonl", "both"}:
            self._jsonl_path = Path(config.jsonl_path)
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        if config.backend in {"phoenix", "both"}:
            self._configure_otel()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def capture_content(self) -> bool:
        return self.config.capture_content

    def content(self, value: object) -> str:
        return _trim(value, self.config.max_content_chars)

    def _configure_otel(self) -> None:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:
            raise ImportError(
                "Phoenix observability requires the optional 'observability' extra: "
                "python -m pip install -e '.[observability]'"
            ) from exc
        resource = Resource.create(
            {
                "service.name": "finagent",
                "openinference.project.name": self.config.project_name,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=self.config.otlp_endpoint,
            headers={"x-project-name": self.config.project_name},
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        self._otel_provider = provider
        self._otel_tracer = provider.get_tracer("finagent.agents")

    def _write(self, payload: Mapping[str, object]) -> None:
        if self._jsonl_path is None:
            return
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        with self._lock:
            with self._jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")

    @contextmanager
    def span(
        self,
        name: str,
        kind: str,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[AgentSpan]:
        if not self.enabled:
            yield AgentSpan(self, "disabled")
            return
        span_id = uuid.uuid4().hex
        parent_id = _CURRENT_SPAN.get()
        token = _CURRENT_SPAN.set(span_id)
        started = datetime.now(UTC)
        attrs = {str(k): _safe_attribute(v) for k, v in (attributes or {}).items()}
        self._write(
            {
                "event": "span_start",
                "span_id": span_id,
                "parent_span_id": parent_id,
                "name": name,
                "kind": kind,
                "at": started.isoformat(),
                "attributes": attrs,
            }
        )
        otel_cm = None
        otel_span = None
        if self._otel_tracer is not None:
            otel_cm = self._otel_tracer.start_as_current_span(name)
            otel_span = otel_cm.__enter__()
            otel_span.set_attribute("openinference.span.kind", kind.upper())
            for key, value in attrs.items():
                otel_span.set_attribute(key, value)
        try:
            yield AgentSpan(self, span_id, otel_span)
        except Exception as exc:
            if otel_span is not None:
                from opentelemetry.trace import Status, StatusCode

                otel_span.record_exception(exc)
                otel_span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            self._write(
                {
                    "event": "span_end",
                    "span_id": span_id,
                    "name": name,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": _trim(exc, 2000),
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            raise
        else:
            self._write(
                {
                    "event": "span_end",
                    "span_id": span_id,
                    "name": name,
                    "status": "ok",
                    "at": datetime.now(UTC).isoformat(),
                }
            )
        finally:
            if otel_cm is not None:
                otel_cm.__exit__(None, None, None)
            _CURRENT_SPAN.reset(token)

    def event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        if not self.enabled:
            return
        attrs = {str(k): _safe_attribute(v) for k, v in (attributes or {}).items()}
        self._write(
            {
                "event": "event",
                "span_id": _CURRENT_SPAN.get(),
                "name": name,
                "at": datetime.now(UTC).isoformat(),
                "attributes": attrs,
            }
        )
        if self._otel_tracer is not None:
            from opentelemetry import trace

            current = trace.get_current_span()
            if current is not None:
                current.add_event(name, attrs)

    def close(self) -> None:
        if self._otel_provider is not None:
            self._otel_provider.force_flush()
            self._otel_provider.shutdown()
