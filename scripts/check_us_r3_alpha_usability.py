"""Verify feature correctness/usability; does not test or approve profitability."""

from __future__ import annotations

import argparse
import faulthandler
import json
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from finagent.research.us_r3_usability import run_usability


def _progress(event: str, fields: Mapping[str, object]) -> None:
    print(
        json.dumps({"time": datetime.now(UTC).isoformat(), "event": event, **fields}),
        file=sys.stderr,
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run label-blind R3 feature engineering checks, without MT5."
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        required=True,
        help="Annual R2 robustness-base Parquet; repeat for multiple years.",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--minimum-cross-section", type=int, default=3)
    args = parser.parse_args()
    faulthandler.enable()
    try:
        result = run_usability(
            tuple(args.source),
            args.output_root,
            minimum_cross_section=args.minimum_cross_section,
            progress=_progress,
        )
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if result["passed"] else 1
    except KeyboardInterrupt:
        _progress("interrupted", {"completed_evidence_preserved": True})
        return 130
    except Exception as error:  # noqa: BLE001 -- CLI boundary logs full traceback and fails closed.
        _progress(
            "failed",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_evidence_preserved": True,
            },
        )
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
