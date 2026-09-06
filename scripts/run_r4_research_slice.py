"""Run/inspect the bounded R4 MarketState + FactorLibrary vertical slice."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from finagent.application.adaptive_research import run_adaptive_research_slice
from finagent.domain.research import TimeRange
from finagent.research.adaptive_inputs import bind_development_source
from finagent.research.factor_library import FactorLibrary, FactorOrigin, FactorRegistration
from finagent.research.factor_library_evaluation import FactorEvaluationConfig
from finagent.research.market_state import MarketFeatureConfig
from finagent.research.market_state_gmm import GMMConfig
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from finagent.research.us_r3_economics import EconomicPolicy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="one declared development fit/project window; no search")
    for name in ("source", "calendar", "base-plan", "base-evidence", "output"):
        run.add_argument("--" + name, type=Path, required=True)
    for name in (
        "source-id",
        "source-revision",
        "universe",
        "fit-start",
        "fit-end",
        "evaluation-start",
        "evaluation-end",
    ):
        run.add_argument("--" + name, required=True)
    run.add_argument("--proxy", default="IWM")
    run.add_argument("--components", type=int, default=4)
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--minimum-breadth", type=int, default=20)
    run.add_argument("--selection-count", type=int, default=5)
    inspect = commands.add_parser("inspect", help="query saved development factors/evaluations")
    inspect.add_argument("--library", type=Path, required=True)
    inspect.add_argument("--factor")
    inspect.add_argument("--as-of", type=datetime.fromisoformat)
    args = parser.parse_args()
    if args.command == "inspect":
        if not args.library.is_file():
            parser.error("library must be an existing file")
        library = FactorLibrary(args.library, read_only=True)
        try:
            if args.factor:
                payload: object = {
                    "factor": library.get(args.factor, as_of=args.as_of),
                    "evaluations": library.evaluations(args.factor, as_of=args.as_of),
                }
            else:
                if args.as_of:
                    parser.error("--as-of requires --factor")
                payload = library.list_factors()
            print(json.dumps(payload, sort_keys=True, allow_nan=False))
        finally:
            library.close()
        return 0
    fit_window = TimeRange(
        datetime.fromisoformat(args.fit_start), datetime.fromisoformat(args.fit_end)
    )
    evaluation_window = TimeRange(
        datetime.fromisoformat(args.evaluation_start), datetime.fromisoformat(args.evaluation_end)
    )
    source = bind_development_source(
        args.source,
        args.calendar,
        args.base_plan,
        args.base_evidence,
        source_id=args.source_id,
        source_revision=args.source_revision,
        universe=tuple(args.universe.split(",")),
    )
    # Keep a small existing prototype pool. Its previous negative R3 result is
    # explicit provenance, not silently reset or promoted to an ACTIVE strategy.
    factors = tuple(
        FactorRegistration(
            item.graph,
            item.strategy.slug,
            item.strategy.mechanism,
            item.hypothesis.summary,
            FactorOrigin.MANUAL,
            (
                ("catalog", "existing_r3_frontier_prototypes"),
                ("strategy_id", item.strategy.strategy_id),
                ("prior_research_terminal", "WORKFLOW_VERIFIED_NO_CONFIRMED_ALPHA"),
            ),
            fit_window.start,
        )
        for item in build_us_r3_executable_frontier_candidates()
    )
    result = run_adaptive_research_slice(
        source,
        factors,
        fit_window,
        evaluation_window,
        args.output,
        feature_config=MarketFeatureConfig(proxy_asset=args.proxy),
        gmm_config=GMMConfig(n_components=args.components, random_seed=args.seed),
        evaluation_config=FactorEvaluationConfig(
            EconomicPolicy(
                minimum_breadth=args.minimum_breadth,
                selection_count=args.selection_count,
            )
        ),
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "terminal": result["terminal"],
                "model_id": result["model_id"],
                "factor_count": len(factors),
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
