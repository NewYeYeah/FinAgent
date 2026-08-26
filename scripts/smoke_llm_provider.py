from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.agents.providers import LLMRequest, load_configured_llm


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a minimal structured-output smoke test against one configured LLM provider."
    )
    parser.add_argument("config", type=Path, help="public LLM TOML configuration")
    parser.add_argument("--profile", help="LLM profile name; defaults to [llm].default_profile")
    parser.add_argument(
        "--secrets",
        type=Path,
        help="optional secret-file path override; the secret value is never printed",
    )
    args = parser.parse_args()

    configured = load_configured_llm(
        args.config,
        profile_name=args.profile,
        secrets_path=args.secrets,
    )
    request = LLMRequest(
        request_id="llm-provider-smoke",
        model=configured.model,
        instructions=(
            "This is a FinAgent provider connectivity test. Return a minimal JSON object "
            "confirming that structured output works."
        ),
        input_text=(
            f"Return ok=true and provider={configured.profile.provider!r}. "
            "Do not include credentials or configuration paths."
        ),
        schema_name="finagent_provider_smoke",
        response_schema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "provider": {"type": "string"},
            },
            "required": ["ok", "provider"],
            "additionalProperties": False,
        },
        max_output_tokens=1024,
    )
    response = configured.provider.complete(request)
    payload = json.loads(response.output_text)
    if not isinstance(payload, dict):
        raise RuntimeError("LLM smoke response must be a JSON object")
    if payload.get("ok") is not True:
        raise RuntimeError("LLM smoke response did not return ok=true")

    report = {
        "profile": configured.profile.name,
        "provider": response.provider,
        "model": response.model,
        "response_id": response.response_id,
        "status": response.status,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
            "cached_input_tokens": response.usage.cached_input_tokens,
        },
        "latency_ms": response.latency_ms,
        "output": payload,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
