from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from finagent.data.minute_store import manifest_from_huggingface_snapshot, select_partitions
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.data.us_minute.quarantine import quarantined_clean_month_select_sql
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

SOURCE_ID = "hf-mito0o852-ohlcv-1m"
SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"


def _aware_datetime(value: str) -> datetime:
    rendered = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(rendered)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamps must be timezone-aware ISO-8601 values")
    return parsed.astimezone(UTC)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export a bounded, admitted U.S. minute sample for local development only. "
            "The default /data destination is gitignored and must not be redistributed."
        )
    )
    parser.add_argument("root", type=Path, help="Hugging Face OHLCV-1m cache/snapshot root")
    parser.add_argument("--asset", action="append", required=True, help="Ticker; repeatable")
    parser.add_argument("--start", type=_aware_datetime, required=True)
    parser.add_argument("--end", type=_aware_datetime, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/dev_samples/us_minute_seed"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    assets = tuple(sorted(dict.fromkeys(item.strip() for item in args.asset if item.strip())))
    if not assets:
        raise SystemExit("at least one non-empty --asset is required")
    if len(assets) > 32:
        raise SystemExit("development sample export is capped at 32 assets")
    if args.end <= args.start:
        raise SystemExit("--end must be later than --start")
    if args.end - args.start > timedelta(days=31):
        raise SystemExit("development sample export is capped at 31 days")

    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True)

    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=CLEANING_ID,
        source_id=SOURCE_ID,
    )
    routing_query = MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=args.start,
        end=args.end,
        interval=BarInterval.MINUTE_1,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.ALL_OBSERVED,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )
    partitions = select_partitions(manifest, routing_query)

    connection = duckdb.connect(database=":memory:")
    exported: list[dict[str, object]] = []
    try:
        for partition in partitions:
            select_sql = quarantined_clean_month_select_sql(
                partition.path,
                tickers=assets,
                start=args.start,
                end=args.end,
            )
            target = data_dir / partition.path.name
            connection.execute(
                f"COPY (SELECT timestamp, open, high, low, close, volume, ticker "
                f"FROM ({select_sql}) AS admitted ORDER BY timestamp, ticker) "
                f"TO {_sql_string(target.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            row = connection.execute(
                f"SELECT COUNT(*) FROM read_parquet({_sql_string(target.as_posix())})"
            ).fetchone()
            row_count = int(row[0]) if row is not None else 0
            exported.append(
                {
                    "month": partition.month,
                    "filename": target.name,
                    "row_count": row_count,
                    "size_bytes": target.stat().st_size,
                }
            )
    finally:
        connection.close()

    payload = {
        "schema_version": "finagent.local-us-minute-dev-sample.v1",
        "scope": "local_non_redistributed_development_only",
        "source_id": SOURCE_ID,
        "source_revision": SOURCE_REVISION,
        "source_inventory_id": INVENTORY_ID,
        "cleaning_identity": CLEANING_ID,
        "assets": list(assets),
        "start_inclusive": args.start.isoformat(),
        "end_exclusive": args.end.isoformat(),
        "partitions": exported,
        "limitations": [
            "do_not_commit_or_redistribute",
            "sample_is_not_a_research_universe",
            "session_rows_are_all_observed_and_unclassified",
        ],
    }
    manifest_path = output_dir / "sample_manifest.json"
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**payload, "output_dir": str(output_dir)}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
