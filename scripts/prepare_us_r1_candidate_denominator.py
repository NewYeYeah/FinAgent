from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_r1_handoff import (
    build_authorized_us_r1_candidate_denominator_from_documents,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        value = tomllib.load(handle)
    return cast(Mapping[str, object], value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the exact US-R1 structural candidate denominator from the accepted terminal "
            "US-A0 experiment. All generation runs are rehashed and matched to the experiment; "
            "A0 performance metrics do not filter candidate admission. Requires current_stage=US-R1."
        )
    )
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument("--a0-preregistration", type=Path, required=True)
    parser.add_argument("--a0-execution-plan", type=Path, required=True)
    parser.add_argument("--a0-experiment", type=Path, required=True)
    parser.add_argument("--a0-gate-review", type=Path, required=True)
    parser.add_argument(
        "--generation-run",
        type=Path,
        action="append",
        required=True,
        help="Repeat for every generation run embedded by identity in the terminal A0 experiment.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    denominator = build_authorized_us_r1_candidate_denominator_from_documents(
        status_document=_read_status(args.status),
        preregistration_document=_read_mapping(args.a0_preregistration),
        execution_plan_document=_read_mapping(args.a0_execution_plan),
        experiment_document=_read_mapping(args.a0_experiment),
        gate_review_document=_read_mapping(args.a0_gate_review),
        generation_run_documents=tuple(_read_mapping(path) for path in args.generation_run),
    )
    document = denominator.to_dict()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != document:
            raise SystemExit("existing US-R1 candidate denominator differs from authorized handoff")
    else:
        target.write_text(
            json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "output": str(target),
                "denominator_id": denominator.denominator_id,
                "candidate_count": len(denominator.candidates),
                "a0_phase": denominator.a0_phase.value,
                "a0_gate_review_id": denominator.a0_gate_review_id,
                "a0_gate_decision": denominator.a0_gate_decision.value,
                "agent_scope": denominator.agent_scope.value,
                "performance_filter_applied": False,
                "market_data_read": False,
                "status_authority": False,
                "alpha_authority": False,
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
