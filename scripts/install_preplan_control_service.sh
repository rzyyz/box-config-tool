#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_HOME="${SERVICE_HOME:-$(getent passwd "$SERVICE_USER" | cut -d: -f6)}"
PREPLAN_SOURCE_DIR="${PREPLAN_SOURCE_DIR:-}"
ENABLE_AUTOSTART="${ENABLE_AUTOSTART:-0}"
START_SERVICE="${START_SERVICE:-0}"
AUTO_INSTALL_JAVA="${PREPLAN_AUTO_INSTALL_JAVA:-0}"
INSTALL_OFFLINE_JAVA="${PREPLAN_INSTALL_OFFLINE_JAVA:-1}"
MIN_JAVA_MAJOR="${PREPLAN_MIN_JAVA_MAJOR:-17}"
JAVA_OPTS="${PREPLAN_JAVA_OPTS:--Xms256m -Xmx512m}"
SERVICE_NAME="preplan-control"
LOG_ROOT="${BOX_CONFIG_LOG_ROOT:-${PROJECT_ROOT}/logs}"

log() {
  echo "[preplan-install] $*"
}

die() {
  echo "[preplan-install][error] $*" >&2
  exit 1
}

find_preplan_source_dir() {
  local candidate
  for candidate in \
    "${PREPLAN_SOURCE_DIR}" \
    "${PROJECT_ROOT}/preplan-control-server" \
    "${PROJECT_ROOT}/test/preplan-control-server"; do
    [ -n "${candidate}" ] || continue
    if [ -f "${candidate}/preplan-control.jar" ]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

find_java_bin() {
  local candidate
  for candidate in \
    "${JAVA_HOME:-}/bin/java" \
    "/usr/lib/jvm/java-17-openjdk-arm64/bin/java" \
    "/usr/bin/java" \
    "$(command -v java 2>/dev/null || true)"; do
    [ -n "${candidate}" ] || continue
    if [ -x "${candidate}" ] && "${candidate}" -version >/dev/null 2>&1; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

java_major_version() {
  local java_bin="$1"
  local version
  version="$("${java_bin}" -version 2>&1 | awk -F '"' '/version/ {print $2; exit}')"
  case "${version}" in
    1.*) echo "${version#1.}" | cut -d. -f1 ;;
    *) echo "${version}" | cut -d. -f1 ;;
  esac
}

find_suitable_java_bin() {
  local java_bin major
  java_bin="$(find_java_bin)" || return 1
  major="$(java_major_version "${java_bin}")"
  if [ -n "${major}" ] && [ "${major}" -ge "${MIN_JAVA_MAJOR}" ] 2>/dev/null; then
    echo "${java_bin}"
    return 0
  fi
  log "Java at ${java_bin} is too old (major=${major:-unknown}); need ${MIN_JAVA_MAJOR}+"
  return 1
}

install_java17_if_allowed() {
  if [ "${AUTO_INSTALL_JAVA}" != "1" ]; then
    return 1
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi
  log "installing openjdk-17-jre-headless"
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-17-jre-headless
}

install_java17_offline_if_available() {
  local installer="${PROJECT_ROOT}/scripts/install_openjdk17_offline.sh"
  if [ "${INSTALL_OFFLINE_JAVA}" != "1" ]; then
    return 1
  fi
  if [ ! -x "${installer}" ] && [ ! -f "${installer}" ]; then
    return 1
  fi
  log "trying offline OpenJDK 17 packages"
  PROJECT_ROOT="${PROJECT_ROOT}" PREPLAN_MIN_JAVA_MAJOR="${MIN_JAVA_MAJOR}" bash "${installer}"
}

main() {
  local preplan_dir
  preplan_dir="$(find_preplan_source_dir)" || {
    log "preplan-control package not found under PROJECT_ROOT, skipping"
    exit 0
  }

  local jar_path="${preplan_dir}/preplan-control.jar"
  local log_dir="${LOG_ROOT}/preplan_control"
  local java_bin

  if ! java_bin="$(find_suitable_java_bin)"; then
    if install_java17_offline_if_available; then
      java_bin="$(find_suitable_java_bin)" || die "offline Java 17 install finished, but suitable java command is still unavailable"
    elif install_java17_if_allowed; then
      java_bin="$(find_suitable_java_bin)" || die "Java 17 install finished, but suitable java command is still unavailable"
    else
      die "Java ${MIN_JAVA_MAJOR}+ not found. Put OpenJDK 17 debs in offline_java/openjdk17_debs, or rerun with PREPLAN_AUTO_INSTALL_JAVA=1 when apt is available"
    fi
  fi

  mkdir -p "${log_dir}" "${preplan_dir}/logs"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${log_dir}" "${preplan_dir}/logs" 2>/dev/null || true

  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "${tmp_file}" <<EOF
[Unit]
Description=Preplan Control Service
After=network.target
Wants=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${preplan_dir}
Environment=HOME=${SERVICE_HOME}
Environment=BOX_CONFIG_LOG_ROOT=${LOG_ROOT}
ExecStart=${java_bin} ${JAVA_OPTS} -jar ${jar_path}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65536
TimeoutStartSec=60
TimeoutStopSec=20
Nice=8
OOMScoreAdjust=350

[Install]
WantedBy=multi-user.target
EOF

  sudo install -m 0644 "${tmp_file}" "${service_file}"
  rm -f "${tmp_file}"
  sudo systemctl daemon-reload

  if [ "${ENABLE_AUTOSTART}" = "1" ]; then
    sudo systemctl enable "${SERVICE_NAME}.service"
    log "enabled ${SERVICE_NAME}.service at boot"
  else
    sudo systemctl disable "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
    log "installed ${SERVICE_NAME}.service without boot autostart"
  fi

  if [ "${START_SERVICE}" = "1" ]; then
    sudo systemctl restart "${SERVICE_NAME}.service"
    log "started ${SERVICE_NAME}.service"
  else
    log "installed ${SERVICE_NAME}.service without starting it"
  fi

  log "service file installed for ${preplan_dir}"
}

main "$@"
