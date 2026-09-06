"""Freeze first, then run a bounded exploratory economic screen without MT5/API."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from finagent.research.us_r3_economic_campaign import freeze_campaign, run_campaign
from finagent.research.us_r3_economics import EconomicPolicy


def progress(event: str, fields: Mapping[str, object]) -> None:
    print(json.dumps({"event": event, **fields}), file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    for name in ("source", "calendar", "base-plan", "base-evidence", "output"):
        freeze.add_argument("--" + name, type=Path, required=True)
    freeze.add_argument("--start", type=date.fromisoformat, required=True)
    freeze.add_argument("--end", type=date.fromisoformat, required=True)
    freeze.add_argument(
        "--execution-profile", choices=("strict_15m", "pending_exit_5m"), default="strict_15m"
    )
    freeze.add_argument(
        "--experiment",
        choices=("sleeve_baseline", "low_turnover_opening", "activity_reversal"),
        default="sleeve_baseline",
    )
    for name in ("history-source", "history-base-plan", "history-base-evidence"):
        freeze.add_argument("--" + name, type=Path)
    run = sub.add_parser("run")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            result = freeze_campaign(
                args.source,
                args.calendar,
                args.base_plan,
                args.base_evidence,
                args.output,
                start=args.start,
                end=args.end,
                policy=EconomicPolicy(execution_profile=args.execution_profile),
                experiment=args.experiment,
                history_source=args.history_source,
                history_base_plan=args.history_base_plan,
                history_base_evidence=args.history_base_evidence,
            )
        else:
            result = run_campaign(args.protocol, args.output_root, progress=progress)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except KeyboardInterrupt:
        progress("interrupted", {"completed_evidence_preserved": True})
        return 130
    except Exception as error:  # noqa: BLE001 -- CLI error boundary.
        progress("failed", {"error": str(error), "completed_evidence_preserved": True})
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
