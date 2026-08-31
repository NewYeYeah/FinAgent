from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import run_historical_workbench_release_smoke as cli

ROOT = Path(__file__).resolve().parents[1]


def test_hw1_cli_captures_utf8_output_independent_of_host_locale() -> None:
    completed = cli._run_captured(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.buffer.write('✓ → browser smoke'.encode('utf-8')); "
                "sys.stderr.buffer.write('测试'.encode('utf-8'))"
            ),
        ],
        cwd=ROOT,
    )

    assert completed.returncode == 0
    assert completed.stdout == "✓ → browser smoke"
    assert completed.stderr == "测试"
    assert "✓ → browser smoke" in cli._captured_output(completed)
    assert "测试" in cli._captured_output(completed)


def test_hw1_cli_captured_output_tolerates_missing_stream_values() -> None:
    completed = subprocess.CompletedProcess(
        args=["synthetic"],
        returncode=0,
        stdout=None,
        stderr=None,
    )

    assert cli._captured_output(completed) == ""


def test_hw1_cli_persists_and_surfaces_browser_failure_detail(tmp_path: Path) -> None:
    config = SimpleNamespace(output_json=tmp_path / "historical_workbench_release_smoke.json")
    detail = "locator timeout\ntrace: test-results/hw1/trace.zip\n中文诊断"

    log_path = cli._write_browser_log(config, detail)  # type: ignore[arg-type]

    assert log_path == tmp_path / "historical_workbench_release_smoke.playwright.log"
    assert log_path.read_text(encoding="utf-8") == detail + "\n"
    assert cli._browser_failure_tail(detail, 20).endswith("中文诊断")
    assert cli._browser_failure_tail("") == "Playwright failed without captured output"


def test_hw1_cli_filters_only_windows_10054_reset(monkeypatch) -> None:
    reset = ConnectionResetError(10054, "forced close")
    reset.winerror = 10054  # type: ignore[attr-defined]
    record = logging.LogRecord(
        "asyncio",
        logging.ERROR,
        __file__,
        1,
        "reset",
        (),
        (ConnectionResetError, reset, None),
    )
    other = logging.LogRecord(
        "asyncio",
        logging.ERROR,
        __file__,
        1,
        "other",
        (),
        None,
    )
    guard = cli._BenignWindowsResetFilter()

    monkeypatch.setattr(cli.os, "name", "nt")
    assert guard.filter(record) is False
    assert guard.filter(other) is True
