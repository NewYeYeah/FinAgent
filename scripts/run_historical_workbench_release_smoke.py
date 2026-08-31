#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import uvicorn

from finagent.runtime.historical_workbench_release_smoke import (
    HistoricalWorkbenchReleaseSmoke,
    HistoricalWorkbenchReleaseSmokeConfig,
)
from finagent.visualization.workbench_api import _attach_frontend


def _command(name: str) -> str:
    candidates = (f"{name}.cmd", name) if os.name == "nt" else (name,)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError(f"{name} is required for the browser release smoke")


def _run_frontend_build(repository_root: Path) -> None:
    workspace = repository_root / "workspace"
    if not (workspace / "node_modules").is_dir():
        raise RuntimeError(
            "workspace/node_modules is absent; run `cd workspace && npm ci` before "
            "the real HW-1.0-RS browser smoke"
        )
    completed = subprocess.run(
        [_command("npm"), "run", "build"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Workspace production build failed\n"
            + completed.stdout[-4000:]
            + "\n"
            + completed.stderr[-4000:]
        )


def _wait_ready(url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:  # noqa: S310 - loopback only
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Workbench release-smoke server did not become ready: {last_error}")


def _run_browser(
    *,
    prepared,
    config: HistoricalWorkbenchReleaseSmokeConfig,
) -> tuple[bool, str]:
    if config.build_frontend:
        _run_frontend_build(config.repository_root)
    if not config.frontend_dir.is_dir():
        raise RuntimeError(
            f"Workspace production build is absent at {config.frontend_dir}; "
            "run `cd workspace && npm run build`"
        )

    # The production app is already fully composed by the smoke verifier. Attach the
    # just-built static bundle without rebuilding any evidence projections.
    _attach_frontend(prepared.app, config.frontend_dir)
    server = uvicorn.Server(
        uvicorn.Config(
            prepared.app,
            host=config.host,
            port=config.port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, name="hw1-release-smoke", daemon=True)
    thread.start()
    base_url = f"http://{config.host}:{config.port}"
    try:
        _wait_ready(f"{base_url}/api/v3/workbench/status")
        env = os.environ.copy()
        env.update(
            {
                "FINAGENT_HW_RS_BASE_URL": base_url,
                "FINAGENT_HW_RS_FREEZE_ID": prepared.expected["freeze_id"],
                "FINAGENT_HW_RS_OUTCOME": prepared.expected["research_outcome"],
                "FINAGENT_HW_RS_PORTFOLIO_VALIDATION_ID": prepared.expected[
                    "portfolio_validation_id"
                ],
                "FINAGENT_HW_RS_STRATEGY_SERIES_ID": prepared.expected[
                    "strategy_series_id"
                ],
                "FINAGENT_HW_RS_FACTOR_SERIES_ID": prepared.expected[
                    "factor_series_id"
                ],
                "FINAGENT_HW_RS_PROGRAM_RESULT_ID": prepared.expected[
                    "program_result_id"
                ],
            }
        )
        completed = subprocess.run(
            [
                _command("npx"),
                "playwright",
                "test",
                "e2e/historical-release-smoke-real.spec.ts",
                "--config=playwright.release-smoke.config.ts",
            ],
            cwd=config.repository_root / "workspace",
            env=env,
            check=False,
            text=True,
            capture_output=True,
        )
        detail = (completed.stdout + "\n" + completed.stderr)[-8000:].strip()
        return completed.returncode == 0, detail
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Historical Workbench 1.0 post-freeze release smoke against the "
            "exact A-C5/A-C3 local evidence. This is read-only and does not rerun research."
        )
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path(
            "configs/acceptance/historical_workbench_release_smoke.example.toml"
        ),
    )
    parser.add_argument("--smoke-git-sha")
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Validate release/evidence/Workbench projections without Playwright.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Use an existing workspace/dist instead of running npm run build.",
    )
    args = parser.parse_args()

    config = HistoricalWorkbenchReleaseSmokeConfig.read_toml(args.config)
    if args.smoke_git_sha:
        config = replace(config, smoke_git_sha=args.smoke_git_sha)
    if args.backend_only:
        config = replace(config, run_browser=False)
    if args.no_build:
        config = replace(config, build_frontend=False)

    smoke = HistoricalWorkbenchReleaseSmoke(config)
    prepared = smoke.prepare()
    browser_status = "not_run"
    browser_detail = "browser smoke disabled"
    if config.run_browser:
        passed, browser_detail = _run_browser(prepared=prepared, config=config)
        browser_status = "passed" if passed else "failed"

    result = smoke.finalize(
        prepared,
        browser_status=browser_status,
        browser_detail=browser_detail,
    )
    print(
        json.dumps(
            {
                "schema_version": "finagent.historical-workbench-release-smoke-cli.v1",
                "smoke_id": result.payload.get("smoke_id"),
                "freeze_id": result.payload.get("freeze_id"),
                "research_outcome": result.payload.get("research_outcome"),
                "contract_valid": result.contract_valid,
                "browser_status": browser_status,
                "accepted": result.accepted,
                "json_report": str(result.json_path),
                "markdown_report": str(result.markdown_path),
                "production_reserve_consumed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    success = result.accepted if config.mode == "real_frozen_release" else result.contract_valid
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
