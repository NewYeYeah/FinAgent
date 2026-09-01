from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from finagent.data.minute_store import (
    DuckDBParquetMinuteStore,
    copy_plan_to_parquet,
    count_plan_rows,
    fetch_plan_rows,
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
        description="Run one bounded US-D1 query against the admitted local OHLCV-1m corpus."
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--asset", action="append", required=True)
    parser.add_argument("--start", type=_aware_datetime, required=True)
    parser.add_argument("--end", type=_aware_datetime, required=True)
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=0,
        help=(
            "Optional local row preview count in 0..100. Defaults to 0 so portable smoke "
            "summaries contain no source OHLCV rows."
        ),
    )
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    assets = tuple(sorted(dict.fromkeys(item.strip() for item in args.asset if item.strip())))
    if not assets:
        raise SystemExit("at least one non-empty --asset is required")
    if not 0 <= args.preview_rows <= 100:
        raise SystemExit("--preview-rows must be in 0..100")
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
    count = count_plan_rows(plan)
    preview = fetch_plan_rows(plan, limit=args.preview_rows) if args.preview_rows else ()
    materialization = None
    if args.output is not None:
        materialization = copy_plan_to_parquet(plan, args.output, overwrite=True)

    print(
        json.dumps(
            {
                "manifest": manifest.to_dict(),
                "view": store.view(query).to_dict(),
                "plan": plan.to_dict(),
                "actual_rows": count,
                "preview": [
                    {
                        key: value.isoformat() if isinstance(value, datetime) else value
                        for key, value in row.items()
                    }
                    for row in preview
                ],
                "materialization": materialization.to_dict() if materialization else None,
            },
            sort_keys=True,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
