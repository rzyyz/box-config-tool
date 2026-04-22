#!/usr/bin/env bash

set -euo pipefail

SERVICES=(
  "traffic_detect.service"
  "config_agent.service"
  "box_admin.service"
  "box_daily_reboot.timer"
)

echo "[safe] Stop and disable project services. This does not delete code."

for service in "${SERVICES[@]}"; do
  if systemctl list-unit-files | grep -q "^${service}"; then
    echo "[safe] stopping ${service}"
    sudo systemctl stop "${service}" || true
    echo "[safe] disabling ${service}"
    sudo systemctl disable "${service}" || true
  else
    echo "[safe] ${service} is not installed, skip"
  fi
done

echo "[safe] stopping possible DeepStream processes"
sudo pkill -f '[d]eepstream-app' || true

echo "[safe] refreshing systemd"
sudo systemctl daemon-reload || true

echo "[safe] done. Services can still be started manually with systemctl start."
