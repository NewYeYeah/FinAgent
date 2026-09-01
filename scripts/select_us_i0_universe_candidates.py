from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from finagent.data.minute_store import DuckDBExecutionPolicy
from finagent.data.minute_transform import load_trading_calendar_evidence_json
from finagent.data.us_universe_candidates import (
    USUniverseCandidateSelectionPolicy,
    select_us_universe_candidates,
)

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"
CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"
DEFAULT_SEEDS = ("MSFT", "NVDA", "AMD", "INTC")


def _aware_datetime(value: str) -> datetime:
    rendered = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(rendered)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware ISO-8601")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Select a deterministic US-I0 engineering-universe candidate set from "
            "recent admitted OHLCV activity intersected with the exact MT5 symbol inventory. "
            "The output is a review/spread-probe candidate set, not an accepted universe."
        )
    )
    parser.add_argument("root", type=Path, help="Local OHLCV-1m Hugging Face cache root")
    parser.add_argument(
        "--mt5-probe",
        type=Path,
        required=True,
        help="Accepted read-only MT5 capability probe JSON",
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("reports/us_calendar/xnys_1992_2026.json"),
    )
    parser.add_argument(
        "--start",
        type=_aware_datetime,
        default=datetime(2026, 1, 1, tzinfo=UTC),
    )
    parser.add_argument(
        "--end",
        type=_aware_datetime,
        default=datetime(2026, 4, 1, tzinfo=UTC),
    )
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--minimum-selected", type=int, default=20)
    parser.add_argument("--minimum-active-sessions", type=int, default=20)
    parser.add_argument("--minimum-active-session-ratio", type=float, default=0.80)
    parser.add_argument("--minimum-median-coverage-ratio", type=float, default=0.80)
    parser.add_argument("--minimum-median-close", type=float, default=1.0)
    parser.add_argument("--minimum-median-daily-notional-proxy", type=float, default=0.0)
    parser.add_argument(
        "--require-visible",
        action="store_true",
        help=(
            "Require current MT5 Market Watch visibility. Omit this for candidate discovery; "
            "invisible selections remain explicit manual-visibility actions."
        ),
    )
    parser.add_argument(
        "--seed-symbol",
        action="append",
        default=[],
        help="Accepted seed symbol that must remain eligible; repeatable",
    )
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_i0_candidates"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_instruments/us_i0_universe_candidates.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    raw = json.loads(args.mt5_probe.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise SystemExit("MT5 probe JSON root must be an object")
    probe = cast(Mapping[str, object], raw)
    calendar = load_trading_calendar_evidence_json(
        args.calendar,
        expected_calendar_id=CALENDAR_ID,
    )
    seeds = tuple(args.seed_symbol) if args.seed_symbol else DEFAULT_SEEDS
    policy = USUniverseCandidateSelectionPolicy(
        start=args.start,
        end=args.end,
        calendar_id=CALENDAR_ID,
        top_n=args.top_n,
        minimum_selected_count=args.minimum_selected,
        minimum_active_sessions=args.minimum_active_sessions,
        minimum_active_session_ratio=args.minimum_active_session_ratio,
        minimum_median_regular_coverage_ratio=args.minimum_median_coverage_ratio,
        minimum_median_session_close=args.minimum_median_close,
        minimum_median_daily_notional_proxy=args.minimum_median_daily_notional_proxy,
        require_visible=args.require_visible,
        seed_symbols=seeds,
    )
    execution_policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    report = select_us_universe_candidates(
        args.root,
        mt5_probe=probe,
        calendar=calendar,
        policy=policy,
        expected_revision=SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=CLEANING_ID,
        execution_policy=execution_policy,
        temp_directory=args.temp_directory,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = {
        "selection_id": report.selection_id,
        "ready_for_spread_probe": report.ready_for_spread_probe,
        "blockers": list(report.blockers),
        "limitations": list(report.limitations),
        "research_symbol_count": report.research_symbol_count,
        "broker_tradable_symbol_count": report.broker_tradable_symbol_count,
        "exact_intersection_count": report.exact_intersection_count,
        "eligible_candidate_count": report.eligible_candidate_count,
        "selected_candidate_count": len(report.candidates),
        "spread_probe_symbols": [item.broker_symbol for item in report.candidates],
        "manual_visibility_required_symbols": list(
            report.manual_visibility_required_symbols
        ),
        "output": str(args.output),
    }
    print(json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if report.ready_for_spread_probe else 2


if __name__ == "__main__":
    raise SystemExit(main())
