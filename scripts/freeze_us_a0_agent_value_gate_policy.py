from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_agent_value_evaluation import validate_us_a0_preregistration_bundle
from finagent.research.us_agent_value_gate import canonical_us_a0_agent_value_gate_policy
from finagent.research.us_agent_value_protocol import USAgentValuePhase


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


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
            "Freeze the pre-result US-A0 Agent Value Gate policy. The policy defines practical "
            "relative-value thresholds only; it has no project-stage or Alpha authority."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_mapping(args.preregistration)
    phase = USAgentValuePhase(str(preregistration.get("phase", "")).strip())
    protocol = validate_us_a0_preregistration_bundle(preregistration, phase)
    policy = canonical_us_a0_agent_value_gate_policy(phase)
    if policy.protocol_id != protocol.protocol_id:
        raise RuntimeError("canonical Gate policy lost preregistration protocol identity")
    output = _write_json(args.output, policy.to_dict(), overwrite=args.overwrite)
    print(
        json.dumps(
            {
                "phase": phase.value,
                "protocol_id": protocol.protocol_id,
                "policy_id": policy.policy_id,
                "practical_rank_ic_margin": policy.practical_rank_ic_margin,
                "required_agent_run_win_fraction": (
                    f"{policy.required_agent_run_win_numerator}/"
                    f"{policy.required_agent_run_win_denominator}"
                ),
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
