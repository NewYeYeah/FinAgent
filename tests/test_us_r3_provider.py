from pathlib import Path

import pytest

from finagent.agents.r3_provider import StrictDeepSeekProvider, parse_reply
from finagent.agents.r3_runtime import ResearchRequest


def payload():
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": "{}", "reasoning_content": "never persist"},
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 50,
            "prompt_cache_miss_tokens": 50,
        },
    }


def test_verified_cache_usage_and_peak_cost_bound():
    reply = parse_reply(payload(), token_cap=200, input_cap=110, output_cap=30)
    assert reply.used_tokens == 120
    assert reply.cost_microusd == 148
    assert reply.action_json == "{}"


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_tokens", 121),
        ("prompt_tokens", 0),
        ("completion_tokens", True),
        ("prompt_cache_hit_tokens", 51),
    ],
)
def test_inconsistent_or_unknown_usage_fails_closed(field, value):
    data = payload()
    data["usage"][field] = value
    with pytest.raises(ValueError):
        parse_reply(data, token_cap=200, input_cap=110, output_cap=30)


def test_truncation_cannot_be_admitted_as_complete_action():
    data = payload()
    data["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ValueError, match="incomplete"):
        parse_reply(data, token_cap=200, input_cap=110, output_cap=30)


def test_budget_rejected_before_transport_spawn(monkeypatch):
    monkeypatch.setattr(
        "finagent.agents.r3_provider.mp.get_context", lambda *a: pytest.fail("must not spawn")
    )
    provider = StrictDeepSeekProvider(Path("not-read"), "instruction")
    with pytest.raises(ValueError, match="budget"):
        provider.respond(ResearchRequest("req", "context", 100, 1, 1))


def test_worker_single_post_strips_reasoning_and_never_retries(monkeypatch):
    from types import SimpleNamespace

    from finagent.agents import r3_provider
    from finagent.agents.providers import config

    monkeypatch.setattr(
        config,
        "load_llm_profile",
        lambda p: SimpleNamespace(
            provider="deepseek",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            secret_id="dummy",
        ),
    )
    monkeypatch.setattr(config, "_llm_table", lambda p: {})
    monkeypatch.setattr(config, "_configured_secrets_path", lambda **k: Path("unused"))
    monkeypatch.setattr(config, "_read_api_key", lambda **k: "synthetic-test-secret")
    sent, posts = [], []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"is_available": True})

        def post(self, *args, **kwargs):
            posts.append(kwargs["json"])
            return SimpleNamespace(status_code=200, json=payload)

    monkeypatch.setattr("httpx.Client", Client)
    pipe = SimpleNamespace(send=sent.append, close=lambda: None)
    r3_provider._worker(pipe, "unused", "context", "instruction", 30, 1)
    assert len(posts) == 1
    assert posts[0]["thinking"] == {"type": "disabled"}
    assert "reasoning" not in str(sent)
    assert "synthetic-test-secret" not in str(sent)

    def fail(*a, **k):
        posts.append("failed")
        raise RuntimeError("synthetic-test-secret")

    monkeypatch.setattr(Client, "post", fail)
    r3_provider._worker(pipe, "unused", "context", "instruction", 30, 1)
    assert len(posts) == 2
    assert sent[-1] == {"error": "transport_uncertain"}


def test_deadline_terminates_worker_without_resending(monkeypatch):
    from types import SimpleNamespace

    calls = []
    process = SimpleNamespace(
        start=lambda: calls.append("start"),
        is_alive=lambda: True,
        terminate=lambda: calls.append("terminate"),
        join=lambda **k: calls.append("join"),
    )
    parent = SimpleNamespace(poll=lambda t: False, close=lambda: None)
    child = SimpleNamespace(close=lambda: None)
    context = SimpleNamespace(Pipe=lambda **k: (parent, child), Process=lambda **k: process)
    monkeypatch.setattr("finagent.agents.r3_provider.mp.get_context", lambda *a: context)
    with pytest.raises(TimeoutError):
        StrictDeepSeekProvider(Path("unused"), "instruction").respond(
            ResearchRequest("r", "c", 16384, 50000, 1)
        )
    assert calls == ["start", "terminate", "join"]
