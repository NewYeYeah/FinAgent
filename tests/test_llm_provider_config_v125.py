import os
import sys
from types import SimpleNamespace

import pytest

from finagent.agents.providers import (
    DeepSeekChatProvider,
    LLMProviderError,
    LLMRequest,
    SiliconFlowChatProvider,
    load_configured_llm,
    load_llm_profile,
)


class _FakeUsageDetails:
    cached_tokens = 4


class _FakeUsage:
    prompt_tokens = 12
    completion_tokens = 7
    total_tokens = 19
    prompt_tokens_details = _FakeUsageDetails()


class _FakeMessage:
    content = '{"ok":true}'


class _FakeChoice:
    message = _FakeMessage()
    finish_reason = "stop"


class _FakeChatResponse:
    id = "chat-test"
    model = "deepseek-v4-pro"
    choices = [_FakeChoice()]
    usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, *, error=None):
        self.kwargs = None
        self.error = error

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return _FakeChatResponse()


class _FakeClient:
    def __init__(self, *, error=None):
        self.chat = SimpleNamespace(completions=_FakeCompletions(error=error))


def _request() -> LLMRequest:
    return LLMRequest(
        request_id="req-v125",
        model="deepseek-v4-pro",
        instructions="Return the requested structure.",
        input_text="test input",
        schema_name="test_schema",
        response_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        max_output_tokens=256,
    )


def test_deepseek_chat_adapter_uses_json_mode_and_official_reasoning_parameters():
    client = _FakeClient()
    provider = DeepSeekChatProvider(client=client, thinking=True, reasoning_effort="high")

    response = provider.complete(_request())

    assert response.provider == "deepseek"
    assert response.output_text == '{"ok":true}'
    assert response.usage.cached_input_tokens == 4
    kwargs = client.chat.completions.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert kwargs["reasoning_effort"] == "high"
    assert "JSON Schema" in kwargs["messages"][0]["content"]


def test_siliconflow_v4_pro_adapter_avoids_unverified_reasoning_parameters():
    client = _FakeClient()
    provider = SiliconFlowChatProvider(client=client)

    response = provider.complete(_request())

    assert response.provider == "siliconflow"
    kwargs = client.chat.completions.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in kwargs
    assert "extra_body" not in kwargs


def test_provider_error_does_not_echo_upstream_exception_text_or_secret():
    secret = "sk-do-not-leak-123"
    provider = DeepSeekChatProvider(
        client=_FakeClient(error=RuntimeError(f"upstream exposed {secret}"))
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete(_request())

    assert secret not in str(exc_info.value)
    assert "upstream exposed" not in str(exc_info.value)
    assert "RuntimeError" in str(exc_info.value)


def test_public_profile_contains_routing_but_no_api_key(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        """
[llm]
default_profile = "deepseek_main"
secrets_file = "ignored-in-this-test.toml"

[llm.profiles.deepseek_main]
provider = "deepseek"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-pro"
secret_id = "deepseek_official"
thinking = true
reasoning_effort = "high"
""".strip(),
        encoding="utf-8",
    )

    profile = load_llm_profile(config_path)

    assert profile.provider == "deepseek"
    assert profile.model == "deepseek-v4-pro"
    assert profile.secret_id == "deepseek_official"
    assert "api_key" not in repr(profile).lower()
    assert "sk-" not in repr(profile)


def test_host_loader_passes_secret_only_to_sdk_constructor(tmp_path, monkeypatch):
    secret = "sk-runtime-only-456"
    config_path = tmp_path / "llm.toml"
    secret_path = tmp_path / "secrets.toml"
    config_path.write_text(
        f"""
[llm]
default_profile = "deepseek_main"
secrets_file = "{secret_path.as_posix()}"
enforce_private_secret_file = false

[llm.profiles.deepseek_main]
provider = "deepseek"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-pro"
secret_id = "deepseek_official"
thinking = true
reasoning_effort = "high"
""".strip(),
        encoding="utf-8",
    )
    secret_path.write_text(
        f'[api_keys]\ndeepseek_official = "{secret}"\n',
        encoding="utf-8",
    )

    constructor_calls = []

    def fake_openai(**kwargs):
        constructor_calls.append(kwargs)
        return _FakeClient()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=fake_openai))

    configured = load_configured_llm(config_path)

    assert configured.profile.model == "deepseek-v4-pro"
    assert constructor_calls == [
        {"api_key": secret, "base_url": "https://api.deepseek.com"}
    ]
    assert secret not in repr(configured)
    assert secret not in repr(configured.profile)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits are not portable to Windows")
def test_secret_file_must_not_be_group_or_world_readable_on_posix(tmp_path):
    config_path = tmp_path / "llm.toml"
    secret_path = tmp_path / "secrets.toml"
    config_path.write_text(
        f"""
[llm]
default_profile = "deepseek_main"
secrets_file = "{secret_path.as_posix()}"
enforce_private_secret_file = true

[llm.profiles.deepseek_main]
provider = "deepseek"
model = "deepseek-v4-pro"
secret_id = "deepseek_official"
""".strip(),
        encoding="utf-8",
    )
    secret_path.write_text(
        '[api_keys]\ndeepseek_official = "sk-placeholder"\n',
        encoding="utf-8",
    )
    secret_path.chmod(0o644)

    with pytest.raises(PermissionError, match="chmod 600"):
        load_configured_llm(config_path)
