from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from finagent.agents.providers import LLMRequest, load_configured_llm
from finagent.research.us_agent_value_deepseek import (
    DEEPSEEK_V4_PRICING_POLICY_ID,
    estimate_deepseek_v4_cost_usd,
)
from finagent.research.us_agent_value_runtime import (
    DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
    DEEPSEEK_V4_MAX_OUTPUT_TOKENS,
)

_DEFAULT_SMOKE_PROFILE = "deepseek_official_v4_flash"


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Call one configured LLM profile with a tiny structured-JSON request. This is an "
            "engineering connectivity/JSON/usage smoke only and has no US-A0 research authority."
        )
    )
    parser.add_argument("--config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument(
        "--profile",
        default=_DEFAULT_SMOKE_PROFILE,
        help="Engineering smoke defaults to official DeepSeek V4-Flash.",
    )
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
        help=(
            "Completion budget shared by DeepSeek reasoning_content and final content. "
            "Default 65536; DeepSeek V4 current maximum is 384000."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/llm/llm_profile_smoke.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.max_output_tokens <= DEEPSEEK_V4_MAX_OUTPUT_TOKENS:
        raise SystemExit(
            f"--max-output-tokens must be in [1,{DEEPSEEK_V4_MAX_OUTPUT_TOKENS}]"
        )
    configured = load_configured_llm(
        args.config.expanduser().resolve(),
        profile_name=args.profile,
        secrets_path=(None if args.secrets is None else args.secrets.expanduser().resolve()),
    )
    request = LLMRequest(
        request_id="finagent-llm-profile-smoke-v1",
        model=configured.profile.model,
        instructions=(
            "Return only the requested tiny JSON capability acknowledgement. Do not include "
            "explanatory prose."
        ),
        input_text=json.dumps(
            {
                "task": "FinAgent configured-provider engineering smoke",
                "required_response": {"ok": True, "capability": "structured_json"},
            },
            sort_keys=True,
        ),
        schema_name="finagent_llm_profile_smoke_v1",
        response_schema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "capability": {"type": "string"},
            },
            "required": ["ok", "capability"],
            "additionalProperties": False,
        },
        max_output_tokens=args.max_output_tokens,
        temperature=None,
        metadata={
            "scope": "engineering_smoke_only",
            "max_output_tokens": str(args.max_output_tokens),
        },
    )
    response = configured.provider.complete(request)
    retrieved_at = datetime.now(UTC)
    try:
        parsed = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"LLM smoke response is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        raise SystemExit("LLM smoke response did not acknowledge ok=true")
    if parsed.get("capability") != "structured_json":
        raise SystemExit("LLM smoke response capability mismatch")

    cost_usd = 0.0
    pricing_policy_id: str | None = None
    if configured.profile.provider == "deepseek" and configured.profile.model in {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    }:
        cost_usd = estimate_deepseek_v4_cost_usd(
            configured.profile.model,
            response,
            priced_at=retrieved_at,
        )
        pricing_policy_id = DEEPSEEK_V4_PRICING_POLICY_ID

    payload: dict[str, object] = {
        "schema_version": "finagent.llm-profile-smoke.v1",
        "profile": configured.profile.name,
        "provider": configured.profile.provider,
        "configured_model": configured.profile.model,
        "response_model": response.model,
        "base_url": configured.profile.base_url,
        "thinking": configured.profile.thinking,
        "reasoning_effort": configured.profile.reasoning_effort,
        "max_output_tokens": args.max_output_tokens,
        "retrieved_at": retrieved_at.isoformat(),
        "passed": True,
        "blockers": [],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "cached_input_tokens": response.usage.cached_input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
            "latency_ms": response.latency_ms,
            "cost_usd": cost_usd,
            "pricing_policy_id": pricing_policy_id,
        },
        "provider_status": response.status,
        "provider_attempts": response.metadata.get("provider_attempts", "1"),
        "reasoning_tokens": response.metadata.get("reasoning_tokens", "0"),
        "completion_budget_semantics": (
            "reasoning_content_and_final_content_share_max_output_tokens"
        ),
        "scope": "engineering_smoke_only_not_us_a0_generation_or_gate_evidence",
        "research_authority": False,
        "stage_exit_authority": False,
        "agent_value_gate_authority": False,
        "alpha_authority": False,
    }
    payload["report_id"] = _canonical_hash(payload, prefix="llm-profile-smoke")
    target = args.output.expanduser().resolve()
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**payload, "output": str(target)}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
