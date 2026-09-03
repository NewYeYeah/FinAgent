from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from finagent.data.us_minute.simulation_certification import (
    CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY,
    validate_canonical_us_simulation_d3_certification_policy,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the canonical simulation-limited US-D3 certification policy. "
            "The policy never promotes delayed-reference or all-day fixture evidence to "
            "live/execution authority."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_d3/us_d3_simulation_certification_policy.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY
    document = policy.to_dict()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        existing = validate_canonical_us_simulation_d3_certification_policy(
            _read_mapping(output)
        )
        if existing.to_dict() != document:
            raise RuntimeError("existing simulation D3 policy differs from canonical v1")
    else:
        output.write_text(
            json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "policy_id": policy.policy_id,
                "core_policy_id": policy.core_policy.policy_id,
                "expected_simulation_universe_policy_id": (
                    policy.expected_simulation_universe_policy_id
                ),
                "all_day_preflight_in_certification_denominator": False,
                "live_broker_re_admission_required": True,
                "stage_exit_authority": False,
                "status_authority": False,
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
