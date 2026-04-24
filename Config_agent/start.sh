#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export HOME="${HOME:-$(cd ~ && pwd)}"
LOG_ROOT="${BOX_CONFIG_LOG_ROOT:-${PROJECT_ROOT}/logs}"
LOG_DIR="${LOG_ROOT}/config_agent"
mkdir -p "$LOG_DIR"
export CONFIG_AGENT_LOG_PATH="${CONFIG_AGENT_LOG_PATH:-${LOG_DIR}/config_agent.log}"
exec >>"${LOG_DIR}/service.log" 2>&1
echo "[$(date '+%F %T')] starting Config_agent"

CONDA_PROFILE="$HOME/miniforge3/etc/profile.d/conda.sh"
CONDA_ENV="${CONFIG_AGENT_CONDA_ENV:-yolo11_py310}"
ENV_PREFIX="${CONFIG_AGENT_ENV_PREFIX:-$HOME/miniforge3/envs/$CONDA_ENV}"

if [ -f "$CONDA_PROFILE" ]; then
  # Reuse the project Python environment when it exists on Jetson.
  source "$CONDA_PROFILE"
  conda activate "$CONDA_ENV" || export PATH="$ENV_PREFIX/bin:$PATH"
else
  export PATH="$ENV_PREFIX/bin:$PATH"
fi

cd "$SCRIPT_DIR"
exec python app.py
