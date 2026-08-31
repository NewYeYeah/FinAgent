#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.runtime.initial_requirement_compliance import (
    run_initial_requirement_compliance_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the A-C4 read-only initial requirement compliance audit. "
            "This command has no reserve, PAPER, broker or live-capital authority."
        )
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path(
            "configs/acceptance/ashare_initial_requirement_compliance_ac4.toml"
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--git-sha")
    parser.add_argument(
        "--json-report",
        type=Path,
        default=Path("reports/ashare_initial_requirement_compliance_ac4.json"),
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=Path("reports/ashare_initial_requirement_compliance_ac4.md"),
    )
    args = parser.parse_args()

    audit = run_initial_requirement_compliance_audit(
        args.manifest,
        repository_root=args.repository_root,
        git_sha=args.git_sha,
    )
    audit.write_json(args.json_report)
    audit.write_markdown(args.markdown_report)
    print(
        json.dumps(
            {
                "schema_version": "finagent.initial-requirement-compliance-cli.v1",
                "audit_id": audit.audit_id,
                "audit_complete": audit.audit_complete,
                "historical_freeze_ready": audit.historical_freeze_ready,
                "summary": dict(audit.status_counts),
                "json_report": str(args.json_report),
                "markdown_report": str(args.markdown_report),
                "production_reserve_authority": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if audit.historical_freeze_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
