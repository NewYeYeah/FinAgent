from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.research.us_r1_walkforward import canonical_us_r1_walk_forward


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the canonical US-R1 three-fold walk-forward geometry. The entire "
            "pre-evaluation gap is excluded and later verified to cover the frozen 60m "
            "purge plus 60m embargo. No market data or A0 result is consumed."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r1/us_r1_walk_forward.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    protocol = canonical_us_r1_walk_forward()
    document = protocol.to_dict()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != document:
            raise SystemExit("existing US-R1 walk-forward differs from canonical preregistration")
    else:
        target.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(target),
                "protocol_id": protocol.protocol_id,
                "fold_ids": [fold.fold_id for fold in protocol.folds],
                "fold_count": len(protocol.folds),
                "purge_trading_minutes": 60,
                "embargo_trading_minutes": 60,
                "market_data_read": False,
                "a0_result_read": False,
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
