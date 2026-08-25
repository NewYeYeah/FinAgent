#!/usr/bin/env bash

# Shared environment initialization for FinAgent launchers.
# This file is meant to be sourced; do not enable shell options here.

finagent_env_error() {
    printf 'FinAgent environment error: %s\n' "$*" >&2
}

finagent_find_conda() {
    if [[ -n "${FINAGENT_CONDA_EXE:-}" && -x "${FINAGENT_CONDA_EXE}" ]]; then
        printf '%s\n' "${FINAGENT_CONDA_EXE}"
        return 0
    fi
    if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
        printf '%s\n' "${CONDA_EXE}"
        return 0
    fi
    if command -v conda >/dev/null 2>&1; then
        command -v conda
        return 0
    fi

    local candidate
    for candidate in \
        "${HOME}/miniconda3/bin/conda" \
        "${HOME}/anaconda3/bin/conda" \
        "/opt/conda/bin/conda"; do
        if [[ -x "${candidate}" ]]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done
    return 1
}

finagent_activate_conda() {
    local env_name="${FINAGENT_ENV_NAME:-finagent}"
    local conda_exe hook

    if [[ "${CONDA_DEFAULT_ENV:-}" == "${env_name}" && -n "${CONDA_PREFIX:-}" ]]; then
        return 0
    fi
    if ! conda_exe="$(finagent_find_conda)"; then
        finagent_env_error "Conda was not found. Create the environment with: conda env create -f environment/environment.yml"
        return 1
    fi
    if ! hook="$(${conda_exe} shell.bash hook 2>/dev/null)"; then
        finagent_env_error "Unable to initialize Conda from ${conda_exe}."
        return 1
    fi
    eval "${hook}"
    if ! conda activate "${env_name}"; then
        finagent_env_error "Conda environment '${env_name}' is unavailable. Run: conda env create -f environment/environment.yml"
        return 1
    fi
}

finagent_sanitize_environment() {
    if [[ -z "${CONDA_PREFIX:-}" ]]; then
        finagent_env_error "CONDA_PREFIX is empty after environment activation."
        return 1
    fi

    # ROS/colcon setup scripts mutate all of these. FinAgent deliberately starts
    # from its Conda interpreter and standard system tools only.
    unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH
    unset ROS_DISTRO ROS_ETC_DIR ROS_VERSION ROS_PYTHON_VERSION
    unset ROS_LOCALHOST_ONLY ROS_DOMAIN_ID RMW_IMPLEMENTATION
    unset PYTHONPATH LD_LIBRARY_PATH PKG_CONFIG_PATH

    export PATH="${CONDA_PREFIX}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    export PYTHONNOUSERSITE=1
    export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
    export FINAGENT_ENV_ACTIVE=1
}

finagent_verify_environment() {
    local env_name="${FINAGENT_ENV_NAME:-finagent}"
    if [[ "${CONDA_DEFAULT_ENV:-}" != "${env_name}" ]]; then
        finagent_env_error "Expected Conda environment '${env_name}', got '${CONDA_DEFAULT_ENV:-none}'."
        return 1
    fi
    if [[ "$(command -v python)" != "${CONDA_PREFIX}/bin/python" ]]; then
        finagent_env_error "Python does not come from ${CONDA_PREFIX}."
        return 1
    fi
    python - <<'PY'
import os
import sys

ros_paths = [path for path in sys.path if "/opt/ros/" in path]
if ros_paths:
    raise SystemExit(f"ROS paths remain in sys.path: {ros_paths}")
if sys.version_info < (3, 11):
    raise SystemExit(f"FinAgent requires Python >= 3.11, got {sys.version.split()[0]}")
if os.environ.get("PYTHONPATH"):
    raise SystemExit("PYTHONPATH must be empty in the FinAgent environment")
PY
}

finagent_initialize_environment() {
    finagent_activate_conda || return 1
    finagent_sanitize_environment || return 1
    finagent_verify_environment || return 1
}
