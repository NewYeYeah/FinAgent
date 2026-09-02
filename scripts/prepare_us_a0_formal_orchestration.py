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
    prepare_us_a0_formal_orchestration_checkpoint,
    validate_us_a0_formal_deepseek_runtime_policy,
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
            "Freeze the US-A0 FORMAL PREPARED checkpoint after accepted PILOT progression, "
            "FORMAL launch and DeepSeek runtime policy. No model or market-data call occurs."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--pilot-gate-review", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default="deepseek_official_v4_flash")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_a0/formal_launch/checkpoint_00_prepared.json"),
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
    runtime = validate_us_a0_formal_deepseek_runtime_policy(
        _read_json(args.runtime_policy),
        profile=profile,
        launch_artifacts=launch,
    )
    checkpoint = prepare_us_a0_formal_orchestration_checkpoint(launch, runtime)
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    except FileExistsError as exc:
        raise SystemExit(f"FORMAL PREPARED checkpoint already exists: {target}") from exc
    print(
        json.dumps(
            {
                "phase": "FORMAL",
                "state": checkpoint.state.value,
                "checkpoint_id": checkpoint.checkpoint_id,
                "launch_bundle_id": checkpoint.launch_bundle_id,
                "runtime_policy_id": checkpoint.runtime_policy_id,
                "pilot_gate_review_id": checkpoint.pilot_gate_review_id,
                "agent_run_spec_ids": list(checkpoint.agent_run_spec_ids),
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
