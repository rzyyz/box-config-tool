#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_HOME="${SERVICE_HOME:-$(getent passwd "$SERVICE_USER" | cut -d: -f6)}"
TARGET_PROJECT_ROOT="${TARGET_PROJECT_ROOT:-${SERVICE_HOME}/Project/box_config_tool}"
PROJECT_ROOT="${PROJECT_ROOT:-$TARGET_PROJECT_ROOT}"
LOG_ROOT="${BOX_CONFIG_LOG_ROOT:-${PROJECT_ROOT}/logs}"
STAMP="$(date '+%Y%m%d_%H%M%S')"
OUT_DIR="${PROJECT_ROOT}/release/diagnostics_${STAMP}"
OUT_TAR="${PROJECT_ROOT}/release/diagnostics_${STAMP}.tar.gz"

mkdir -p "${OUT_DIR}/service_status" "${OUT_DIR}/logs" "${OUT_DIR}/configs" "${PROJECT_ROOT}/release"

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [ -e "$src" ]; then
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
  fi
}

capture_text() {
  local file="$1"
  shift
  ("$@") >"$file" 2>&1 || true
}

capture_sudo_text() {
  local file="$1"
  shift
  if [ "$(id -u)" -eq 0 ]; then
    ("$@") >"$file" 2>&1 || true
  else
    sudo "$@" >"$file" 2>&1 || true
  fi
}

capture_text "${OUT_DIR}/service_status/system_overview.txt" uname -a
capture_text "${OUT_DIR}/service_status/free.txt" free -h
capture_text "${OUT_DIR}/service_status/uptime.txt" uptime
capture_text "${OUT_DIR}/service_status/df.txt" df -h
capture_text "${OUT_DIR}/service_status/ps_top.txt" ps -eo pid,user,comm,rss,args --sort=-rss
capture_text "${OUT_DIR}/service_status/listening_ports.txt" ss -ltnp

for service in box_admin.service config_agent.service traffic_detect.service preplan-control.service; do
  capture_text "${OUT_DIR}/service_status/${service}.status.txt" systemctl status "$service" --no-pager
  capture_sudo_text "${OUT_DIR}/service_status/${service}.journal.txt" journalctl -u "$service" -n 300 --no-pager
done

copy_if_exists "${LOG_ROOT}" "${OUT_DIR}/logs/runtime_logs"
copy_if_exists "${PROJECT_ROOT}/Traffic_detect/log" "${OUT_DIR}/logs/traffic_log_dir"
copy_if_exists "${PROJECT_ROOT}/Traffic_detect/queue_csv" "${OUT_DIR}/logs/queue_csv"
copy_if_exists "${PROJECT_ROOT}/Box_admin/config" "${OUT_DIR}/configs/box_admin"
copy_if_exists "${PROJECT_ROOT}/Traffic_detect/config" "${OUT_DIR}/configs/traffic_detect"
copy_if_exists "${PROJECT_ROOT}/DeepStream-Yolo/deepstream_app_config.txt" "${OUT_DIR}/configs/deepstream_app_config.txt"

tar -czf "${OUT_TAR}" -C "${PROJECT_ROOT}/release" "$(basename "$OUT_DIR")"
rm -rf "${OUT_DIR}"

echo "[diagnostics] created: ${OUT_TAR}"
