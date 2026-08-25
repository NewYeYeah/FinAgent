from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_launchers_are_executable() -> None:
    assert os.access(ROOT / "scripts" / "finagent.sh", os.X_OK)
    assert os.access(ROOT / "scripts" / "run_tests.sh", os.X_OK)


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
