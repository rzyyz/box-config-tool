#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SNAP_DIR="${CHROMIUM_SNAP_DIR:-}"

if [ -z "${SNAP_DIR}" ]; then
  if [ -s "${PROJECT_ROOT}/offline_browser/snaps/chromium_3318.snap" ]; then
    SNAP_DIR="${PROJECT_ROOT}/offline_browser/snaps"
  elif [ -s "${PROJECT_ROOT}/offline_browser/browser_snaps_export/chromium_3318.snap" ]; then
    SNAP_DIR="${PROJECT_ROOT}/offline_browser/browser_snaps_export"
  else
    SNAP_DIR="${PROJECT_ROOT}/offline_browser/snaps"
  fi
fi

log() {
  echo "[chromium-offline] $*"
}

need_snap() {
  local file="$1"
  [ -s "${SNAP_DIR}/${file}" ] || {
    log "missing snap package: ${SNAP_DIR}/${file}"
    return 1
  }
}

install_one() {
  local name="$1"
  local file="$2"
  if snap list "$name" >/dev/null 2>&1; then
    log "snap already installed: ${name}"
    return 0
  fi
  need_snap "$file" || return 1
  log "installing ${name} from ${file}"
  sudo snap install --dangerous "${SNAP_DIR}/${file}"
}

if ! command -v snap >/dev/null 2>&1; then
  log "snap command not found; cannot install Chromium offline"
  exit 1
fi

[ -d "${SNAP_DIR}" ] || {
  log "snap package directory not found: ${SNAP_DIR}"
  exit 1
}

install_one bare bare_5.snap
install_one core22 core22_2412.snap
install_one core24 core24_1588.snap
install_one cups cups_1171.snap
install_one gtk-common-themes gtk-common-themes_1535.snap
install_one gnome-46-2404 gnome-46-2404_147.snap
install_one mesa-2404 mesa-2404_1166.snap
install_one chromium chromium_3318.snap

if ! command -v chromium-browser >/dev/null 2>&1 && [ -x /snap/bin/chromium ]; then
  sudo ln -sf /snap/bin/chromium /usr/local/bin/chromium-browser
fi

log "installed snaps:"
snap list | grep -E 'chromium|core22|core24|gtk-common-themes|gnome-46-2404|mesa-2404|cups|bare' || true
