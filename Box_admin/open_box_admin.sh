#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_URL="${BOX_ADMIN_URL:-http://127.0.0.1:8090}"
STATUS_URL="${APP_URL%/}/api/status"

is_running() {
  curl -fsS --max-time 2 "$STATUS_URL" >/dev/null 2>&1
}

try_start_service() {
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q '^box_admin\.service'; then
    systemctl start box_admin.service >/dev/null 2>&1 || true
  fi
}

try_start_local() {
  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal -- bash -lc "cd \"$SCRIPT_DIR\" && bash start.sh; exec bash" >/dev/null 2>&1 || true
  else
    (cd "$SCRIPT_DIR" && bash start.sh >/tmp/box_admin_manual.log 2>&1 &)
  fi
}

open_browser() {
  export DISPLAY="${DISPLAY:-:0}"
  export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

  for browser in google-chrome google-chrome-stable chromium-browser chromium /snap/bin/chromium epiphany-browser; do
    if command -v "$browser" >/dev/null 2>&1 || [ -x "$browser" ]; then
      "$browser" "$APP_URL" >/dev/null 2>&1 &
      return 0
    fi
  done

  xdg-open "$APP_URL" >/dev/null 2>&1 && return 0
  sensible-browser "$APP_URL" >/dev/null 2>&1 && return 0
  return 1
}

if ! is_running; then
  try_start_service
  sleep 2
fi

if ! is_running; then
  try_start_local
  sleep 3
fi

open_browser || true
