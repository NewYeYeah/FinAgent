#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"

# shellcheck source=lib/finagent_env.sh
source "${script_dir}/lib/finagent_env.sh"

usage() {
    cat <<'EOF'
Usage:
  ./scripts/finagent.sh                 Open an isolated interactive shell
  ./scripts/finagent.sh --check         Print and validate the active environment
  ./scripts/finagent.sh COMMAND [ARGS]  Run one command in the isolated environment

Optional environment variables:
  FINAGENT_ENV_NAME    Conda environment name (default: finagent)
  FINAGENT_CONDA_EXE   Explicit path to the Conda executable
EOF
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
esac

cd "${repo_root}"
finagent_initialize_environment

case "${1:-}" in
    --check)
        printf 'repository: %s\n' "${repo_root}"
        printf 'conda env:  %s\n' "${CONDA_DEFAULT_ENV}"
        printf 'python:     %s\n' "$(command -v python)"
        printf 'version:    %s\n' "$(python --version 2>&1)"
        printf 'ROS paths:  none\n'
        exit 0
        ;;
esac

if (( $# > 0 )); then
    exec "$@"
fi

export FINAGENT_REPO_ROOT="${repo_root}"
export PS1="(finagent-isolated) ${PS1:-\\u@\\h:\\w\\$ }"
printf 'FinAgent isolated shell ready. Repository: %s\n' "${repo_root}"
printf 'Type exit to return to the previous shell.\n'
exec bash --noprofile --norc -i
