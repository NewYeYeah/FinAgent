from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import load_llm_profile
from finagent.research.us_agent_value_formal_launch import validate_us_a0_formal_launch_bundle
from finagent.research.us_agent_value_formal_runtime import (
    DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
    build_us_a0_formal_deepseek_runtime_policy,
)


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the DeepSeek runtime used by all three US-A0 FORMAL Agent runs. "
            "Requires the exact accepted PILOT review and frozen FORMAL launch."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--pilot-gate-review", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default="deepseek_official_v4_flash")
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_a0/formal_launch/us_a0_formal_runtime_policy.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    execution_plan = _read_json(args.execution_plan)
    gate_policy = _read_json(args.gate_policy)
    pilot_review = _read_json(args.pilot_gate_review)
    status = _read_status(args.status)
    launch = validate_us_a0_formal_launch_bundle(
        _read_json(args.launch_bundle),
        preregistration_document=preregistration,
        execution_plan_document=execution_plan,
        gate_policy_document=gate_policy,
        status_document=status,
        pilot_gate_review_document=pilot_review,
    )
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    policy = build_us_a0_formal_deepseek_runtime_policy(
        profile=profile,
        launch_artifacts=launch,
        max_output_tokens=args.max_output_tokens,
    )
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(policy.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    except FileExistsError as exc:
        raise SystemExit(f"FORMAL runtime policy already exists and cannot be overwritten: {target}") from exc
    print(
        json.dumps(
            {
                "phase": "FORMAL",
                "runtime_policy_id": policy.runtime_policy_id,
                "launch_bundle_id": policy.launch_bundle_id,
                "execution_plan_id": policy.execution_plan_id,
                "pilot_gate_review_id": policy.pilot_gate_review_id,
                "provider": policy.provider_id,
                "model": policy.model_id,
                "reasoning_effort": policy.reasoning_effort,
                "thinking_enabled": policy.thinking_enabled,
                "max_output_tokens": policy.max_output_tokens,
                "external_model_called": False,
                "secrets_loaded": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "output": str(target),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
