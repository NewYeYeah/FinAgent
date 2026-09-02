from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_agent_value_launch import (
    assess_us_a0_pilot_launch_readiness,
    validate_us_a0_pilot_control_documents,
    validate_us_a0_pilot_launch_bundle,
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
            "Validate the exact frozen US-A0 PILOT launch/control evidence and report whether "
            "project-stage authority currently permits the external AGENT generation call. "
            "This command never reads LLM secrets, calls a model or reads financial data."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--manual-run", type=Path, required=True)
    parser.add_argument(
        "--programmatic-run",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    execution_plan = _read_json(args.execution_plan)
    gate_policy = _read_json(args.gate_policy)
    launch_document = _read_json(args.launch_bundle)
    artifacts = validate_us_a0_pilot_launch_bundle(
        launch_document,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan,
        gate_policy_document=gate_policy,
    )
    control_documents = (
        _read_json(args.manual_run),
        *tuple(_read_json(path) for path in args.programmatic_run),
    )
    controls = validate_us_a0_pilot_control_documents(artifacts, control_documents)
    readiness = assess_us_a0_pilot_launch_readiness(
        _read_status(args.status),
        artifacts.launch_bundle,
    )
    print(
        json.dumps(
            {
                **readiness.to_dict(),
                "control_run_ids": [run.run_id for run in controls],
                "agent_run_spec_ids": list(artifacts.launch_bundle.agent_run_spec_ids),
                "agent_provider": artifacts.launch_bundle.agent_provider_id,
                "agent_model": artifacts.launch_bundle.agent_model_id,
                "secrets_loaded": False,
                "external_model_called": False,
                "financial_data_read": False,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
