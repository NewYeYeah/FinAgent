#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data import read_normalized_csv, validate_records


def _resolve_bars_path(path: Path) -> Path:
    if path.is_dir():
        bars = path / "bars.csv"
        if not bars.is_file():
            raise FileNotFoundError(
                f"market-data directory does not contain bars.csv: {path}; "
                "run pull_market_data.py successfully before validation"
            )
        return bars
    if path.is_file():
        return path
    raise FileNotFoundError(
        f"market-data path does not exist: {path}; "
        "run pull_market_data.py successfully before validation"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a FinAgent normalized OHLCV CSV or materialized market-data directory."
    )
    parser.add_argument("bars", type=Path, help="bars.csv or directory containing bars.csv")
    parser.add_argument("--expected-symbol", action="append", default=[])
    parser.add_argument(
        "--allow-calendar-gaps",
        action="store_true",
        help="allow unequal per-asset calendars (not Level 2 tradability validation)",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    bars_path = _resolve_bars_path(args.bars)
    records = read_normalized_csv(bars_path)
    report = validate_records(
        records,
        expected_symbols=tuple(args.expected_symbol),
        require_common_calendar=not args.allow_calendar_gaps,
    )
    payload = report.to_dict()
    rendered = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
