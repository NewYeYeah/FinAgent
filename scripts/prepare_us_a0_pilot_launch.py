from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from finagent.research.us_agent_value_launch import build_us_a0_pilot_launch_artifacts


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--control-generated-at must be timezone-aware ISO-8601")
    return parsed.astimezone(UTC)


def _write_json(path: Path, payload: Mapping[str, object], *, overwrite: bool) -> Path:
    target = path.expanduser().resolve()
    if target.exists() and not overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the pre-result US-A0 PILOT launch bundle and exact deterministic MANUAL / "
            "PROGRAMMATIC generation evidence. No API secret, external model or financial data "
            "is accessed. The AGENT run-spec identity is frozen but its real generation-run ID "
            "remains pending future stage-authorized execution."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument(
        "--control-generated-at",
        type=_aware,
        default=None,
        help=(
            "Optional aware timestamp used for both deterministic control runs. Defaults to the "
            "current UTC time and is then frozen into the launch identity."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports/us_a0/pilot_launch"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    generated_at = args.control_generated_at or datetime.now(UTC)
    artifacts = build_us_a0_pilot_launch_artifacts(
        preregistration_document=_read_json(args.preregistration),
        execution_plan_document=_read_json(args.execution_plan),
        gate_policy_document=_read_json(args.gate_policy),
        control_generated_at=generated_at,
    )
    output_root = args.output_root.expanduser().resolve()
    manual_output = _write_json(
        output_root / "pilot_manual_01.json",
        artifacts.manual_run.to_dict(),
        overwrite=args.overwrite,
    )
    programmatic_outputs = tuple(
        _write_json(
            output_root / f"pilot_programmatic_{run.spec.run_ordinal:02d}.json",
            run.to_dict(),
            overwrite=args.overwrite,
        )
        for run in artifacts.programmatic_runs
    )
    bundle_output = _write_json(
        output_root / "us_a0_pilot_launch_bundle.json",
        artifacts.launch_bundle.to_dict(),
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "launch_bundle_id": artifacts.launch_bundle.launch_bundle_id,
                "phase": artifacts.launch_bundle.phase.value,
                "preregistration_bundle_id": artifacts.launch_bundle.preregistration_bundle_id,
                "execution_plan_id": artifacts.launch_bundle.execution_plan_id,
                "gate_policy_id": artifacts.launch_bundle.gate_policy_id,
                "control_generated_at": artifacts.launch_bundle.control_generated_at.isoformat(),
                "manual_generation_run_id": artifacts.manual_run.run_id,
                "programmatic_generation_run_ids": [
                    run.run_id for run in artifacts.programmatic_runs
                ],
                "agent_run_spec_ids": list(artifacts.launch_bundle.agent_run_spec_ids),
                "agent_provider": artifacts.launch_bundle.agent_provider_id,
                "agent_model": artifacts.launch_bundle.agent_model_id,
                "agent_prompt_template": artifacts.launch_bundle.agent_prompt_template_id,
                "secrets_loaded": False,
                "external_model_called": False,
                "financial_data_read": False,
                "research_authority": False,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "bundle_output": str(bundle_output),
                "manual_output": str(manual_output),
                "programmatic_outputs": [str(path) for path in programmatic_outputs],
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
