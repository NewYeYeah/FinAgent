#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from datetime import date
from pathlib import Path

from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetInspector,
    LocalAshareDatasetLayout,
)


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    values = payload.get("local_ashare")
    if not isinstance(values, dict):
        raise TypeError("configuration must contain [local_ashare]")
    return values


def _date(value: object | None) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect a local A-share Parquet dataset, certify the daily/basic schema, "
            "and optionally reconcile one intraday sample against daily OHLCV."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--root", type=Path, help="override local_ashare.root")
    parser.add_argument("--sample-symbol", help="override local_ashare.sample_symbol")
    parser.add_argument("--sample-date", help="YYYY-MM-DD override")
    parser.add_argument("--frequency", choices=tuple(item.value for item in AshareBarFrequency))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    values = _load(args.config)
    root = args.root or Path(str(values["root"]))
    layout = LocalAshareDatasetLayout(
        root=root,
        basic_filename=str(values.get("basic_filename", "stock_basic_data.parquet")),
        daily_filename=str(values.get("daily_filename", "stock_daily.parquet")),
    )
    frequency = AshareBarFrequency(
        str(args.frequency or values.get("sample_frequency", "1min"))
    )
    symbol = str(args.sample_symbol or values.get("sample_symbol", "")).strip() or None
    selected_date = _date(args.sample_date or values.get("sample_date"))
    report = LocalAshareDatasetInspector(layout).inspect(
        intraday_symbol=symbol,
        intraday_date=selected_date,
        frequency=frequency,
    )
    output = args.output or Path(
        str(values.get("report_path", "reports/local_ashare_certification.json"))
    )
    report.write_json(output)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
