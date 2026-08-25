#!/usr/bin/env bash
set -euo pipefail

# FinAgent must run outside ROS2 Python plugin discovery.
# pytest automatically discovers installed plugins unless disabled.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

python -m pytest "$@"
