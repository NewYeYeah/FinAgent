from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.research.us_r1_materialization import canonical_us_r1_feature_formation_policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze US-R1 multi-frequency feature-formation semantics. Structural A0 "
            "window_bars are preserved at 5m/15m/30m and evaluated by the existing B0/A0 "
            "feature evaluator. No A0 result or market data is consumed."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r1/us_r1_feature_formation_policy.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = canonical_us_r1_feature_formation_policy()
    document = policy.to_dict()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != document:
            raise SystemExit("existing US-R1 feature-formation policy differs from canonical policy")
    else:
        target.write_text(
            json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "output": str(target),
                "policy_id": policy.policy_id,
                "window_semantics": policy.window_semantics,
                "supported_intervals": [item.value for item in policy.supported_intervals],
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
