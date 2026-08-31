from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
