#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data import read_normalized_csv, validate_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a FinAgent normalized OHLCV CSV.")
    parser.add_argument("bars", type=Path)
    parser.add_argument("--expected-symbol", action="append", default=[])
    parser.add_argument(
        "--allow-calendar-gaps",
        action="store_true",
        help="allow unequal per-asset calendars (not Level 2 tradability validation)",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    records = read_normalized_csv(args.bars)
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
