from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the canonical US-R1 intraday research protocol before any R1 result exists. "
            "This does not read A0 results, market data or secrets and has no stage authority."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r1/us_r1_research_protocol.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    protocol = canonical_us_r1_research_protocol()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(protocol.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != protocol.to_dict():
            raise SystemExit(f"existing US-R1 protocol differs from canonical freeze: {target}")
    else:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    print(
        json.dumps(
            {
                "protocol_id": protocol.protocol_id,
                "primary_interval": protocol.primary_interval.value,
                "robustness_intervals": [item.value for item in protocol.robustness_intervals],
                "label_horizon_trading_minutes": protocol.label_horizon_trading_minutes,
                "purge_trading_minutes": protocol.purge_trading_minutes,
                "embargo_trading_minutes": protocol.embargo_trading_minutes,
                "bootstrap_samples": protocol.bootstrap_samples,
                "bootstrap_block_sessions": protocol.bootstrap_block_sessions,
                "candidate_admission_rule": protocol.candidate_admission_rule,
                "status_authority": False,
                "alpha_authority": False,
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
