from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from finagent.research.us_agent_value_formal_launch import (
    build_us_a0_formal_launch_artifacts,
)


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_once(path: Path, document: Mapping[str, object]) -> Path:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    except FileExistsError as exc:
        raise SystemExit(f"FORMAL launch evidence already exists and cannot be overwritten: {target}") from exc
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the US-A0 FORMAL launch only after docs/status.toml has accepted the exact "
            "PILOT_PROCEED_TO_FORMAL review. Generates deterministic MANUAL/PROGRAMMATIC "
            "control evidence and leaves three real AGENT run IDs pending."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--pilot-gate-review", type=Path, required=True)
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports/us_a0/formal_launch"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    execution_plan = _read_json(args.execution_plan)
    gate_policy = _read_json(args.gate_policy)
    pilot_review = _read_json(args.pilot_gate_review)
    status = _read_status(args.status)
    generated_at = datetime.now(UTC)
    artifacts = build_us_a0_formal_launch_artifacts(
        preregistration_document=preregistration,
        execution_plan_document=execution_plan,
        gate_policy_document=gate_policy,
        status_document=status,
        pilot_gate_review_document=pilot_review,
        control_generated_at=generated_at,
    )

    root = args.output_root.expanduser().resolve()
    manual_output = _write_once(root / "formal_manual_01.json", artifacts.manual_run.to_dict())
    programmatic_outputs: list[str] = []
    for run in artifacts.programmatic_runs:
        target = _write_once(
            root / f"formal_programmatic_{run.spec.run_ordinal:02d}.json",
            run.to_dict(),
        )
        programmatic_outputs.append(str(target))
    bundle_output = _write_once(
        root / "us_a0_formal_launch_bundle.json",
        artifacts.launch_bundle.to_dict(),
    )
    print(
        json.dumps(
            {
                "phase": "FORMAL",
                "launch_bundle_id": artifacts.launch_bundle.launch_bundle_id,
                "execution_plan_id": artifacts.execution_plan.plan_id,
                "gate_policy_id": artifacts.gate_policy.policy_id,
                "pilot_gate_review_id": artifacts.pilot_gate_review_id,
                "control_generated_at": generated_at.isoformat(),
                "manual_generation_run_id": artifacts.manual_run.run_id,
                "programmatic_generation_run_ids": [
                    run.run_id for run in artifacts.programmatic_runs
                ],
                "agent_run_spec_ids": list(artifacts.launch_bundle.agent_run_spec_ids),
                "candidate_budget_per_run": artifacts.protocol.candidate_budget_per_run,
                "external_model_called": False,
                "secrets_loaded": False,
                "financial_data_read": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "manual_output": str(manual_output),
                "programmatic_outputs": programmatic_outputs,
                "bundle_output": str(bundle_output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
