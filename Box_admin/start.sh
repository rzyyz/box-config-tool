#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export HOME="${HOME:-$(cd ~ && pwd)}"

CONDA_ENV="${BOX_ADMIN_CONDA_ENV:-yolo11_py310}"
CONDA_PROFILE="$HOME/miniforge3/etc/profile.d/conda.sh"
ENV_PREFIX="${BOX_ADMIN_ENV_PREFIX:-$HOME/miniforge3/envs/$CONDA_ENV}"

if [ -f "$CONDA_PROFILE" ]; then
  source "$CONDA_PROFILE"
  conda activate "$CONDA_ENV" || export PATH="$ENV_PREFIX/bin:$PATH"
else
  export PATH="$ENV_PREFIX/bin:$PATH"
fi

cd "$SCRIPT_DIR"
exec python app.py
