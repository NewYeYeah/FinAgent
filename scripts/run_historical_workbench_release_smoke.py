#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

import uvicorn

from finagent.runtime.historical_workbench_release_smoke import (
    BrowserSmokeStatus,
    HistoricalWorkbenchReleaseSmokeConfig,
    HistoricalWorkbenchReleaseSmokePrepared,
)
from finagent.runtime.historical_workbench_release_smoke_acceptance import (
    HistoricalWorkbenchReleaseSmoke,
)
from finagent.visualization.workbench_api import _attach_frontend


def _command(name: str) -> str:
    candidates = (f"{name}.cmd", name) if os.name == "nt" else (name,)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError(f"{name} is required for the browser release smoke")


def _run_captured(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Capture npm/npx output without depending on the host Windows code page.

    Node/Playwright emit UTF-8 output even when Python's preferred Windows text
    encoding is GBK/cp936. ``subprocess.run(text=True)`` otherwise decodes with the
    locale encoding and its reader thread can fail before ``stdout``/``stderr`` are
    populated. Replacement decoding is intentional here: the captured text is only
    diagnostic evidence, while the subprocess return code remains authoritative.
    """

    return subprocess.run(
        list(command),
        cwd=cwd,
        env=None if env is None else dict(env),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _captured_output(completed: subprocess.CompletedProcess[str]) -> str:
    # Be defensive if a platform/runtime still yields None despite text capture.
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return (stdout + "\n" + stderr).strip()


def _browser_failure_tail(detail: str, limit: int = 8000) -> str:
    return detail[-limit:].strip() if detail else "Playwright failed without captured output"


def _write_browser_log(
    config: HistoricalWorkbenchReleaseSmokeConfig,
    detail: str,
) -> Path:
    path = config.output_json.with_suffix(".playwright.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((detail.rstrip() + "\n") if detail else "", encoding="utf-8")
    return path


class _BenignWindowsResetFilter(logging.Filter):
    """Hide only the Proactor WinError 10054 emitted while closing browser sockets."""

    def filter(self, record: logging.LogRecord) -> bool:
        if os.name != "nt" or record.exc_info is None:
            return True
        exc = record.exc_info[1]
        return not (
            isinstance(exc, ConnectionResetError)
            and getattr(exc, "winerror", None) == 10054
        )


def _run_frontend_build(repository_root: Path) -> None:
    workspace = repository_root / "workspace"
    if not (workspace / "node_modules").is_dir():
        raise RuntimeError(
            "workspace/node_modules is absent; run `cd workspace && npm ci` before "
            "the real HW-1.0-RS browser smoke"
        )
    completed = _run_captured(
        [_command("npm"), "run", "build"],
        cwd=workspace,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Workspace production build failed\n" + _captured_output(completed)[-8000:]
        )


def _ensure_chromium(repository_root: Path) -> None:
    completed = _run_captured(
        [_command("npx"), "playwright", "install", "chromium"],
        cwd=repository_root / "workspace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Playwright Chromium installation failed\n"
            + _captured_output(completed)[-8000:]
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
    prepared: HistoricalWorkbenchReleaseSmokePrepared,
    config: HistoricalWorkbenchReleaseSmokeConfig,
) -> tuple[bool, str]:
    if config.build_frontend:
        _run_frontend_build(config.repository_root)
    if not config.frontend_dir.is_dir():
        raise RuntimeError(
            f"Workspace production build is absent at {config.frontend_dir}; "
            "run `cd workspace && npm run build`"
        )
    _ensure_chromium(config.repository_root)

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
    asyncio_logger = logging.getLogger("asyncio")
    reset_filter = _BenignWindowsResetFilter()
    asyncio_logger.addFilter(reset_filter)
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
        completed = _run_captured(
            [
                _command("npx"),
                "playwright",
                "test",
                "e2e/historical-release-smoke-real.spec.ts",
                "--config=playwright.release-smoke.config.ts",
            ],
            cwd=config.repository_root / "workspace",
            env=env,
        )
        detail = _captured_output(completed)
        return completed.returncode == 0, detail
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        asyncio_logger.removeFilter(reset_filter)


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
        help=(
            "Validate release/evidence/Workbench projections without Playwright. "
            "In real mode this is diagnostic only and cannot set accepted=true."
        ),
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
    browser_status: BrowserSmokeStatus = "not_run"
    browser_detail = "browser smoke disabled"
    browser_log: Path | None = None
    if config.run_browser:
        passed, browser_detail = _run_browser(prepared=prepared, config=config)
        browser_status = "passed" if passed else "failed"
        browser_log = _write_browser_log(config, browser_detail)

    result = smoke.finalize(
        prepared,
        browser_status=browser_status,
        browser_detail=browser_detail,
    )
    output: dict[str, object] = {
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
    }
    if browser_log is not None:
        output["browser_log"] = str(browser_log)
    if browser_status == "failed":
        output["browser_failure_tail"] = _browser_failure_tail(browser_detail, 4000)
    print(json.dumps(output, indent=2, sort_keys=True))
    if browser_status == "failed":
        print("\n--- HW-1.0-RS Playwright failure detail ---", file=sys.stderr)
        print(_browser_failure_tail(browser_detail), file=sys.stderr)
        if browser_log is not None:
            print(f"\nFull Playwright log: {browser_log}", file=sys.stderr)

    success = result.accepted if config.mode == "real_frozen_release" else result.contract_valid
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
