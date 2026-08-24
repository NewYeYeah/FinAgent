from __future__ import annotations

from time import perf_counter

from .base import LLMProviderError, LLMRequest, LLMResponse, LLMUsage


class OpenAIResponsesProvider:
    """Optional OpenAI Responses API adapter.

    The OpenAI SDK is imported lazily, so the core package and CI do not require
    provider dependencies. A compatible client can be injected for tests.
    """

    def __init__(self, *, client=None) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError(
                    "OpenAIResponsesProvider requires the optional 'llm-openai' extra"
                ) from exc
            client = OpenAI()
        self.client = client

    @property
    def provider_name(self) -> str:
        return "openai"

    def complete(self, request: LLMRequest) -> LLMResponse:
        kwargs = {
            "model": request.model,
            "instructions": request.instructions,
            "input": request.input_text,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "strict": True,
                    "schema": dict(request.response_schema),
                }
            },
            "metadata": dict(request.metadata),
        }
        if request.temperature is not None:
            kwargs["temperature"] = float(request.temperature)

        started = perf_counter()
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            raise LLMProviderError(f"OpenAI Responses request failed: {type(exc).__name__}: {exc}") from exc
        latency_ms = (perf_counter() - started) * 1000.0

        output_text = str(getattr(response, "output_text", "") or "").strip()
        if not output_text:
            raise LLMProviderError("OpenAI Responses request returned no output_text")

        usage_obj = getattr(response, "usage", None)
        input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
        raw_total_tokens = getattr(usage_obj, "total_tokens", None)
        total_tokens = input_tokens + output_tokens if raw_total_tokens is None else int(raw_total_tokens)
        input_details = getattr(usage_obj, "input_tokens_details", None)
        cached_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

        return LLMResponse(
            request_id=request.request_id,
            response_id=str(getattr(response, "id", "openai-response")),
            provider=self.provider_name,
            model=str(getattr(response, "model", request.model)),
            output_text=output_text,
            usage=LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cached_input_tokens=cached_tokens,
            ),
            latency_ms=latency_ms,
            status=str(getattr(response, "status", "completed") or "completed"),
        )
