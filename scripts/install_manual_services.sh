#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECTED_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_PROJECT_ROOT="/home/nvidia/Project/box_config_tool"
PROJECT_ROOT="${PROJECT_ROOT:-$DETECTED_ROOT}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
SERVICE_HOME="${SERVICE_HOME:-$(getent passwd "$SERVICE_USER" | cut -d: -f6)}"
BOX_ADMIN_DIR="${PROJECT_ROOT}/Box_admin"
CONFIG_AGENT_DIR="${PROJECT_ROOT}/Config_agent"
TRAFFIC_DIR="${PROJECT_ROOT}/Traffic_detect"
INSTALL_DAILY_REBOOT="${INSTALL_DAILY_REBOOT:-0}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[install] Installing manual-only service files."
echo "[install] PROJECT_ROOT=${PROJECT_ROOT}"
echo "[install] SERVICE_USER=${SERVICE_USER}"
echo "[install] SERVICE_HOME=${SERVICE_HOME}"

if [ ! -f "${BOX_ADMIN_DIR}/box_admin.service.example" ] || [ ! -f "${CONFIG_AGENT_DIR}/config_agent.service.example" ] || [ ! -f "${TRAFFIC_DIR}/traffic_detect.service.example" ]; then
  echo "[install][error] Cannot find service examples under PROJECT_ROOT=${PROJECT_ROOT}" >&2
  echo "[install][error] If you copied Box_admin/Config_agent/Traffic_detect directly to another path, run:" >&2
  echo "  PROJECT_ROOT=/actual/project/root bash scripts/install_manual_services.sh" >&2
  exit 1
fi

sed \
  -e "s#User=nvidia#User=${SERVICE_USER}#g" \
  -e "s#${DEFAULT_PROJECT_ROOT}#${PROJECT_ROOT}#g" \
  -e "s#Environment=HOME=/home/nvidia#Environment=HOME=${SERVICE_HOME}#g" \
  "${BOX_ADMIN_DIR}/box_admin.service.example" > "${TMP_DIR}/box_admin.service"

sed \
  -e "s#User=nvidia#User=${SERVICE_USER}#g" \
  -e "s#${DEFAULT_PROJECT_ROOT}#${PROJECT_ROOT}#g" \
  -e "s#Environment=HOME=/home/nvidia#Environment=HOME=${SERVICE_HOME}#g" \
  "${CONFIG_AGENT_DIR}/config_agent.service.example" > "${TMP_DIR}/config_agent.service"

sed \
  -e "s#User=nvidia#User=${SERVICE_USER}#g" \
  -e "s#${DEFAULT_PROJECT_ROOT}#${PROJECT_ROOT}#g" \
  -e "s#Environment=HOME=/home/nvidia#Environment=HOME=${SERVICE_HOME}#g" \
  "${TRAFFIC_DIR}/traffic_detect.service.example" > "${TMP_DIR}/traffic_detect.service"

sudo install -m 0644 "${TMP_DIR}/box_admin.service" /etc/systemd/system/box_admin.service
sudo install -m 0644 "${TMP_DIR}/config_agent.service" /etc/systemd/system/config_agent.service
sudo install -m 0644 "${TMP_DIR}/traffic_detect.service" /etc/systemd/system/traffic_detect.service
sudo systemctl daemon-reload

sudo systemctl disable box_admin.service || true
sudo systemctl disable config_agent.service || true
sudo systemctl disable traffic_detect.service || true

echo "[install] Installed services, but did NOT enable autostart."
echo "[install] Start manually when needed:"
echo "  sudo systemctl start box_admin.service"
echo "  sudo systemctl start config_agent.service"
echo "  sudo systemctl start traffic_detect.service"

if [ "${INSTALL_DAILY_REBOOT}" = "1" ]; then
  echo "[install] INSTALL_DAILY_REBOOT=1, enabling daily reboot timer."
  bash "${SCRIPT_DIR}/install_daily_reboot_timer.sh"
else
  echo "[install] Daily reboot timer is not enabled by default."
  echo "[install] For final delivery boxes, run:"
  echo "  bash scripts/install_daily_reboot_timer.sh"
fi
