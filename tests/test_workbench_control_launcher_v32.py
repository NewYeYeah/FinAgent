from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest


def _run_launcher(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_workbench_control.py"
    monkeypatch.setattr(sys, "argv", [str(script), *args])
    runpy.run_path(str(script), run_name="__main__")


def test_control_launcher_refuses_non_loopback_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit, match="local-only"):
        _run_launcher(monkeypatch, "--host", "0.0.0.0", "--print-config")


def test_control_launcher_prints_explicit_local_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_launcher(monkeypatch, "--print-config")
    # runpy reaches the script's SystemExit(main()) with a successful return code.
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert '"local_only": true' in output
    assert '"control_plane_enabled": true' in output
    assert '"port": 8766' in output
    assert "application_service_ready L0/L1 only" in output
