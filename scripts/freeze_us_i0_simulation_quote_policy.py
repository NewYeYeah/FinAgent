from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from finagent.data.us_delayed_reference_quotes import (
    CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY,
    validate_canonical_us_simulation_quote_timing_policy,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the canonical no-account MetaQuotes-Demo 15-minute delayed-reference "
            "timing policy. This does not change the existing live/current quote Gate."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_instruments/us_i0_simulation_quote_policy.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY
    document = policy.to_dict()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        existing = validate_canonical_us_simulation_quote_timing_policy(
            _read_mapping(output)
        )
        if existing.to_dict() != document:
            raise RuntimeError("existing simulation quote policy differs from canonical v1")
    else:
        output.write_text(
            json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "policy_id": policy.policy_id,
                "source_regime": policy.source_regime,
                "expected_broker_server": policy.expected_broker_server,
                "broker_account_required": policy.broker_account_required,
                "expected_source_delay_seconds": policy.expected_source_delay_seconds,
                "validation_anchor_semantics": (
                    "retrieved_at_utc_minus_expected_source_delay"
                ),
                "raw_live_quote_policy_unchanged": True,
                "live_market_data_authority": False,
                "execution_authority": False,
                "order_authority": False,
                "live_capital_authority": False,
                "status_authority": False,
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
