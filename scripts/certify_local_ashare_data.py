#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

from finagent.application import (
    ApplicationCommandInvocation,
    LocalAshareCertificationApplicationService,
)
from finagent.data import AshareBarFrequency


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    values = payload.get("local_ashare")
    if not isinstance(values, dict):
        raise TypeError("configuration must contain [local_ashare]")
    return values


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
    parser.add_argument(
        "--frequency",
        choices=tuple(item.value for item in AshareBarFrequency),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    parameters: dict[str, object] = {}
    if args.root is not None:
        parameters["root"] = args.root
    if args.sample_symbol is not None:
        parameters["sample_symbol"] = args.sample_symbol
    if args.sample_date is not None:
        parameters["sample_date"] = args.sample_date
    if args.frequency is not None:
        parameters["frequency"] = args.frequency
    if args.output is not None:
        parameters["output"] = args.output

    execution = LocalAshareCertificationApplicationService().execute(
        ApplicationCommandInvocation(
            command_id="data.certify_local_ashare",
            config_values=_load(args.config),
            parameters=parameters,
            requested_by="cli",
        )
    )
    report = execution.outputs.get("report", {})
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if execution.status == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
