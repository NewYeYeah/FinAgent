#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path

import uvicorn

from finagent.visualization.workspace_api import create_workspace_app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the read-only FinAgent Workspace V2 over immutable A2/A2.6/A4 reports, "
            "A4 ledgers and an optional canonical Agent audit SQLite database."
        )
    )
    parser.add_argument(
        "--reports",
        action="append",
        default=[],
        help=(
            "Report JSON file or directory. Repeat for multiple roots. "
            "Defaults to ./reports."
        ),
    )
    parser.add_argument(
        "--agent-audit",
        type=Path,
        help="Optional SQLiteAgentAuditStore database opened read-only.",
    )
    parser.add_argument(
        "--reserve-eligibility",
        type=Path,
        default=Path(".finagent/a5/reserve_eligibility.sqlite"),
        help="A5 ReserveEligibilitySeal SQLite opened read-only when present.",
    )
    parser.add_argument(
        "--reserve-consumption",
        type=Path,
        default=Path(".finagent/a5/reserve_consumption.sqlite"),
        help="A5 durable CONSUMED/audit SQLite opened read-only when present.",
    )
    parser.add_argument(
        "--reserve-terminal",
        type=Path,
        default=Path(".finagent/a5/reserve_terminal.sqlite"),
        help="A5 terminal/ledger SQLite opened read-only when present.",
    )
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=Path("workspace/dist"),
        help="Built Vite frontend directory.",
    )
    parser.add_argument(
        "--catalog-db",
        type=Path,
        default=Path(".finagent/visualization/evidence_catalog.sqlite"),
        help=(
            "Disposable V2 evidence-catalog SQLite path. It is rebuilt from "
            "authoritative report artifacts at service start."
        ),
    )
    parser.add_argument(
        "--no-catalog-db",
        action="store_true",
        help="Keep the derived V2 catalog in memory only.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--git-sha", default="")
    parser.add_argument("--print-config", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be in [1, 65535]")
    reports = tuple(args.reports or ["reports"])
    frontend = None if args.api_only else args.frontend_dir
    catalog_db = None if args.no_catalog_db else args.catalog_db
    reserve_eligibility = args.reserve_eligibility if args.reserve_eligibility.is_file() else None
    reserve_consumption = args.reserve_consumption if args.reserve_consumption.is_file() else None
    reserve_terminal = args.reserve_terminal if args.reserve_terminal.is_file() else None
    if frontend is not None and not frontend.is_dir():
        raise SystemExit(
            f"Workspace frontend is absent at {frontend}. Run `cd workspace && "
            "npm ci && npm run build`, or use --api-only."
        )

    config = {
        "reports": list(reports),
        "agent_audit": str(args.agent_audit) if args.agent_audit else None,
        "frontend_dir": str(frontend) if frontend else None,
        "host": args.host,
        "port": args.port,
        "reload": args.reload,
        "catalog_db": str(catalog_db) if catalog_db else None,
        "reserve_eligibility": str(reserve_eligibility) if reserve_eligibility else None,
        "reserve_consumption": str(reserve_consumption) if reserve_consumption else None,
        "reserve_terminal": str(reserve_terminal) if reserve_terminal else None,
        "workspace_version": "v2+a5-4",
        "read_only": True,
    }
    if args.print_config:
        import json

        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0

    url = f"http://{args.host}:{args.port}"
    if args.open_browser:
        webbrowser.open(url)

    if args.reload:
        os.environ["FINAGENT_WORKSPACE_REPORTS"] = os.pathsep.join(reports)
        os.environ["FINAGENT_WORKSPACE_AGENT_AUDIT"] = (
            str(args.agent_audit) if args.agent_audit else ""
        )
        os.environ["FINAGENT_WORKSPACE_FRONTEND"] = str(frontend) if frontend else ""
        os.environ["FINAGENT_WORKSPACE_GIT_SHA"] = args.git_sha
        os.environ["FINAGENT_WORKSPACE_CATALOG_DB"] = str(catalog_db) if catalog_db else ""
        os.environ["FINAGENT_WORKSPACE_RESERVE_ELIGIBILITY"] = str(reserve_eligibility) if reserve_eligibility else ""
        os.environ["FINAGENT_WORKSPACE_RESERVE_CONSUMPTION"] = str(reserve_consumption) if reserve_consumption else ""
        os.environ["FINAGENT_WORKSPACE_RESERVE_TERMINAL"] = str(reserve_terminal) if reserve_terminal else ""
        uvicorn.run(
            "finagent.visualization.workspace_api:create_app_from_environment",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
        )
        return 0

    app = create_workspace_app(
        report_paths=reports,
        agent_audit_path=args.agent_audit,
        frontend_dir=frontend,
        git_sha=args.git_sha,
        catalog_db_path=catalog_db,
        reserve_eligibility_path=reserve_eligibility,
        reserve_consumption_path=reserve_consumption,
        reserve_terminal_path=reserve_terminal,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
