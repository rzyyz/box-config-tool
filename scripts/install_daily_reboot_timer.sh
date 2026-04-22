#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[daily-reboot] Installing daily reboot timer: 03:30"
sudo install -m 0644 "${SCRIPT_DIR}/box_daily_reboot.service" /etc/systemd/system/box_daily_reboot.service
sudo install -m 0644 "${SCRIPT_DIR}/box_daily_reboot.timer" /etc/systemd/system/box_daily_reboot.timer
sudo systemctl daemon-reload
sudo systemctl enable --now box_daily_reboot.timer

echo "[daily-reboot] Installed and enabled."
echo "[daily-reboot] Check with:"
echo "  systemctl list-timers box_daily_reboot.timer"
echo "  systemctl status box_daily_reboot.timer --no-pager"
