#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export HOME="${HOME:-$(cd ~ && pwd)}"
LOG_ROOT="${BOX_CONFIG_LOG_ROOT:-${PROJECT_ROOT}/logs}"
LOG_DIR="${LOG_ROOT}/traffic_detect"
mkdir -p "$LOG_DIR"
export RUNTIME_LOG_DIR="${RUNTIME_LOG_DIR:-${LOG_DIR}}"
exec >>"${LOG_DIR}/service.log" 2>&1
echo "[$(date '+%F %T')] starting Traffic_detect"
CONDA_ENV="${TRAFFIC_DETECT_CONDA_ENV:-yolo11_py310}"
CONDA_PROFILE="$HOME/miniforge3/etc/profile.d/conda.sh"
ENV_PREFIX="${TRAFFIC_DETECT_ENV_PREFIX:-$HOME/miniforge3/envs/$CONDA_ENV}"
ENV_FILE="$SCRIPT_DIR/runtime.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

if [ -f "$CONDA_PROFILE" ]; then
  source "$CONDA_PROFILE"
  conda activate "$CONDA_ENV" || export PATH="$ENV_PREFIX/bin:$PATH"
else
  export PATH="$ENV_PREFIX/bin:$PATH"
fi

cd "$SCRIPT_DIR"
exec python main.py
