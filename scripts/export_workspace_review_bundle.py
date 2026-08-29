#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from finagent.application import (
    ApplicationCommandInvocation,
    ReviewBundleExportApplicationService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export a read-only Visualization V2 human-review bundle for one A4 "
            "portfolio-validation evidence identity."
        )
    )
    parser.add_argument("validation_id")
    parser.add_argument("--reports", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--git-sha", default="")
    args = parser.parse_args()

    parameters: dict[str, object] = {
        "validation_id": args.validation_id,
        "reports": tuple(args.reports or ["reports"]),
        "git_sha": args.git_sha,
    }
    if args.output is not None:
        parameters["output"] = args.output

    execution = ReviewBundleExportApplicationService().execute(
        ApplicationCommandInvocation(
            command_id="review.export_bundle",
            parameters=parameters,
            requested_by="cli",
        )
    )
    print(execution.outputs["output_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
