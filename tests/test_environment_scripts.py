from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="FinAgent Bash/Conda environment wrappers are a POSIX-only boundary",
)


def test_launchers_are_executable() -> None:
    assert os.access(ROOT / "scripts" / "finagent.sh", os.X_OK)
    assert os.access(ROOT / "scripts" / "run_tests.sh", os.X_OK)
    assert os.access(ROOT / "scripts" / "pull_market_data.py", os.X_OK)
    assert os.access(ROOT / "scripts" / "validate_market_data.py", os.X_OK)
    assert os.access(ROOT / "scripts" / "run_market_backtest.py", os.X_OK)


def _contaminated_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CONDA_DEFAULT_ENV": "finagent",
            "CONDA_PREFIX": sys.prefix,
            "PYTHONPATH": "/opt/ros/jazzy/lib/python3.12/site-packages",
            "AMENT_PREFIX_PATH": "/opt/ros/jazzy",
            "COLCON_PREFIX_PATH": "/tmp/ros_ws/install",
            "CMAKE_PREFIX_PATH": "/opt/ros/jazzy",
            "LD_LIBRARY_PATH": "/opt/ros/jazzy/lib",
            "ROS_DISTRO": "jazzy",
        }
    )
    return env


@POSIX_ONLY
def test_finagent_wrapper_removes_ros_environment() -> None:
    probe = """
import os
import sys
assert os.environ.get('FINAGENT_ENV_ACTIVE') == '1'
assert os.environ.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD') == '1'
for name in ('PYTHONPATH', 'AMENT_PREFIX_PATH', 'COLCON_PREFIX_PATH',
             'CMAKE_PREFIX_PATH', 'LD_LIBRARY_PATH', 'ROS_DISTRO'):
    assert name not in os.environ, (name, os.environ.get(name))
assert not any('/opt/ros/' in item for item in sys.path)
"""
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "finagent.sh"), "python", "-c", probe],
        cwd=ROOT,
        env=_contaminated_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@POSIX_ONLY
def test_finagent_check_reports_active_interpreter() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "finagent.sh"), "--check"],
        cwd=ROOT,
        env=_contaminated_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "conda env:  finagent" in result.stdout
    assert f"python:     {sys.executable}" in result.stdout
    assert "ROS paths:  none" in result.stdout


@POSIX_ONLY
def test_test_wrapper_explicitly_loads_coverage_plugin() -> None:
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "run_tests.sh"),
            "-q",
            "tests/test_quant_core_hardening_v101.py",
            "-k",
            "trade_activity_distinguishes",
            "--cov=finagent",
            "--cov-report=term",
        ],
        cwd=ROOT,
        env=_contaminated_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "TOTAL" in result.stdout
