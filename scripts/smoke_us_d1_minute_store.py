from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from finagent.data.minute_store import (
    DEFAULT_MINUTE_STORE_SMOKE_POLICY,
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    MinuteStoreSmokeReport,
    copy_plan_to_parquet,
    count_plan_rows,
    fetch_plan_rows,
    inspect_execution_settings,
    manifest_from_huggingface_snapshot,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamps must be timezone-aware ISO-8601 values")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a bounded, replayable US-D1 query against the admitted local OHLCV-1m corpus "
            "under explicit DuckDB memory/thread/temp-spill limits."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--asset", action="append", required=True)
    parser.add_argument("--start", type=_aware_datetime, required=True)
    parser.add_argument("--end", type=_aware_datetime, required=True)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument(
        "--allow-temp-spill",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow bounded DuckDB disk spill; use --no-allow-temp-spill to force 0B.",
    )
    parser.add_argument(
        "--max-temp-directory-size",
        default="4GB",
        help="Maximum DuckDB spill size when temp spill is enabled.",
    )
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_d1"),
        help="Local spill directory; /data is gitignored by repository policy",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/dev_samples/us_d1_smoke/bounded.parquet"),
        help="Local real-data materialization; do not commit or redistribute",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=Path("reports/us_d1/us_d1_smoke_report.json"),
        help="Row-free smoke evidence JSON that is safe to paste for project review",
    )
    parser.add_argument(
        "--verify-replay",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Materialize the same plan twice and require identical content SHA-256",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=0,
        help=(
            "Optional local row preview count in 0..100. Defaults to 0 so portable smoke "
            "summaries contain no source OHLCV rows."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    assets = tuple(sorted(dict.fromkeys(item.strip() for item in args.asset if item.strip())))
    if not assets:
        raise SystemExit("at least one non-empty --asset is required")
    if not 0 <= args.preview_rows <= 100:
        raise SystemExit("--preview-rows must be in 0..100")

    execution_policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=args.allow_temp_spill,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    temp_directory = args.temp_directory if execution_policy.allow_temp_spill else None
    execution_settings = inspect_execution_settings(
        policy=execution_policy,
        temp_directory=temp_directory,
    )
    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=CLEANING_ID,
    )
    store = DuckDBParquetMinuteStore(manifest)
    query = MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=args.start,
        end=args.end,
        interval=BarInterval.MINUTE_1,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.ALL_OBSERVED,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    plan = store.plan(query)

    primary = copy_plan_to_parquet(
        plan,
        args.output,
        overwrite=True,
        policy=execution_policy,
        temp_directory=temp_directory,
    )
    actual_rows = primary.row_count

    replay = None
    replay_match = None
    if args.verify_replay:
        replay_output = args.output.with_name(
            f"{args.output.stem}.replay{args.output.suffix or '.parquet'}"
        )
        replay = copy_plan_to_parquet(
            plan,
            replay_output,
            overwrite=True,
            policy=execution_policy,
            temp_directory=temp_directory,
        )
        replay_match = (
            replay.row_count == primary.row_count
            and replay.content_sha256 == primary.content_sha256
            and replay.materialization_id == primary.materialization_id
        )

    preview = (
        fetch_plan_rows(
            plan,
            limit=args.preview_rows,
            policy=execution_policy,
            temp_directory=temp_directory,
        )
        if args.preview_rows
        else ()
    )
    if not args.verify_replay:
        actual_rows = count_plan_rows(
            plan,
            policy=execution_policy,
            temp_directory=temp_directory,
        )

    report = MinuteStoreSmokeReport(
        plan=plan,
        smoke_policy=DEFAULT_MINUTE_STORE_SMOKE_POLICY,
        execution_policy=execution_policy,
        execution_settings=execution_settings,
        actual_rows=actual_rows,
        primary_materialization=primary,
        replay_materialization=replay,
        replay_match=replay_match,
        ran_at=datetime.now(UTC),
    )
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    console = report.to_dict()
    console["report_output"] = str(args.report_output)
    console["preview"] = [
        {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in row.items()
        }
        for row in preview
    ]
    print(json.dumps(console, sort_keys=True, indent=2, default=str))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
