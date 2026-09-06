"""Audit a frozen R3 campaign against the admitted local 1min OHLCV source."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from finagent.data.minute_store import manifest_from_huggingface_snapshot
from finagent.research.us_r3_minute_liquidity import audit_campaign


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--opening-capital", type=float, default=100_000.0)
    parser.add_argument("--participation-limit", type=float, default=0.01)
    args = parser.parse_args()
    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision="776328445b7ac6e7815ef3a483e9c8ded1eb6d56",
        expected_inventory_id="us-minute-inventory-c2cbf682b456f97eb613ed65",
        cleaning_identity="us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244",
        source_id="hf-mito0o852-ohlcv-1m",
    )
    report = audit_campaign(
        args.campaign,
        manifest,
        args.output,
        start=args.start,
        end=args.end,
        opening_capital=args.opening_capital,
        participation_limit=args.participation_limit,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "daily"}, sort_keys=True))


if __name__ == "__main__":
    main()
