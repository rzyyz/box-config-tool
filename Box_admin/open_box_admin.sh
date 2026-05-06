#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_URL="${BOX_ADMIN_URL:-http://127.0.0.1:8090}"
STATUS_URL="${APP_URL%/}/api/status"
LOCK_DIR="/tmp/box_admin_open.lock"
STAMP_FILE="/tmp/box_admin_open.last"
RECENT_LAUNCH_SECONDS="${BOX_ADMIN_RECENT_LAUNCH_SECONDS:-8}"

cleanup() {
  rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
}

if ! mkdir "$LOCK_DIR" >/dev/null 2>&1; then
  exit 0
fi
trap cleanup EXIT

recent_launch_detected() {
  [ -f "$STAMP_FILE" ] || return 1
  local now_ts last_ts
  now_ts="$(date +%s)"
  last_ts="$(cat "$STAMP_FILE" 2>/dev/null || echo 0)"
  [[ "$last_ts" =~ ^[0-9]+$ ]] || return 1
  [ $((now_ts - last_ts)) -lt "$RECENT_LAUNCH_SECONDS" ]
}

mark_launch() {
  date +%s >"$STAMP_FILE" 2>/dev/null || true
}

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
  mark_launch

  for browser in epiphany-browser google-chrome google-chrome-stable; do
    if command -v "$browser" >/dev/null 2>&1 || [ -x "$browser" ]; then
      "$browser" "$APP_URL" >/dev/null 2>&1 &
      return 0
    fi
  done

  if command -v snap >/dev/null 2>&1 && snap list chromium >/dev/null 2>&1; then
    snap run chromium "$APP_URL" >/dev/null 2>&1 &
    return 0
  fi

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

if recent_launch_detected; then
  exit 0
fi

open_browser || true
