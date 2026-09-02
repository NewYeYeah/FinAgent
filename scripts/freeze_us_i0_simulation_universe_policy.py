from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data.us_simulation_universe import (
    CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the canonical no-account US-I0 simulation EngineeringUniverse "
            "finalization policy. The policy uses delayed-reference spread only as "
            "an engineering diagnostic and carries no live/execution authority."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "reports/us_instruments/us_i0_simulation_universe_policy.json"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(policy.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "policy_id": policy.policy_id,
                "target_count": policy.target_count,
                "minimum_count": policy.minimum_count,
                "maximum_count": policy.maximum_count,
                "maximum_reference_spread_bps": policy.maximum_reference_spread_bps,
                "maximum_inventory_age_seconds": policy.maximum_inventory_age_seconds,
                "spread_semantics": "delayed_reference_diagnostic_only",
                "broker_account_required": False,
                "live_executable_spread_authority": False,
                "execution_authority": False,
                "stage_exit_authority": False,
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
