from __future__ import annotations

import json
from time import perf_counter

from .base import LLMProviderError, LLMRequest, LLMResponse, LLMUsage


class OpenAICompatibleChatProvider:
    """OpenAI-compatible Chat Completions adapter for third-party LLM endpoints.

    Credentials are injected only when the SDK client is constructed. They are never
    copied into LLMRequest, prompts, metadata, provider responses, or error messages.
    """

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        client=None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        provider_name = provider_name.strip().lower()
        if not provider_name:
            raise ValueError("provider_name is required")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError(
                    "OpenAICompatibleChatProvider requires the optional 'llm-openai' extra"
                ) from exc
            client_kwargs: dict[str, str] = {}
            if api_key is not None:
                client_kwargs["api_key"] = api_key
            if base_url is not None:
                client_kwargs["base_url"] = base_url
            client = OpenAI(**client_kwargs)
        if reasoning_effort is not None and reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("reasoning_effort must be one of: low, high, max")
        self.client = client
        self._provider_name = provider_name
        self._thinking = thinking
        self._reasoning_effort = reasoning_effort

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

    def complete(self, request: LLMRequest) -> LLMResponse:
        schema_json = json.dumps(
            dict(request.response_schema), sort_keys=True, separators=(",", ":"), ensure_ascii=False
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
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Do not include the provider exception text: upstream HTTP errors can contain
            # request context that should never be allowed into durable Agent logs.
            raise LLMProviderError(
                f"{self.provider_name} Chat Completions request failed: {type(exc).__name__}"
            ) from exc
        latency_ms = (perf_counter() - started) * 1000.0

        choices = getattr(response, "choices", None)
        if not choices:
            raise LLMProviderError(
                f"{self.provider_name} Chat Completions request returned no choices"
            )
        choice = choices[0]
        message = getattr(choice, "message", None)
        output_text = str(getattr(message, "content", "") or "").strip()
        if not output_text:
            raise LLMProviderError(
                f"{self.provider_name} Chat Completions request returned no message content"
            )

        usage_obj = getattr(response, "usage", None)
        input_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
        raw_total_tokens = getattr(usage_obj, "total_tokens", None)
        total_tokens = input_tokens + output_tokens if raw_total_tokens is None else int(raw_total_tokens)
        input_details = getattr(usage_obj, "prompt_tokens_details", None)
        cached_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)
        finish_reason = str(getattr(choice, "finish_reason", "completed") or "completed")

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
        )


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
    ) -> None:
        super().__init__(
            provider_name="deepseek",
            api_key=api_key,
            base_url=base_url,
            client=client,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )


class SiliconFlowChatProvider(OpenAICompatibleChatProvider):
    """SiliconFlow OpenAI-compatible Chat Completions adapter.

    Provider-specific reasoning parameters are intentionally omitted by default because
    SiliconFlow's current V4-Pro parameter documentation is narrower than its model catalog.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.siliconflow.cn/v1",
        client=None,
    ) -> None:
        super().__init__(
            provider_name="siliconflow",
            api_key=api_key,
            base_url=base_url,
            client=client,
        )
