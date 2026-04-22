#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT_WAS_SET="${PROJECT_ROOT+x}"
PROJECT_ROOT="${PROJECT_ROOT:-$SOURCE_ROOT}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_HOME="${SERVICE_HOME:-$(getent passwd "$SERVICE_USER" | cut -d: -f6)}"
TARGET_PROJECT_ROOT="${TARGET_PROJECT_ROOT:-${SERVICE_HOME}/Project/box_config_tool}"
EXPECTED_ROOT="${EXPECTED_ROOT:-$TARGET_PROJECT_ROOT}"
AUTO_INSTALL_TO_TARGET="${AUTO_INSTALL_TO_TARGET:-1}"
ALLOW_ROOT_SERVICE_USER="${ALLOW_ROOT_SERVICE_USER:-0}"
CONDA_HOME="${CONDA_HOME:-${SERVICE_HOME}/miniforge3}"
CONDA_ENV="${CONDA_ENV:-yolo11_py310}"
MINIFORGE_INSTALLER="${MINIFORGE_INSTALLER:-}"
ENABLE_AUTOSTART="${ENABLE_AUTOSTART:-1}"
START_SERVICES="${START_SERVICES:-1}"
START_TRAFFIC="${START_TRAFFIC:-1}"
INSTALL_DAILY_REBOOT="${INSTALL_DAILY_REBOOT:-0}"
INSTALL_DESKTOP_ICON="${INSTALL_DESKTOP_ICON:-1}"
PIP_WHEEL_DIR="${PIP_WHEEL_DIR:-}"
REQUIRED_IMPORTS=("flask" "fastapi" "uvicorn" "flask_cors")
REQUIRED_PIP_PACKAGES=("flask" "fastapi" "uvicorn" "flask-cors")
OFFLINE_REQUIREMENTS="${OFFLINE_REQUIREMENTS:-}"

log() {
  echo "[onekey] $*"
}

die() {
  echo "[onekey][error] $*" >&2
  exit 1
}

need_file() {
  [ -e "$1" ] || die "missing required path: $1"
}

prepare_project_root() {
  if [ "$SERVICE_USER" = "root" ] && [ "$ALLOW_ROOT_SERVICE_USER" != "1" ]; then
    die "service user resolved to root. Run this script as the box login user, or set SERVICE_USER=<login-user>"
  fi

  if [ -z "$SERVICE_HOME" ]; then
    die "cannot find home directory for SERVICE_USER=${SERVICE_USER}"
  fi

  if [ -z "$PROJECT_ROOT_WAS_SET" ] && [ "$AUTO_INSTALL_TO_TARGET" = "1" ] && [ "$SOURCE_ROOT" != "$TARGET_PROJECT_ROOT" ]; then
    log "copying package to fixed deploy path: ${TARGET_PROJECT_ROOT}"
    mkdir -p "$(dirname "$TARGET_PROJECT_ROOT")"
    mkdir -p "$TARGET_PROJECT_ROOT"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --exclude '.git' "${SOURCE_ROOT}/" "${TARGET_PROJECT_ROOT}/"
    else
      cp -a "${SOURCE_ROOT}/." "$TARGET_PROJECT_ROOT/"
    fi
    PROJECT_ROOT="$TARGET_PROJECT_ROOT"
    SCRIPT_DIR="${PROJECT_ROOT}/scripts"
  fi
}

require_project_layout() {
  need_file "${PROJECT_ROOT}/Box_admin/start.sh"
  need_file "${PROJECT_ROOT}/Config_agent/start.sh"
  need_file "${PROJECT_ROOT}/Traffic_detect/start.sh"
  need_file "${PROJECT_ROOT}/DeepStream-Yolo/deepstream_app_config.txt"
  need_file "${PROJECT_ROOT}/scripts/install_manual_services.sh"

  if [ "$PROJECT_ROOT" != "$EXPECTED_ROOT" ]; then
    log "PROJECT_ROOT is ${PROJECT_ROOT}"
    log "recommended fixed deploy path is ${EXPECTED_ROOT}"
    log "services will still be generated for PROJECT_ROOT=${PROJECT_ROOT}"
  fi
}

require_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    return 0
  fi
  sudo -v || die "sudo permission is required to install and start systemd services"
}

make_scripts_executable() {
  log "making project scripts executable"
  chmod +x "${PROJECT_ROOT}"/scripts/*.sh || true
  chmod +x "${PROJECT_ROOT}"/Box_admin/*.sh || true
  chmod +x "${PROJECT_ROOT}"/Config_agent/*.sh || true
  chmod +x "${PROJECT_ROOT}"/Traffic_detect/start.sh || true
}

install_miniforge_if_needed() {
  if [ -x "${CONDA_HOME}/bin/conda" ]; then
    log "Miniforge already exists: ${CONDA_HOME}"
    return 0
  fi

  local installer="${MINIFORGE_INSTALLER:-${PROJECT_ROOT}/Miniforge3-Linux-aarch64.sh}"
  [ -f "$installer" ] || die "Miniforge not found. Put Miniforge3-Linux-aarch64.sh in PROJECT_ROOT or set MINIFORGE_INSTALLER=/path/to/installer"

  log "installing Miniforge to ${CONDA_HOME}"
  bash "$installer" -b -p "$CONDA_HOME"
}

load_conda() {
  # shellcheck disable=SC1091
  source "${CONDA_HOME}/etc/profile.d/conda.sh"
}

conda_env_exists() {
  conda env list | awk '{print $1}' | grep -Fxq "$1"
}

select_or_create_conda_env() {
  load_conda

  if conda_env_exists "$CONDA_ENV"; then
    RUNTIME_CONDA_ENV="$CONDA_ENV"
    log "using conda env: ${RUNTIME_CONDA_ENV}"
    return 0
  fi

  log "conda env ${CONDA_ENV} does not exist; trying offline create from local conda package cache"
  if conda create -y -n "$CONDA_ENV" python=3.10 --offline; then
    RUNTIME_CONDA_ENV="$CONDA_ENV"
    log "created conda env: ${RUNTIME_CONDA_ENV}"
    return 0
  fi

  RUNTIME_CONDA_ENV="base"
  log "could not create ${CONDA_ENV} offline; falling back to conda env: base"
}

find_wheel_dir() {
  if [ -n "$PIP_WHEEL_DIR" ]; then
    [ -d "$PIP_WHEEL_DIR" ] || die "PIP_WHEEL_DIR does not exist: ${PIP_WHEEL_DIR}"
    echo "$PIP_WHEEL_DIR"
    return 0
  fi

  for candidate in \
    "${PROJECT_ROOT}/python_wheels" \
    "${PROJECT_ROOT}/wheels" \
    "${PROJECT_ROOT}/offline_wheels" \
    "${PROJECT_ROOT}/packages" \
    "${PROJECT_ROOT}/release/python_wheels"; do
    if [ -d "$candidate" ] && find "$candidate" -maxdepth 1 -name '*.whl' | grep -q .; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

python_has_imports() {
  local code
  code="$(printf 'import %s\n' "${REQUIRED_IMPORTS[@]}")"
  python - <<PY
${code}
PY
}

ensure_python_packages() {
  load_conda
  conda activate "$RUNTIME_CONDA_ENV"

  if python_has_imports; then
    log "required Python packages are already available in ${RUNTIME_CONDA_ENV}"
    return 0
  fi

  local wheel_dir
  if wheel_dir="$(find_wheel_dir)"; then
    log "installing Python packages from local wheels: ${wheel_dir}"
    local requirements_file="${OFFLINE_REQUIREMENTS:-${PROJECT_ROOT}/python_requirements_offline.txt}"
    if [ -f "$requirements_file" ]; then
      python -m pip install --no-index --find-links "$wheel_dir" -r "$requirements_file"
    else
      python -m pip install --no-index --find-links "$wheel_dir" "${REQUIRED_PIP_PACKAGES[@]}"
    fi
  else
    die "required Python packages are missing and no local wheel directory was found. Put wheels under python_wheels/ or set PIP_WHEEL_DIR=/path/to/wheels"
  fi

  python_has_imports || die "Python package check still failed after wheel installation"
}

install_sudoers() {
  local sudoers_tmp
  sudoers_tmp="$(mktemp)"
  cat > "$sudoers_tmp" <<EOF
# Installed by box_config_tool/scripts/install_onekey.sh
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start traffic_detect.service, /usr/bin/systemctl stop traffic_detect.service, /usr/bin/systemctl restart traffic_detect.service, /usr/bin/systemctl enable traffic_detect.service, /usr/bin/systemctl disable traffic_detect.service
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start config_agent.service, /usr/bin/systemctl stop config_agent.service, /usr/bin/systemctl restart config_agent.service, /usr/bin/systemctl enable config_agent.service, /usr/bin/systemctl disable config_agent.service
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start box_admin.service, /usr/bin/systemctl stop box_admin.service, /usr/bin/systemctl restart box_admin.service, /usr/bin/systemctl enable box_admin.service, /usr/bin/systemctl disable box_admin.service
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/nmcli connection modify *, /usr/bin/nmcli connection up *
EOF

  sudo visudo -cf "$sudoers_tmp" >/dev/null
  sudo install -m 0440 "$sudoers_tmp" /etc/sudoers.d/box_config_tool
  rm -f "$sudoers_tmp"
  log "installed sudoers: /etc/sudoers.d/box_config_tool"
}

install_services() {
  log "installing systemd services"
  PROJECT_ROOT="$PROJECT_ROOT" SERVICE_USER="$SERVICE_USER" SERVICE_HOME="$SERVICE_HOME" INSTALL_DAILY_REBOOT=0 \
    bash "${PROJECT_ROOT}/scripts/install_manual_services.sh"

  for service in box_admin.service config_agent.service traffic_detect.service; do
    sudo mkdir -p "/etc/systemd/system/${service}.d"
  done

cat > /tmp/box_admin_env.conf <<EOF
[Service]
Environment=HOME=${SERVICE_HOME}
Environment=BOX_ADMIN_CONDA_ENV=${RUNTIME_CONDA_ENV}
EOF
  cat > /tmp/config_agent_env.conf <<EOF
[Service]
Environment=HOME=${SERVICE_HOME}
Environment=CONFIG_AGENT_CONDA_ENV=${RUNTIME_CONDA_ENV}
EOF
  cat > /tmp/traffic_detect_env.conf <<EOF
[Service]
Environment=HOME=${SERVICE_HOME}
Environment=TRAFFIC_DETECT_CONDA_ENV=${RUNTIME_CONDA_ENV}
EOF

  sudo install -m 0644 /tmp/box_admin_env.conf /etc/systemd/system/box_admin.service.d/10-runtime-env.conf
  sudo install -m 0644 /tmp/config_agent_env.conf /etc/systemd/system/config_agent.service.d/10-runtime-env.conf
  sudo install -m 0644 /tmp/traffic_detect_env.conf /etc/systemd/system/traffic_detect.service.d/10-runtime-env.conf
  rm -f /tmp/box_admin_env.conf /tmp/config_agent_env.conf /tmp/traffic_detect_env.conf

  sudo systemctl daemon-reload
}

configure_autostart() {
  if [ "$ENABLE_AUTOSTART" = "1" ]; then
    log "enabling project services at boot"
    sudo systemctl enable box_admin.service
    sudo systemctl enable config_agent.service
    sudo systemctl enable traffic_detect.service
  else
    log "ENABLE_AUTOSTART=0, services will remain disabled at boot"
    sudo systemctl disable box_admin.service config_agent.service traffic_detect.service || true
  fi

  if [ "$INSTALL_DAILY_REBOOT" = "1" ]; then
    bash "${PROJECT_ROOT}/scripts/install_daily_reboot_timer.sh"
  fi
}

install_desktop_icon() {
  [ "$INSTALL_DESKTOP_ICON" = "1" ] || return 0
  [ -d "${SERVICE_HOME}/Desktop" ] || return 0

  local desktop_tmp
  desktop_tmp="$(mktemp)"
  cat > "$desktop_tmp" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Box Admin
Name[zh_CN]=盒子配置工具
Comment=打开盒子本地配置页面
Comment[zh_CN]=打开盒子本地配置页面
Exec=/bin/bash -lc 'exec "${PROJECT_ROOT}/Box_admin/open_box_admin.sh"'
Path=${PROJECT_ROOT}/Box_admin
Icon=preferences-system-network
Terminal=false
Categories=Settings;Network;
StartupNotify=true
EOF

  install -m 0755 "$desktop_tmp" "${SERVICE_HOME}/Desktop/box_admin.desktop"
  rm -f "$desktop_tmp"
  chown "${SERVICE_USER}:${SERVICE_USER}" "${SERVICE_HOME}/Desktop/box_admin.desktop" 2>/dev/null || true
  sudo -u "$SERVICE_USER" gio set "${SERVICE_HOME}/Desktop/box_admin.desktop" metadata::trusted true >/dev/null 2>&1 || true
  log "installed desktop shortcut: ${SERVICE_HOME}/Desktop/box_admin.desktop"
}

start_services() {
  [ "$START_SERVICES" = "1" ] || return 0

  log "starting box_admin.service and config_agent.service"
  sudo systemctl restart box_admin.service
  sudo systemctl restart config_agent.service

  if [ "$START_TRAFFIC" = "1" ]; then
    log "starting traffic_detect.service"
    sudo systemctl restart traffic_detect.service
  else
    log "START_TRAFFIC=0, traffic_detect.service is installed but not started"
  fi
}

verify_install() {
  log "service enabled state:"
  systemctl is-enabled box_admin.service || true
  systemctl is-enabled config_agent.service || true
  systemctl is-enabled traffic_detect.service || true

  log "service active state:"
  systemctl is-active box_admin.service || true
  systemctl is-active config_agent.service || true
  systemctl is-active traffic_detect.service || true

  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 5 http://127.0.0.1:8090/api/status >/dev/null \
      && log "Box_admin is reachable: http://127.0.0.1:8090" \
      || log "Box_admin is not reachable yet; check: journalctl -u box_admin.service -n 80 --no-pager"
  fi
}

main() {
  prepare_project_root
  require_project_layout
  require_sudo
  make_scripts_executable
  install_miniforge_if_needed
  select_or_create_conda_env
  ensure_python_packages
  install_sudoers
  install_services
  configure_autostart
  install_desktop_icon
  start_services
  verify_install

  log "done"
  log "open: http://127.0.0.1:8090 or http://<box-ip>:8090"
}

main "$@"
