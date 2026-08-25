#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# finagent.sh intentionally disables third-party pytest auto-discovery so ROS 2
# plugins cannot leak into the project. Coverage flags therefore need the trusted
# pytest-cov plugin to be loaded explicitly.
pytest_plugins=()
for argument in "$@"; do
    if [[ "${argument}" == --cov || "${argument}" == --cov=* || \
          "${argument}" == --cov-report || "${argument}" == --cov-report=* || \
          "${argument}" == --cov-config || "${argument}" == --cov-config=* || \
          "${argument}" == --cov-fail-under || "${argument}" == --cov-fail-under=* ]]; then
        pytest_plugins=(-p pytest_cov.plugin)
        break
    fi
done

exec "${script_dir}/finagent.sh" python -m pytest "${pytest_plugins[@]}" "$@"
