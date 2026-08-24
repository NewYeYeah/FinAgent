from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol

from finagent.domain._validation import require_non_empty

JsonSchema = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be an integer >= 0")
        if self.total_tokens and self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens cannot be smaller than input_tokens + output_tokens")


@dataclass(frozen=True, slots=True)
class LLMRequest:
    request_id: str
    model: str
    instructions: str
    input_text: str
    schema_name: str
    response_schema: JsonSchema
    max_output_tokens: int = 2000
    temperature: float | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("request_id", "model", "instructions", "input_text", "schema_name"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int) or self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be an integer >= 1")
        if self.temperature is not None and not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("temperature must be in [0, 2]")
        schema = dict(self.response_schema)
        if schema.get("type") != "object":
            raise ValueError("response_schema root type must be object")
        object.__setattr__(self, "response_schema", MappingProxyType(schema))
        object.__setattr__(self, "metadata", MappingProxyType({str(k): str(v) for k, v in self.metadata.items()}))

    @property
    def prompt_hash(self) -> str:
        payload = {
            "model": self.model,
            "instructions": self.instructions,
            "input_text": self.input_text,
            "schema_name": self.schema_name,
            "response_schema": dict(self.response_schema),
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class LLMResponse:
    request_id: str
    response_id: str
    provider: str
    model: str
    output_text: str
    usage: LLMUsage = LLMUsage()
    latency_ms: float = 0.0
    status: str = "completed"
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("request_id", "response_id", "provider", "model", "output_text", "status"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        object.__setattr__(self, "metadata", MappingProxyType({str(k): str(v) for k, v in self.metadata.items()}))


class LLMProviderError(RuntimeError):
    pass


class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class StaticLLMProvider:
    """Deterministic provider used by tests and offline development."""

    def __init__(self, output_text: str, *, provider_name: str = "static", model: str = "static-model") -> None:
        self._output_text = require_non_empty(output_text, "output_text")
        self._provider_name = require_non_empty(provider_name, "provider_name")
        self._model = require_non_empty(model, "model")
        self.requests: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            request_id=request.request_id,
            response_id=f"static-{len(self.requests)}",
            provider=self.provider_name,
            model=self._model,
            output_text=self._output_text,
            usage=LLMUsage(),
            latency_ms=0.0,
        )
