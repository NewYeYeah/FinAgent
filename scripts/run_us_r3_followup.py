"""Audit R3, plan evidence, and freeze/run a separately budgeted workflow pilot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from finagent.research.us_r3_followup_review import evidence_plan, review_completion
from finagent.research.us_r3_workflow_pilot import freeze_workflow, run_workflow


def progress(event: str, fields: dict[str, object]) -> None:
    print(json.dumps({"event": event, **fields}), file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "evidence-plan", "freeze-workflow"):
        p = sub.add_parser(name)
        p.add_argument("--previous-root", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if name == "freeze-workflow":
            p.add_argument("--config", type=Path, default=Path("configs/llm.toml"))
    p = sub.add_parser("run-workflow")
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "review":
            result = review_completion(args.previous_root, args.output)
        elif args.command == "evidence-plan":
            result = evidence_plan(args.previous_root, args.output)
        elif args.command == "freeze-workflow":
            result = freeze_workflow(args.previous_root, args.config, args.output)
        else:
            result = run_workflow(args.protocol, args.output_root, progress=progress)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as error:  # noqa: BLE001 -- do not expose model/source exception payloads.
        progress("failed", {"type": type(error).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
