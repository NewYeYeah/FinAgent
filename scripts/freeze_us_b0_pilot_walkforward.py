from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the deterministic US-B0 pilot walk-forward design before any formal "
            "baseline result is inspected. This does not require or imply US-D3 acceptance."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_b0/us_b0_pilot_walkforward_protocol.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    protocol = canonical_us_b0_pilot_walk_forward()
    output = args.output.expanduser().resolve()
    if output.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(protocol.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "protocol_id": protocol.protocol_id,
                "fold_count": len(protocol.folds),
                "selection_authority": False,
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
