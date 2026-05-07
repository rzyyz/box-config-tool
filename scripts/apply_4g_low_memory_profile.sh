#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
ENABLE_PREPLAN_AUTOSTART="${ENABLE_PREPLAN_AUTOSTART:-0}"
ENABLE_TRAFFIC_AUTOSTART="${ENABLE_TRAFFIC_AUTOSTART:-0}"
ENABLE_BOX_ADMIN_AUTOSTART="${ENABLE_BOX_ADMIN_AUTOSTART:-1}"
ENABLE_CONFIG_AGENT_AUTOSTART="${ENABLE_CONFIG_AGENT_AUTOSTART:-1}"
PREPLAN_JAVA_OPTS="${PREPLAN_JAVA_OPTS:--Xms256m -Xmx512m}"

log() {
  echo "[4g-profile] $*"
}

require_sudo() {
  sudo -v
}

set_enabled() {
  local unit="$1"
  local enabled="$2"
  if [ "$enabled" = "1" ]; then
    sudo systemctl enable "$unit" >/dev/null 2>&1 || true
    log "enable $unit"
  else
    sudo systemctl disable "$unit" >/dev/null 2>&1 || true
    log "disable $unit"
  fi
}

install_preplan_unit() {
  if [ ! -f "${SCRIPT_DIR}/install_preplan_control_service.sh" ]; then
    return 0
  fi
  log "installing low-memory preplan-control service"
  PROJECT_ROOT="${PROJECT_ROOT}" SERVICE_USER="${SERVICE_USER}" \
  ENABLE_AUTOSTART="${ENABLE_PREPLAN_AUTOSTART}" START_SERVICE=1 \
  PREPLAN_JAVA_OPTS="${PREPLAN_JAVA_OPTS}" \
  bash "${SCRIPT_DIR}/install_preplan_control_service.sh"
}

write_traffic_override() {
  local override_dir="/etc/systemd/system/traffic_detect.service.d"
  sudo mkdir -p "${override_dir}"
  sudo tee "${override_dir}/20-low-memory.conf" >/dev/null <<'EOF'
[Service]
Nice=5
OOMScoreAdjust=300
RestartSec=8
KillMode=control-group
TimeoutStopSec=20
LimitNOFILE=65536
EOF
  log "wrote traffic_detect low-memory override"
}

trim_desktop_background() {
  pkill -f 'gnome-software --gapplication-service' >/dev/null 2>&1 || true
  sudo systemctl stop packagekit.service >/dev/null 2>&1 || true
  sudo systemctl stop packagekit-offline-update.service >/dev/null 2>&1 || true
  sudo systemctl disable packagekit.service >/dev/null 2>&1 || true
  sudo systemctl disable packagekit-offline-update.service >/dev/null 2>&1 || true
  log "trimmed packagekit / gnome-software background services"
}

main() {
  require_sudo
  install_preplan_unit
  write_traffic_override
  sudo systemctl daemon-reload

  set_enabled box_admin.service "${ENABLE_BOX_ADMIN_AUTOSTART}"
  set_enabled config_agent.service "${ENABLE_CONFIG_AGENT_AUTOSTART}"
  set_enabled traffic_detect.service "${ENABLE_TRAFFIC_AUTOSTART}"
  if systemctl cat preplan-control.service >/dev/null 2>&1; then
    set_enabled preplan-control.service "${ENABLE_PREPLAN_AUTOSTART}"
  fi

  trim_desktop_background

  sudo systemctl restart traffic_detect.service >/dev/null 2>&1 || true
  sudo systemctl restart box_admin.service >/dev/null 2>&1 || true
  if systemctl cat preplan-control.service >/dev/null 2>&1; then
    sudo systemctl restart preplan-control.service >/dev/null 2>&1 || true
  fi

  log "current enablement:"
  systemctl is-enabled box_admin.service config_agent.service traffic_detect.service preplan-control.service 2>/dev/null || true
  log "current active status:"
  systemctl is-active box_admin.service config_agent.service traffic_detect.service preplan-control.service 2>/dev/null || true
  log "memory snapshot:"
  free -h || true
}

main "$@"
