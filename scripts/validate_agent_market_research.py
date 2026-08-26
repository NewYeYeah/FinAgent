#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data import read_normalized_csv
from finagent.data.ingestion.diff import compare_provider_records
from finagent.research import (
    AgentMarketValidationPolicy,
    SQLiteAgentMarketValidationStore,
    read_agent_market_result,
    validate_agent_market_results,
)


def _metric_limit(value: str) -> tuple[str, float]:
    try:
        name, raw = value.split("=", 1)
        limit = float(raw)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("metric limit must use NAME=NONNEGATIVE_FLOAT") from exc
    name = name.strip()
    if not name or limit < 0:
        raise argparse.ArgumentTypeError("metric limit must use NAME=NONNEGATIVE_FLOAT")
    return name, limit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate deterministic replay or frozen-family cross-provider Agent studies."
    )
    parser.add_argument("left", type=Path, help="reference AgentMarketResearchResult JSON")
    parser.add_argument("right", type=Path, help="candidate AgentMarketResearchResult JSON")
    parser.add_argument("--mode", choices=("replay", "cross_provider"), required=True)
    parser.add_argument("--left-bars", type=Path)
    parser.add_argument("--right-bars", type=Path)
    parser.add_argument("--min-selection-agreement", type=float, default=0.0)
    parser.add_argument("--min-acceptance-agreement", type=float, default=0.0)
    parser.add_argument(
        "--metric-abs-limit",
        action="append",
        type=_metric_limit,
        default=[],
        metavar="NAME=VALUE",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()

    left = read_agent_market_result(args.left)
    right = read_agent_market_result(args.right)
    provider_diff = None
    if args.mode == "replay":
        if args.left_bars or args.right_bars:
            parser.error("--left-bars/--right-bars are only valid for cross_provider")
        if args.metric_abs_limit:
            parser.error("replay mode is exact; --metric-abs-limit is not applicable")
        policy = AgentMarketValidationPolicy.replay()
    else:
        if args.left_bars is None or args.right_bars is None:
            parser.error("cross_provider requires --left-bars and --right-bars")
        provider_diff = compare_provider_records(
            left.provider,
            read_normalized_csv(args.left_bars),
            right.provider,
            read_normalized_csv(args.right_bars),
        )
        limits = dict(args.metric_abs_limit)
        if len(limits) != len(args.metric_abs_limit):
            parser.error("duplicate --metric-abs-limit names are not allowed")
        policy = AgentMarketValidationPolicy.cross_provider(
            min_selection_agreement=args.min_selection_agreement,
            min_acceptance_agreement=args.min_acceptance_agreement,
            aggregate_abs_limits=limits,
        )

    report = validate_agent_market_results(
        left,
        right,
        policy=policy,
        provider_diff=provider_diff,
    )
    if args.output is not None:
        report.write_json(args.output)
    if args.store is not None:
        SQLiteAgentMarketValidationStore(args.store).register(report)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
