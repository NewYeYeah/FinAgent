#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

import uvicorn

from finagent.visualization.historical_workbench_control_api import (
    create_historical_control_app,
)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the explicit local-only FinAgent Historical Workbench Control Plane. "
            "A-C1 enables only reviewed application_service_ready L0/L1 historical "
            "commands; reserve, promotion, PAPER, broker and live-capital authority "
            "remain forbidden."
        )
    )
    parser.add_argument("--configs", action="append", default=[])
    parser.add_argument("--reports", action="append", default=[])
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(".finagent/workbench/commands.sqlite"),
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=Path(".finagent/workbench/exports"),
    )
    parser.add_argument("--actor", default=getpass.getuser())
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--print-config", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.host not in _LOOPBACK_HOSTS:
        raise SystemExit(
            "A-C1 Control Plane is local-only and refuses non-loopback --host values"
        )
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be in [1, 65535]")
    if not 1 <= args.workers <= 4:
        raise SystemExit("--workers must be in [1, 4]")
    configs = tuple(args.configs or ["configs"])
    reports = tuple(args.reports or ["reports"])
    config = {
        "configs": list(configs),
        "reports": list(reports),
        "store": str(args.store),
        "export_dir": str(args.export_dir),
        "actor": args.actor,
        "workers": args.workers,
        "host": args.host,
        "port": args.port,
        "local_only": True,
        "control_plane_enabled": True,
        "historical_operations": True,
        "authority": (
            "reviewed application_service_ready L0/L1 only; historical commands only"
        ),
    }
    if args.print_config:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0

    if args.reload:
        os.environ["FINAGENT_CONTROL_CONFIGS"] = os.pathsep.join(configs)
        os.environ["FINAGENT_CONTROL_REPORTS"] = os.pathsep.join(reports)
        os.environ["FINAGENT_CONTROL_STORE"] = str(args.store)
        os.environ["FINAGENT_CONTROL_EXPORT_DIR"] = str(args.export_dir)
        os.environ["FINAGENT_CONTROL_ACTOR"] = args.actor
        os.environ["FINAGENT_CONTROL_WORKERS"] = str(args.workers)
        uvicorn.run(
            "finagent.visualization.historical_workbench_control_api:create_app_from_environment",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
        )
        return 0

    app = create_historical_control_app(
        config_paths=configs,
        report_paths=reports,
        store_path=args.store,
        export_dir=args.export_dir,
        requested_by=args.actor,
        max_workers=args.workers,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
