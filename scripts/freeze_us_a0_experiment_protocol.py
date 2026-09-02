from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from finagent.research.us_agent_value_protocol import (
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)


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
            "Freeze the US-A0 MANUAL/PROGRAMMATIC/AGENT controlled-experiment protocol "
            "before real Agent-value results are inspected. This artifact has no stage-exit, "
            "Agent-value-gate or Alpha authority."
        )
    )
    parser.add_argument(
        "--phase",
        choices=("pilot", "formal"),
        default="pilot",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_a0/us_a0_pilot_preregistration.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    phase = USAgentValuePhase.PILOT if args.phase == "pilot" else USAgentValuePhase.FORMAL
    vocabulary = canonical_us_a0_primitive_vocabulary()
    protocol = canonical_us_a0_experiment_protocol(phase)
    manual = canonical_us_a0_manual_candidates()[: protocol.candidate_budget_per_run]
    payload: dict[str, object] = {
        "schema_version": "finagent.us-agent-value-preregistration-bundle.v1",
        "phase": phase.value,
        "vocabulary": vocabulary.to_dict(),
        "protocol": protocol.to_dict(),
        "manual_candidates": [candidate.to_dict() for candidate in manual],
        "manual_candidate_count": len(manual),
        "scope": "pre_result_controlled_experiment_preregistration_only",
        "status_authority": False,
        "stage_exit_authority": False,
        "agent_value_gate_authority": False,
        "alpha_authority": False,
    }
    payload["bundle_id"] = _canonical_hash(
        payload,
        prefix="us-agent-value-preregistration",
    )

    target = args.output.expanduser().resolve()
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "bundle_id": payload["bundle_id"],
                "protocol_id": protocol.protocol_id,
                "vocabulary_id": vocabulary.vocabulary_id,
                "phase": phase.value,
                "candidate_budget_per_run": protocol.candidate_budget_per_run,
                "manual_candidate_count": len(manual),
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
