#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from finagent.visualization.workspace_api import WorkspaceEvidenceCatalog
from finagent.visualization.workspace_v2 import WorkspaceV2Projection


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

    reports = tuple(args.reports or ["reports"])
    catalog = WorkspaceEvidenceCatalog(reports, git_sha=args.git_sha)
    projection = WorkspaceV2Projection(
        catalog.bundles(), report_paths=reports, git_sha=args.git_sha
    )
    payload = projection.review_bundle(args.validation_id)
    output = args.output or Path(f"finagent-review-{args.validation_id}.zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
