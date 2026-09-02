from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.research.us_r1_gate import canonical_us_r1_alpha_gate_policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the canonical US-R1 Deployment Alpha Gate before robust-research results exist. "
            "The policy is a research/deployment gate only and grants no execution or live authority."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r1/us_r1_alpha_gate_policy.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = canonical_us_r1_alpha_gate_policy()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(policy.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != policy.to_dict():
            raise SystemExit(f"existing US-R1 Alpha Gate policy differs from canonical freeze: {target}")
    else:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    print(
        json.dumps(
            {
                "policy_id": policy.policy_id,
                "protocol_id": policy.protocol_id,
                "min_primary_mean_rank_ic": policy.min_primary_mean_rank_ic,
                "min_worst_fold_rank_ic": policy.min_worst_fold_rank_ic,
                "max_holm_adjusted_pvalue": policy.max_holm_adjusted_pvalue,
                "max_bh_qvalue": policy.max_bh_qvalue,
                "max_session_bootstrap_pvalue": policy.max_session_bootstrap_pvalue,
                "min_frequency_sign_consistency": policy.min_frequency_sign_consistency,
                "min_mean_long_short_return_bps": policy.min_mean_long_short_return_bps,
                "alpha_authority": False,
                "order_authority": False,
                "live_capital_authority": False,
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
