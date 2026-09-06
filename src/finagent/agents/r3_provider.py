"""Single-attempt DeepSeek transport, killable deadline and verified token usage.

Only visible action content is returned. Credentials/reasoning never enter the
ledger. Charged USD is a conservative PEAK-tariff bound, not an invoice claim.
"""

from __future__ import annotations

import math
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

from finagent.agents.r3_runtime import ProviderQuotaExhausted, ResearchReply, ResearchRequest

TARIFF = {
    "cache_hit_microusd_per_token": 0.044,
    "cache_miss_microusd_per_token": 1.32,
    "output_microusd_per_token": 3.96,
    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    "verified_date": "2026-09-06",
    "scope": "deepseek-v4-pro peak upper bound; actual off-peak invoice can be lower",
}


def parse_reply(
    payload: dict[str, Any], *, token_cap: int, input_cap: int, output_cap: int
) -> ResearchReply:
    usage = payload.get("usage", {})
    keys = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    )
    if any(type(usage.get(k)) is not int or usage[k] < 0 for k in keys):
        raise ValueError("provider_usage_unverified")
    inp, out, total, hit, miss = (usage[k] for k in keys)
    if (
        inp + out != total
        or hit + miss != inp
        or total <= 0
        or total > token_cap
        or inp > input_cap
        or out > output_cap
    ):
        raise ValueError("provider_usage_breach")
    choices = payload.get("choices", [])
    if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
        raise ValueError("provider_incomplete_action")
    action = choices[0].get("message", {}).get("content")
    if not isinstance(action, str) or len(action.encode()) > 32768:
        raise ValueError("provider_action_bound")
    return ResearchReply(action, total, math.ceil(hit * 0.044 + miss * 1.32 + out * 3.96))


def _worker(
    connection: Any,
    config_path: str,
    context: str,
    instruction: str,
    output_cap: int,
    timeout: float,
    profile_name: str | None = None,
) -> None:
    stage = "profile"
    try:
        import httpx

        from finagent.agents.providers.config import (
            _configured_secrets_path,
            _llm_table,
            _read_api_key,
            load_llm_profile,
        )

        profile = load_llm_profile(config_path, profile_name=profile_name)
        if (
            profile.provider != "deepseek"
            or profile.model != "deepseek-v4-pro"
            or profile.base_url.rstrip("/") != "https://api.deepseek.com"
        ):
            raise ValueError("provider_not_admitted")
        if profile_name is not None and (
            profile.thinking is not False
            or profile.max_attempts != 1
            or profile.reasoning_effort is not None
            or profile.timeout_seconds != 120.0
        ):
            raise ValueError("provider_profile_mismatch")
        table = _llm_table(Path(config_path))
        stage = "credential"
        secret = _read_api_key(
            secret_path=_configured_secrets_path(llm=table, explicit_path=None),
            secret_id=profile.secret_id,
            enforce_private_permissions=True,
        )
        stage = "transport"
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            headers = {"Authorization": "Bearer " + secret}
            quota = client.get("https://api.deepseek.com/user/balance", headers=headers)
            if quota.status_code != 200 or quota.json().get("is_available") is not True:
                connection.send({"error": "quota_unavailable"})
                return
            response = client.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json={
                    "model": profile.model,
                    "messages": [
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": context},
                    ],
                    "thinking": {"type": "disabled"},
                    "max_tokens": output_cap,
                    "temperature": 0.7,
                    "response_format": {"type": "json_object"},
                    "stream": False,
                },
            )
            if response.status_code != 200:
                connection.send(
                    {
                        "error": "quota_unavailable"
                        if response.status_code in (402, 429)
                        else "transport_uncertain"
                    }
                )
                return
            payload = response.json()
            # Strip all fields that could contain hidden reasoning before IPC.
            connection.send(
                {
                    "model": payload.get("model"),
                    "id": payload.get("id"),
                    "system_fingerprint": payload.get("system_fingerprint"),
                    "usage": payload.get("usage"),
                    "choices": [
                        {
                            "finish_reason": c.get("finish_reason"),
                            "message": {"content": c.get("message", {}).get("content")},
                        }
                        for c in payload.get("choices", [])
                    ],
                }
            )
    except Exception:  # noqa: BLE001 -- sanitize the worker boundary.
        connection.send(
            {
                "error": {
                    "profile": "provider_profile_mismatch",
                    "credential": "credential_unavailable",
                }.get(stage, "transport_uncertain")
            }
        )
    finally:
        connection.close()


class StrictDeepSeekProvider:
    def __init__(
        self, config_path: Path, instruction: str, *, profile_name: str | None = None
    ) -> None:
        self.config_path = config_path
        self.instruction = instruction
        self.profile_name = profile_name
        self.last_receipt: dict[str, Any] | None = None

    def respond(self, request: ResearchRequest) -> ResearchReply:
        self.last_receipt = None
        input_cap = len((request.context_json + self.instruction).encode()) + 1024
        output_cap = min(3000, request.maximum_total_tokens - input_cap)
        if (
            output_cap < 256
            or math.ceil(input_cap * 1.32 + output_cap * 3.96) > request.maximum_cost_microusd
        ):
            raise ValueError("transport_budget_not_feasible")
        context = mp.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(
            target=_worker,
            args=(
                child,
                str(self.config_path),
                request.context_json,
                self.instruction,
                output_cap,
                max(0.1, request.timeout_seconds - 2),
                self.profile_name,
            ),
        )
        process.daemon = True
        started = time.monotonic()
        process.start()
        child.close()
        try:
            if not parent.poll(
                max(0.01, request.timeout_seconds - 1 - (time.monotonic() - started))
            ):
                raise TimeoutError("transport_deadline")
            payload = parent.recv()
            if payload.get("error") == "quota_unavailable":
                raise ProviderQuotaExhausted("provider_quota")
            if "error" in payload:
                raise ValueError(
                    payload["error"]
                    if payload["error"] in {"provider_profile_mismatch", "credential_unavailable"}
                    else "transport_uncertain"
                )
            reply = parse_reply(
                payload,
                token_cap=request.maximum_total_tokens,
                input_cap=input_cap,
                output_cap=output_cap,
            )
            if self.profile_name is not None:
                if payload.get("model") != "deepseek-v4-pro" or not isinstance(
                    payload.get("id"), str
                ):
                    raise ValueError("provider_response_identity_mismatch")
                self.last_receipt = {
                    "model_id": payload["model"],
                    "response_id": payload["id"],
                    "system_fingerprint": payload.get("system_fingerprint"),
                    "usage": {
                        k: payload["usage"][k]
                        for k in (
                            "prompt_tokens",
                            "completion_tokens",
                            "total_tokens",
                            "prompt_cache_hit_tokens",
                            "prompt_cache_miss_tokens",
                        )
                    },
                    "cost_microusd": reply.cost_microusd,
                    "quota_available": True,
                }
                reply = ResearchReply(
                    reply.action_json,
                    reply.used_tokens,
                    reply.cost_microusd,
                    payload["usage"]["prompt_tokens"],
                    payload["usage"]["completion_tokens"],
                )
            return reply
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            parent.close()
