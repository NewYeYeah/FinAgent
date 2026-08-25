# FinAgent Environment Isolation Guide

## Assessment of the current hardening

The v1.0.1 update correctly disables automatic third-party pytest plugin loading
and explicitly blocks known ROS 2/ament plugins. That fixes the observed pytest
collection failure, but it is only pytest-level isolation.

A shell that sourced ROS 2 may also carry contamination through:

```text
PYTHONPATH
AMENT_PREFIX_PATH
COLCON_PREFIX_PATH
CMAKE_PREFIX_PATH
LD_LIBRARY_PATH
PKG_CONFIG_PATH
ROS_DISTRO / ROS_VERSION / RMW_IMPLEMENTATION
PATH entries under /opt/ros
```

Those variables affect normal Python commands, Ruff, mypy, package builds and
subprocesses even when pytest plugin autoload is disabled. FinAgent therefore
uses one environment boundary for every development command.

## Create the environment

From the repository root:

```bash
conda env create -f environment/environment.yml
```

The environment file installs the repository from `.` in editable mode. The
previous `-e ..` entry targeted the parent of the repository when this command
was run from the documented location and has been corrected.

## Canonical entrypoint

Validate the environment:

```bash
./scripts/finagent.sh --check
```

Open an interactive isolated child shell:

```bash
./scripts/finagent.sh
```

Inside it, use ordinary commands:

```bash
python -m pytest -q
ruff check src tests --select E9,F63,F7,F82
python -m build
```

Type `exit` to return to the original shell.

A Bash program cannot activate Conda in its parent process. Therefore,
“double-click to enter FinAgent” means starting this isolated child shell. On
Ubuntu, mark the file executable (Git now preserves this) and choose **Run in
Terminal** if the file manager asks how to open it. File-manager double-click
behavior is desktop-specific; running `./scripts/finagent.sh` is the portable
equivalent.

## One-off commands

The same entrypoint runs any command without a dedicated script:

```bash
./scripts/finagent.sh python -m pytest -q
./scripts/finagent.sh ruff check src tests --select E9,F63,F7,F82
./scripts/finagent.sh mypy src/finagent/domain/metrics.py
./scripts/finagent.sh python -m build
```

The existing shortcut remains available:

```bash
./scripts/run_tests.sh -q
./scripts/run_tests.sh -q tests/test_quant_core_hardening_v101.py
```

`run_tests.sh` contains no independent environment policy; it delegates to
`finagent.sh`.

## Reuse from another project script

Preferred thin-wrapper pattern:

```bash
#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${script_dir}/finagent.sh" python -m pytest "$@"
```

If a multi-step Bash program must initialize once and then execute several
commands, source the library:

```bash
source "${repo_root}/scripts/lib/finagent_env.sh"
finagent_initialize_environment

python -m pytest -q
python -m build
```

This keeps cleanup and validation in one maintained location.

## Isolation contract

After Conda activation, the initializer:

- removes ROS, ament and colcon variables;
- clears `PYTHONPATH`, `LD_LIBRARY_PATH` and `PKG_CONFIG_PATH`;
- rebuilds `PATH` from the active Conda environment plus standard system paths;
- sets `PYTHONNOUSERSITE=1`;
- sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`;
- verifies that `python` is `${CONDA_PREFIX}/bin/python`;
- rejects Python earlier than 3.11;
- fails if an `/opt/ros/` entry remains in `sys.path`.

This is intentionally strict. FinAgent does not currently require ROS, custom
CMake prefixes or CUDA shared-library paths. Future external native dependencies
should be added explicitly rather than restoring an inherited ROS environment.

## Configuration and troubleshooting

Use another Conda environment name:

```bash
FINAGENT_ENV_NAME=my-finagent ./scripts/finagent.sh --check
```

If Conda is not on `PATH`, provide its executable:

```bash
FINAGENT_CONDA_EXE="$HOME/miniconda3/bin/conda" ./scripts/finagent.sh --check
```

If activation fails, recreate or update the environment:

```bash
conda env create -f environment/environment.yml
# or
conda env update -n finagent -f environment/environment.yml --prune
```

Do not “fix” an activation error by sourcing ROS 2 again or by adding
`/opt/ros/*` to `PYTHONPATH`.
