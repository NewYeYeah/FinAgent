from __future__ import annotations

import json
from time import perf_counter, sleep

from .base import LLMProviderError, LLMRequest, LLMResponse, LLMUsage


class OpenAICompatibleChatProvider:
    """OpenAI-compatible Chat Completions adapter for third-party LLM endpoints.

    Credentials are injected only when the SDK client is constructed. They are never
    copied into LLMRequest, prompts, metadata, provider responses, or error messages.

    Provider retries address transport/provider transients only. Invalid generated
    JSON/Python is repaired at the feature-generation layer, where the conformance
    failure can be fed back without mixing provider availability with research logic.
    """

    _RETRYABLE_EXCEPTION_NAMES = {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
        "ServiceUnavailableError",
    }

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        client=None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        timeout_seconds: float = 900.0,
    ) -> None:
        provider_name = provider_name.strip().lower()
        if not provider_name:
            raise ValueError("provider_name is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError(
                    "OpenAICompatibleChatProvider requires the optional 'llm-openai' extra"
                ) from exc
            client_kwargs: dict[str, object] = {}
            if api_key is not None:
                client_kwargs["api_key"] = api_key
            if base_url is not None:
                client_kwargs["base_url"] = base_url
            client = OpenAI(**client_kwargs)
            # Keep the historical host-boundary invariant that the SDK constructor
            # receives only connection/credential identity. Timeout is a runtime option.
            with_options = getattr(client, "with_options", None)
            if callable(with_options):
                client = with_options(timeout=timeout_seconds)
        if reasoning_effort is not None and reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("reasoning_effort must be one of: low, high, max")
        self.client = client
        self._provider_name = provider_name
        self._thinking = thinking
        self._reasoning_effort = reasoning_effort
        self._max_attempts = int(max_attempts)
        self._retry_backoff_seconds = float(retry_backoff_seconds)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def _provider_parameters(self) -> dict[str, object]:
        parameters: dict[str, object] = {}
        if self._thinking is not None:
            parameters["extra_body"] = {
                "thinking": {"type": "enabled" if self._thinking else "disabled"}
            }
        if self._reasoning_effort is not None:
            parameters["reasoning_effort"] = self._reasoning_effort
        return parameters

    @staticmethod
    def _retryable_exception(exc: Exception) -> bool:
        if type(exc).__name__ in OpenAICompatibleChatProvider._RETRYABLE_EXCEPTION_NAMES:
            return True
        status = getattr(exc, "status_code", None)
        return isinstance(status, int) and (status == 429 or status >= 500)

    def _backoff(self, attempt: int) -> None:
        if self._retry_backoff_seconds > 0:
            sleep(self._retry_backoff_seconds * (2 ** max(0, attempt - 1)))

    def complete(self, request: LLMRequest) -> LLMResponse:
        schema_json = json.dumps(
            dict(request.response_schema),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        instructions = (
            f"{request.instructions}\n\n"
            "Return only one valid JSON object. Do not wrap it in Markdown or explanatory text. "
            f"The JSON object must match this JSON Schema exactly:\n{schema_json}"
        )
        kwargs: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": request.input_text},
            ],
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if request.temperature is not None:
            kwargs["temperature"] = float(request.temperature)
        kwargs.update(self._provider_parameters())

        started = perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_error = exc
                if attempt < self._max_attempts and self._retryable_exception(exc):
                    self._backoff(attempt)
                    continue
                raise LLMProviderError(
                    f"{self.provider_name} Chat Completions request failed after "
                    f"{attempt} attempt(s): {type(exc).__name__}"
                ) from exc

            choices = getattr(response, "choices", None)
            if not choices:
                if attempt < self._max_attempts:
                    self._backoff(attempt)
                    continue
                raise LLMProviderError(
                    f"{self.provider_name} Chat Completions returned no choices after "
                    f"{attempt} attempt(s)"
                )

            choice = choices[0]
            message = getattr(choice, "message", None)
            finish_reason = str(getattr(choice, "finish_reason", "completed") or "completed")
            output_text = str(getattr(message, "content", "") or "").strip()
            usage_obj = getattr(response, "usage", None)
            input_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
            raw_total_tokens = getattr(usage_obj, "total_tokens", None)
            total_tokens = (
                input_tokens + output_tokens
                if raw_total_tokens is None
                else int(raw_total_tokens)
            )
            input_details = getattr(usage_obj, "prompt_tokens_details", None)
            cached_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)
            completion_details = getattr(usage_obj, "completion_tokens_details", None)
            reasoning_tokens = int(getattr(completion_details, "reasoning_tokens", 0) or 0)
            has_reasoning = bool(str(getattr(message, "reasoning_content", "") or "").strip())

            if not output_text:
                retryable_empty = finish_reason in {
                    "stop",
                    "completed",
                    "insufficient_system_resource",
                    "",
                }
                if attempt < self._max_attempts and retryable_empty:
                    self._backoff(attempt)
                    continue
                raise LLMProviderError(
                    f"{self.provider_name} Chat Completions returned empty message content; "
                    f"finish_reason={finish_reason}, completion_tokens={output_tokens}, "
                    f"reasoning_tokens={reasoning_tokens}, has_reasoning={has_reasoning}, "
                    f"attempts={attempt}"
                )

            if finish_reason == "length":
                raise LLMProviderError(
                    f"{self.provider_name} Chat Completions exhausted max_tokens="
                    f"{request.max_output_tokens}; completion_tokens={output_tokens}, "
                    f"reasoning_tokens={reasoning_tokens}"
                )

            latency_ms = (perf_counter() - started) * 1000.0
            return LLMResponse(
                request_id=request.request_id,
                response_id=str(getattr(response, "id", f"{self.provider_name}-response")),
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
                status=finish_reason,
                metadata={
                    "provider_attempts": str(attempt),
                    "reasoning_tokens": str(reasoning_tokens),
                    "has_reasoning": str(has_reasoning).lower(),
                    "finish_reason": finish_reason,
                },
            )

        assert last_error is not None
        raise LLMProviderError(
            f"{self.provider_name} Chat Completions exhausted provider attempts"
        ) from last_error


class DeepSeekChatProvider(OpenAICompatibleChatProvider):
    """DeepSeek official OpenAI-compatible Chat Completions adapter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        client=None,
        thinking: bool = True,
        reasoning_effort: str = "high",
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        timeout_seconds: float = 900.0,
    ) -> None:
        super().__init__(
            provider_name="deepseek",
            api_key=api_key,
            base_url=base_url,
            client=client,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            timeout_seconds=timeout_seconds,
        )


class SiliconFlowChatProvider(OpenAICompatibleChatProvider):
    """SiliconFlow OpenAI-compatible Chat Completions adapter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.siliconflow.cn/v1",
        client=None,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        timeout_seconds: float = 900.0,
    ) -> None:
        super().__init__(
            provider_name="siliconflow",
            api_key=api_key,
            base_url=base_url,
            client=client,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            timeout_seconds=timeout_seconds,
        )
