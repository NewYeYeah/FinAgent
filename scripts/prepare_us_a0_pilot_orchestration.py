from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import load_llm_profile
from finagent.research.us_agent_value_launch import (
    assess_us_a0_pilot_launch_readiness,
    validate_us_a0_pilot_launch_bundle,
)
from finagent.research.us_agent_value_orchestration import (
    prepare_us_a0_pilot_orchestration_checkpoint,
)
from finagent.research.us_agent_value_runtime import validate_us_a0_deepseek_runtime_policy

_DEFAULT_A0_LLM_PROFILE = "deepseek_official_v4_flash"


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
            "Create the append-only PREPARED checkpoint for the frozen US-A0 PILOT. "
            "This is pre-result orchestration metadata only; no API secret, model or market data is used."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default=_DEFAULT_A0_LLM_PROFILE)
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_a0/pilot_launch/checkpoint_00_prepared.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    execution_plan = _read_json(args.execution_plan)
    gate_policy = _read_json(args.gate_policy)
    launch_bundle = _read_json(args.launch_bundle)
    runtime_policy_document = _read_json(args.runtime_policy)
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    launch_artifacts = validate_us_a0_pilot_launch_bundle(
        launch_bundle,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan,
        gate_policy_document=gate_policy,
    )
    _, runtime_policy = validate_us_a0_deepseek_runtime_policy(
        runtime_policy_document,
        profile=profile,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan,
        gate_policy_document=gate_policy,
        launch_bundle_document=launch_bundle,
    )
    checkpoint = prepare_us_a0_pilot_orchestration_checkpoint(
        launch_artifacts.launch_bundle,
        runtime_policy,
    )
    readiness = assess_us_a0_pilot_launch_readiness(
        _read_status(args.status),
        launch_artifacts.launch_bundle,
    )

    target = args.output.expanduser().resolve()
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(checkpoint.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "checkpoint_id": checkpoint.checkpoint_id,
                "state": checkpoint.state.value,
                "launch_bundle_id": checkpoint.launch_bundle_id,
                "runtime_policy_id": checkpoint.runtime_policy_id,
                "execution_plan_id": checkpoint.execution_plan_id,
                "agent_run_spec_id": checkpoint.agent_run_spec_id,
                "max_output_tokens": runtime_policy.max_output_tokens,
                "ready_for_external_agent_generation": (
                    readiness.ready_for_external_agent_generation
                ),
                "blockers": list(readiness.blockers),
                "secrets_loaded": False,
                "external_model_called": False,
                "financial_data_read": False,
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
