"""Run five deterministic allocators on one frozen within-year fold specification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.application.adaptive_portfolio import load_factor_pool, run_adaptive_portfolio
from finagent.research.adaptive_inputs import bind_development_source
from finagent.research.adaptive_walkforward import WalkForwardFold
from finagent.research.market_state import MarketFeatureConfig
from finagent.research.us_r3_economics import EconomicPolicy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "calendar", "base-plan", "base-evidence", "library", "folds", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-id", "source-revision", "universe"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--factor-ids", help="explicit comma-separated pool; defaults to every registered factor"
    )
    parser.add_argument("--proxy", default="IWM")
    parser.add_argument("--minimum-breadth", type=int, default=20)
    parser.add_argument("--selection-count", type=int, default=5)
    args = parser.parse_args()
    source = bind_development_source(
        args.source,
        args.calendar,
        args.base_plan,
        args.base_evidence,
        source_id=args.source_id,
        source_revision=args.source_revision,
        universe=tuple(args.universe.split(",")),
    )
    factors, binding = load_factor_pool(
        args.library, tuple(args.factor_ids.split(",")) if args.factor_ids else ()
    )
    folds = tuple(
        WalkForwardFold.from_dict(row) for row in json.loads(args.folds.read_text(encoding="utf-8"))
    )
    result = run_adaptive_portfolio(
        source,
        factors,
        folds,
        args.output,
        economics=EconomicPolicy(
            minimum_breadth=args.minimum_breadth, selection_count=args.selection_count
        ),
        feature_config=MarketFeatureConfig(args.proxy),
        library_binding=binding,
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "terminal": result["terminal"],
                "fold_count": len(result["folds"]),
                "allocator_count": 5,
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
