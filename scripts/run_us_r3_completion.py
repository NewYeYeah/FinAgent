"""Freeze and complete the bounded R3 pilot and exploratory assessment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from finagent.research.us_r3_completion import freeze_completion, run_completion
from finagent.research.us_r3_confirmation import confirm_returns


def progress(event: str, fields: dict[str, object]) -> None:
    print(json.dumps({"event": event, **fields}), file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    freeze = subs.add_parser("freeze")
    freeze.add_argument("--economic-protocol", type=Path, required=True)
    freeze.add_argument("--config", type=Path, default=Path("configs/llm.toml"))
    freeze.add_argument("--output", type=Path, required=True)
    run = subs.add_parser("run")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    confirm = subs.add_parser("confirm")
    for name in ("model", "protocol", "receipt", "returns", "output"):
        confirm.add_argument("--" + name, type=Path, required=True)
    confirm.add_argument("--trusted-receipt-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "confirm":
            result = confirm_returns(
                model_path=args.model,
                protocol_path=args.protocol,
                receipt_path=args.receipt,
                trusted_receipt_sha256=args.trusted_receipt_sha256,
                returns_path=args.returns,
                output=args.output,
            )
        else:
            result = (
                freeze_completion(args.economic_protocol, args.config, args.output)
                if args.command == "freeze"
                else run_completion(args.protocol, args.output_root, progress=progress)
            )
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except KeyboardInterrupt:
        progress("interrupted", {"resume_evidence_preserved": True})
        return 130
    except Exception as error:  # noqa: BLE001 -- sanitized CLI boundary.
        # Provider/source exceptions must not expose credentials or data to logs.
        progress("failed", {"type": type(error).__name__, "resume_evidence_preserved": True})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
