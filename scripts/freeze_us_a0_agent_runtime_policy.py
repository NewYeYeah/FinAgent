from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import load_llm_profile
from finagent.research.us_agent_value_execution import validate_us_a0_execution_plan
from finagent.research.us_agent_value_launch import validate_us_a0_pilot_launch_bundle
from finagent.research.us_agent_value_runtime import (
    DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
    build_us_a0_deepseek_runtime_policy,
)

_DEFAULT_A0_LLM_PROFILE = "deepseek_official_v4_flash"


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the US-A0 DeepSeek runtime parameters that affect structured Agent generation. "
            "This reads public routing configuration only; it does not read API secrets or call a model."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default=_DEFAULT_A0_LLM_PROFILE)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEEPSEEK_V4_DEFAULT_MAX_OUTPUT_TOKENS,
        help="Completion budget shared by reasoning_content and final JSON; default 65536.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_a0/pilot_launch/us_a0_agent_runtime_policy.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_mapping(args.preregistration)
    execution_plan_document = _read_mapping(args.execution_plan)
    gate_policy_document = _read_mapping(args.gate_policy)
    launch_bundle_document = _read_mapping(args.launch_bundle)
    _, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration,
    )
    launch_artifacts = validate_us_a0_pilot_launch_bundle(
        launch_bundle_document,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
    )
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    policy = build_us_a0_deepseek_runtime_policy(
        profile=profile,
        execution_plan=execution_plan,
        launch_artifacts=launch_artifacts,
        max_output_tokens=args.max_output_tokens,
    )

    target = args.output.expanduser().resolve()
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(policy.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "runtime_policy_id": policy.runtime_policy_id,
                "execution_plan_id": policy.execution_plan_id,
                "launch_bundle_id": policy.launch_bundle_id,
                "provider": policy.provider_id,
                "model": policy.model_id,
                "thinking_enabled": policy.thinking_enabled,
                "reasoning_effort": policy.reasoning_effort,
                "max_output_tokens": policy.max_output_tokens,
                "maximum_supported_output_tokens": 384000,
                "secrets_loaded": False,
                "external_model_called": False,
                "research_authority": False,
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
