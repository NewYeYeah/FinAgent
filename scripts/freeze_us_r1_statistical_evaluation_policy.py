from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.research.us_r1_evaluation_policy import (
    canonical_us_r1_statistical_evaluation_policy,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze the pre-result US-R1 statistical evaluation policy."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r1/us_r1_statistical_evaluation_policy.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = canonical_us_r1_statistical_evaluation_policy()
    document = policy.to_dict()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != document:
            raise SystemExit("existing US-R1 statistical evaluation policy differs from canonical v1")
    else:
        target.write_text(
            json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "policy_id": policy.policy_id,
                "direction_source_fold_ordinal": policy.direction_source_fold_ordinal,
                "minimum_cross_section": policy.minimum_cross_section,
                "quantile_count": policy.quantile_count,
                "market_data_read": False,
                "a0_result_read": False,
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
