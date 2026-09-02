from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from finagent.research.us_agent_value_execution import validate_us_a0_execution_plan
from finagent.research.us_agent_value_generation import (
    build_candidate_generation_run,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
)
from finagent.research.us_agent_value_protocol import USAgentValueArm


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--generated-at must be timezone-aware ISO-8601")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a preregistered MANUAL or PROGRAMMATIC US-A0 generation run. "
            "This does not read financial data and does not run an LLM."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--arm", choices=("manual", "programmatic"), required=True)
    parser.add_argument("--run-ordinal", type=int, default=1)
    parser.add_argument(
        "--generated-at",
        type=_aware,
        default=None,
        help="Optional aware timestamp. Defaults to the current UTC time.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_mapping(args.preregistration.expanduser().resolve())
    execution_plan_document = _read_mapping(args.execution_plan.expanduser().resolve())
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration,
    )
    arm = USAgentValueArm.MANUAL if args.arm == "manual" else USAgentValueArm.PROGRAMMATIC
    matching = tuple(
        item
        for item in execution_plan.run_specs
        if item.arm is arm and item.run_ordinal == args.run_ordinal
    )
    if len(matching) != 1:
        raise SystemExit(
            f"execution plan does not authorize exactly one {arm.value} run ordinal {args.run_ordinal}"
        )
    spec = matching[0]
    generated_at = args.generated_at or datetime.now(UTC)
    if arm is USAgentValueArm.MANUAL:
        slots = manual_proposal_slots(protocol, generated_at=generated_at)
    else:
        if spec.random_seed is None:  # pragma: no cover - run-spec invariant
            raise RuntimeError("PROGRAMMATIC run spec is missing its frozen seed")
        slots = deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=spec.random_seed,
            generated_at=generated_at,
        )
    run = build_candidate_generation_run(protocol, spec, slots)

    target = args.output.expanduser().resolve()
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(run.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_id": run.run_id,
                "run_spec_id": run.spec.run_spec_id,
                "phase": run.spec.phase.value,
                "arm": run.spec.arm.value,
                "run_ordinal": run.spec.run_ordinal,
                "candidate_budget": run.spec.candidate_budget,
                "accepted_candidate_count": len(run.accepted_candidates),
                "invalid_slot_count": run.invalid_slot_count,
                "duplicate_slot_count": run.duplicate_slot_count,
                "repair_count": run.repair_count,
                "agent_value_gate_authority": False,
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
