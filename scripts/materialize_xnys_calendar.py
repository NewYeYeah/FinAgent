from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from finagent.data.calendar_materialization import (
    RECOMMENDED_EXCHANGE_CALENDARS_VERSION,
    ExchangeCalendarMaterializationSpec,
    materialize_xnys_exchange_calendars,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize exact-version XNYS trading-calendar evidence for the admitted "
            "U.S. minute research interval."
        )
    )
    parser.add_argument("--start", type=_date, default=date(1992, 1, 1))
    parser.add_argument("--end", type=_date, default=date(2026, 3, 31))
    parser.add_argument(
        "--expected-version",
        default=RECOMMENDED_EXCHANGE_CALENDARS_VERSION,
        help="Exact installed exchange_calendars version required for evidence identity",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    spec = ExchangeCalendarMaterializationSpec(
        requested_start=args.start,
        requested_end=args.end,
        expected_package_version=args.expected_version,
    )
    report = materialize_xnys_exchange_calendars(spec)
    report.write_json(args.output)
    print(json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
