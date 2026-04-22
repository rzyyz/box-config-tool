import configparser
import csv
import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlunparse

from flask import Flask, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEEPSTREAM_CONFIG_PATH = Path(
    os.getenv(
        "BOX_ADMIN_DEEPSTREAM_CONFIG",
        str(PROJECT_ROOT / "DeepStream-Yolo" / "deepstream_app_config.txt"),
    )
)
TRAFFIC_ROOT = Path(
    os.getenv(
        "BOX_ADMIN_TRAFFIC_ROOT",
        str(PROJECT_ROOT / "Traffic_detect"),
    )
)
TRAFFIC_CONFIG_DIR = TRAFFIC_ROOT / "config"
TRAFFIC_LOG_DIR = TRAFFIC_ROOT / "log"
TRAFFIC_QUEUE_DIR = TRAFFIC_ROOT / "queue_csv"
TRAFFIC_RUNTIME_ENV_PATH = TRAFFIC_ROOT / "runtime.env"
CAMERA_BINDINGS_PATH = Path(
    os.getenv(
        "BOX_ADMIN_CAMERA_BINDINGS",
        str(BASE_DIR / "config" / "camera_bindings.json"),
    )
)
INTERFACE_NOTES_PATH = Path(
    os.getenv(
        "BOX_ADMIN_INTERFACE_NOTES",
        str(BASE_DIR / "config" / "interface_notes.json"),
    )
)
WEB_HOST = os.getenv("BOX_ADMIN_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("BOX_ADMIN_PORT", "8090"))
NETWORK_INTERFACE = os.getenv("BOX_ADMIN_INTERFACE", "")
LOG_PATH = Path(os.getenv("BOX_ADMIN_LOG_PATH", "/tmp/box_admin.log"))
DEFAULT_SIGNAL_CONTROLLER_HOST = os.getenv("BOX_ADMIN_DEFAULT_SIGNAL_HOST", "172.16.4.246")
DEFAULT_SIGNAL_CONTROLLER_PORT = int(os.getenv("BOX_ADMIN_DEFAULT_SIGNAL_PORT", "40000"))


def _parse_services() -> list[str]:
    raw = os.getenv("BOX_ADMIN_SERVICES", "traffic_detect.service,config_agent.service,box_admin.service")
    return [item.strip() for item in raw.split(",") if item.strip()]


SERVICES = _parse_services()
SERVICE_DISPLAY_NAMES = {
    "traffic_detect.service": "路口感知检测服务",
    "config_agent.service": "检测线数据接收服务",
    "box_admin.service": "智能感知系统配置工具服务",
}
SERVICE_STATUS_LABELS = {
    "active": "运行中",
    "running": "运行中",
    "inactive": "已暂停",
    "failed": "异常",
    "activating": "启动中",
    "deactivating": "停止中",
    "unknown": "未知",
}
SERVICE_AUTOSTART_LABELS = {
    "enabled": "已开启",
    "disabled": "已关闭",
    "static": "不支持开机自启",
    "masked": "已屏蔽",
    "not-found": "未安装",
}
_SERVICE_STATUS_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
SERVICE_STATUS_CACHE_SECONDS = 1.5
CALIBRATION_FILES = {
    "lines_config": TRAFFIC_CONFIG_DIR / "lines_config.json",
    "zones_config": TRAFFIC_CONFIG_DIR / "zones_config.json",
    "zones_queue": TRAFFIC_CONFIG_DIR / "zones_queue.json",
    "headway_config": TRAFFIC_CONFIG_DIR / "headway_config.json",
    "base_length": TRAFFIC_CONFIG_DIR / "base_length.json",
}

app = Flask(__name__, template_folder="templates", static_folder="static")


def log_line(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def load_runtime_env() -> dict[str, str]:
    if not TRAFFIC_RUNTIME_ENV_PATH.exists():
        return {}
    env_map: dict[str, str] = {}
    for raw_line in TRAFFIC_RUNTIME_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip()
    return env_map


def save_runtime_env(env_map: dict[str, str]) -> None:
    TRAFFIC_RUNTIME_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(env_map.items())]
    TRAFFIC_RUNTIME_ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_signal_controller_config() -> dict[str, Any]:
    runtime_env = load_runtime_env()
    host = runtime_env.get("GB_TSC_IP", DEFAULT_SIGNAL_CONTROLLER_HOST).strip() or DEFAULT_SIGNAL_CONTROLLER_HOST
    port_text = runtime_env.get("GB_TSC_PORT", str(DEFAULT_SIGNAL_CONTROLLER_PORT)).strip() or str(DEFAULT_SIGNAL_CONTROLLER_PORT)
    try:
        port = int(port_text)
    except ValueError:
        port = DEFAULT_SIGNAL_CONTROLLER_PORT
    return {"host": host, "port": port}


def _is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return False
    return geteuid() == 0


def run_command(args: list[str], require_root: bool = False, timeout: int = 20) -> dict[str, Any]:
    cmd = list(args)
    if require_root and not _is_root():
        cmd = ["sudo", "-n"] + cmd
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": f"命令不存在: {cmd[0]}",
            "cmd": shlex.join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": "",
            "stderr": "命令执行超时",
            "cmd": shlex.join(cmd),
        }
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
        "cmd": shlex.join(cmd),
    }


def get_hostname() -> str:
    return socket.gethostname()


def service_display_name(name: str) -> str:
    return SERVICE_DISPLAY_NAMES.get(name, name)


def service_autostart_status(name: str) -> dict[str, Any]:
    result = run_command(["systemctl", "is-enabled", name], require_root=False, timeout=3)
    status = (result["stdout"] or result["stderr"] or "unknown").splitlines()[0].strip()
    return {
        "autostart": status,
        "autostart_enabled": status == "enabled",
        "autostart_label": SERVICE_AUTOSTART_LABELS.get(status, status or "未知"),
    }


def service_status(name: str, use_cache: bool = True) -> dict[str, Any]:
    now = time.monotonic()
    cached = _SERVICE_STATUS_CACHE.get(name)
    if use_cache and cached and now - cached[0] < SERVICE_STATUS_CACHE_SECONDS:
        return dict(cached[1])
    result = run_command(["systemctl", "is-active", name], require_root=False, timeout=3)
    status = result["stdout"] if result["ok"] else (result["stdout"] or "failed")
    detail = result["stderr"] or result["stdout"] or ""
    payload = {
        "name": name,
        "display_name": service_display_name(name),
        "status": status,
        "status_label": SERVICE_STATUS_LABELS.get(status, status or "未知"),
        "detail": detail,
    }
    payload.update(service_autostart_status(name))
    _SERVICE_STATUS_CACHE[name] = (now, payload)
    return dict(payload)


def mask_to_prefix(mask: str) -> int:
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def prefix_to_mask(prefix: str) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)


def ensure_ipv4(value: str, field_name: str) -> None:
    try:
        ipaddress.IPv4Address(value)
    except Exception as exc:  # pragma: no cover - user-facing validation
        raise ValueError(f"{field_name} 不合法: {value}") from exc


def get_active_interface() -> str:
    if NETWORK_INTERFACE:
        return NETWORK_INTERFACE
    result = run_command(["ip", "route", "show", "default"])
    if not result["ok"]:
        return ""
    match = re.search(r"dev\s+(\S+)", result["stdout"])
    return match.group(1) if match else ""


def load_interface_notes() -> dict[str, str]:
    if not INTERFACE_NOTES_PATH.exists():
        return {}
    try:
        data = json.loads(INTERFACE_NOTES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    notes = data.get("notes", {})
    if not isinstance(notes, dict):
        return {}
    return {str(key): str(value) for key, value in notes.items()}


def save_interface_notes(notes: dict[str, str]) -> None:
    INTERFACE_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "notes": notes,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    INTERFACE_NOTES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_interface_note(interface_type: str, device: str) -> str:
    if interface_type == "wifi":
        return f"无线网口 {device}"
    if interface_type == "ethernet":
        return f"有线网口 {device}"
    return f"网口 {device}"


def get_interfaces() -> list[dict[str, str]]:
    result = run_command(["nmcli", "-t", "-f", "DEVICE,TYPE,CONNECTION", "device", "status"])
    notes = load_interface_notes()
    interfaces: list[dict[str, str]] = []
    if not result["ok"]:
        return interfaces
    for line in result["stdout"].splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        device, dev_type, connection = parts[0], parts[1], parts[2]
        if dev_type not in {"ethernet", "wifi"}:
            continue
        default_note = default_interface_note(dev_type, device)
        note = notes.get(device, "").strip()
        interfaces.append(
            {
                "device": device,
                "type": dev_type,
                "connection": connection,
                "note": note,
                "default_note": default_note,
                "display_name": f"{device} | {note or default_note}" + (f" | {connection}" if connection else ""),
            }
        )
    return interfaces


def get_network_info(interface: str) -> dict[str, Any]:
    result = run_command(
        [
            "nmcli",
            "-t",
            "-f",
            "GENERAL.CONNECTION,GENERAL.TYPE,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS",
            "device",
            "show",
            interface,
        ]
    )
    info: dict[str, Any] = {
        "interface": interface,
        "connection": "",
        "type": "",
        "address": "",
        "prefix": "",
        "netmask": "",
        "gateway": "",
        "dns": [],
    }
    if not result["ok"]:
        return info
    dns_values = []
    for line in result["stdout"].splitlines():
        if line.startswith("GENERAL.CONNECTION:"):
            info["connection"] = line.split(":", 1)[1]
        elif line.startswith("GENERAL.TYPE:"):
            info["type"] = line.split(":", 1)[1]
        elif line.startswith("IP4.ADDRESS["):
            value = line.split(":", 1)[1]
            if "/" in value:
                address, prefix = value.split("/", 1)
                info["address"] = address
                info["prefix"] = prefix
                info["netmask"] = prefix_to_mask(prefix)
        elif line.startswith("IP4.GATEWAY:"):
            info["gateway"] = line.split(":", 1)[1]
        elif line.startswith("IP4.DNS["):
            dns = line.split(":", 1)[1]
            if dns:
                dns_values.append(dns)
    info["dns"] = dns_values
    return info


def get_interface_payload(interface: str) -> dict[str, Any]:
    details = get_network_info(interface)
    note_map = load_interface_notes()
    interface_item = next((item for item in get_interfaces() if item["device"] == interface), None)
    interface_type = interface_item["type"] if interface_item else details.get("type", "")
    default_note = default_interface_note(interface_type, interface)
    details["note"] = note_map.get(interface, "")
    details["default_note"] = default_note
    details["display_note"] = details["note"] or default_note
    return details


def parse_deepstream_sources(path: Path) -> list[dict[str, Any]]:
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    sources = []
    for section in parser.sections():
        if not re.fullmatch(r"source\d+", section):
            continue
        index = int(section.replace("source", ""))
        enable = parser.get(section, "enable", fallback="0").strip() == "1"
        uri = parser.get(section, "uri", fallback="").strip()
        source_type = parser.get(section, "type", fallback="").strip()
        sources.append({"index": index, "enable": enable, "uri": uri, "type": source_type})
    sources.sort(key=lambda item: item["index"])
    return sources


def update_deepstream_sources(path: Path, updates: list[dict[str, Any]]) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    by_index = {int(item["index"]): item for item in updates}
    current_section = None
    output = []
    for line in lines:
        section_match = re.match(r"\[(source(\d+))\]\s*$", line.strip())
        if section_match:
            current_section = int(section_match.group(2))
            output.append(line)
            continue
        if current_section in by_index:
            stripped = line.strip()
            update = by_index[current_section]
            if stripped.startswith("enable="):
                output.append(f"enable={'1' if update['enable'] else '0'}")
                continue
            if stripped.startswith("uri="):
                output.append(f"uri={update['uri']}")
                continue
        output.append(line)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def parse_rtsp_target(uri: str) -> tuple[str | None, int | None]:
    parsed = urlparse(uri)
    if not parsed.scheme.lower().startswith("rtsp"):
        return None, None
    return parsed.hostname, parsed.port or 554


def parse_rtsp_details(uri: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    if not parsed.scheme.lower().startswith("rtsp"):
        return {
            "host": "",
            "port": 554,
            "username": "",
            "password": "",
            "path": "/ch1/main",
        }
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return {
        "host": parsed.hostname or "",
        "port": parsed.port or 554,
        "username": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "path": path,
    }


def normalize_rtsp_credential(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    # Accept either raw credentials like Htgx@8888 or already-encoded text like Htgx%408888.
    decoded = unquote(text)
    return decoded


def generate_rtsp_uri(host: str, username: str, password: str, port: int, path: str) -> str:
    safe_host = host.strip()
    safe_user = quote(normalize_rtsp_credential(username), safe="")
    safe_password = quote(normalize_rtsp_credential(password), safe="")
    safe_path = path.strip() or "/"
    if not safe_path.startswith("/"):
        safe_path = "/" + safe_path
    auth = ""
    if safe_user:
        auth = safe_user
        if password.strip():
            auth += f":{safe_password}"
        auth += "@"
    netloc = f"{auth}{safe_host}"
    if port and port != 554:
        netloc += f":{port}"
    return urlunparse(("rtsp", netloc, safe_path, "", "", ""))


def replace_uri_host(uri: str, host: str) -> str:
    parsed = urlparse(uri)
    if not parsed.scheme:
        return uri
    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"
    netloc = f"{auth}{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def check_rtsp_connectivity(uri: str) -> dict[str, Any]:
    host, port = parse_rtsp_target(uri)
    if not host:
        return {"uri": uri, "ok": False, "message": "URI 格式无效"}
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect((host, port))
        return {"uri": uri, "ok": True, "message": f"{host}:{port} 可连接"}
    except Exception as exc:
        return {"uri": uri, "ok": False, "message": f"{host}:{port} 连接失败: {exc}"}
    finally:
        sock.close()


def ping_host(host: str, count: int = 1) -> dict[str, Any]:
    if not host:
        return {"ok": False, "message": "未提供主机地址"}
    cmd = ["ping", "-c", str(count), "-W", "1", host]
    result = run_command(cmd, require_root=False, timeout=max(5, count * 2))
    if result["ok"]:
        return {"ok": True, "message": f"{host} 连通正常"}
    return {"ok": False, "message": f"{host} 连通失败"}


def tcp_check(host: str, port: int, timeout_sec: float = 2.0) -> dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_sec)
    try:
        sock.connect((host, port))
        return {"ok": True, "message": f"{host}:{port} 可连接"}
    except Exception as exc:
        return {"ok": False, "message": f"{host}:{port} 连接失败: {exc}"}
    finally:
        sock.close()


_SIGNAL_CHECK_CACHE: tuple[float, str, int, dict[str, Any], dict[str, Any]] | None = None
SIGNAL_CHECK_CACHE_SECONDS = 5.0


def get_signal_checks(host: str, port: int, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    global _SIGNAL_CHECK_CACHE
    now = time.monotonic()
    if not force and _SIGNAL_CHECK_CACHE:
        cached_at, cached_host, cached_port, cached_ping, cached_tcp = _SIGNAL_CHECK_CACHE
        if cached_host == host and cached_port == port and now - cached_at < SIGNAL_CHECK_CACHE_SECONDS:
            return dict(cached_ping), dict(cached_tcp)
    ping_result = ping_host(host, count=1)
    tcp_result = tcp_check(host, port, timeout_sec=0.8)
    _SIGNAL_CHECK_CACHE = (now, host, port, ping_result, tcp_result)
    return ping_result, tcp_result


def load_camera_aliases() -> dict[str, str]:
    if not CAMERA_BINDINGS_PATH.exists():
        return {}
    try:
        data = json.loads(CAMERA_BINDINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict):
        return {}
    return {str(k): str(v) for k, v in aliases.items()}


def save_camera_aliases(aliases: dict[str, str]) -> None:
    CAMERA_BINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "aliases": aliases,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    CAMERA_BINDINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_camera_bindings() -> list[dict[str, Any]]:
    aliases = load_camera_aliases()
    cameras = []
    for source in parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH):
        details = parse_rtsp_details(source["uri"])
        source_key = str(source["index"])
        cameras.append(
            {
                "index": source["index"],
                "name": aliases.get(source_key, f"CAM_{source['index']:02d}"),
                "host": details["host"],
                "port": details["port"],
                "username": details["username"],
                "password": details["password"],
                "path": details["path"],
                "uri": source["uri"],
                "enable": source["enable"],
            }
        )
    return cameras


def save_camera_bindings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_sources = {item["index"]: item for item in parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH)}
    aliases = load_camera_aliases()
    updates = []
    for item in items:
        idx = int(item["index"])
        current = current_sources[idx]
        uri = str(item.get("uri", current["uri"])).strip()
        host = str(item.get("host", "")).strip()
        username = str(item.get("username", "")).strip()
        password = str(item.get("password", "")).strip()
        path = str(item.get("path", "")).strip()
        port_raw = item.get("port", 554)
        if host:
            ensure_ipv4(host, f"source{idx}.host")
        try:
            port = int(port_raw or 554)
        except (TypeError, ValueError):
            raise ValueError(f"source{idx}.port 必须是数字")
        if host:
            uri = generate_rtsp_uri(host, username, password, port, path)
        updates.append({"index": idx, "enable": bool(item.get("enable", current["enable"])), "uri": uri})
        aliases[str(idx)] = str(item.get("name", aliases.get(str(idx), f"CAM_{idx:02d}"))).strip() or f"CAM_{idx:02d}"
    update_deepstream_sources(DEEPSTREAM_CONFIG_PATH, updates)
    save_camera_aliases(aliases)
    return build_camera_bindings()


def latest_csv_file(prefix: str) -> Path | None:
    files = [path for path in TRAFFIC_QUEUE_DIR.glob(f"{prefix}_*.csv") if ".bak" not in path.name]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def read_latest_csv_summary(prefix: str) -> dict[str, Any]:
    path = latest_csv_file(prefix)
    if path is None:
        return {"file": None, "updated_at": None, "top": []}
    last_row = None
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            last_row = row
    if not last_row:
        return {"file": str(path), "updated_at": None, "top": []}
    metrics = []
    for key, value in last_row.items():
        if not key.startswith("lane_"):
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        metrics.append({"lane": key.replace("lane_", ""), "value": round(num, 2)})
    def lane_sort_key(item: dict[str, Any]) -> tuple[int, Any]:
        lane = str(item["lane"])
        return (0, int(lane)) if lane.isdigit() else (1, lane)

    metrics.sort(key=lane_sort_key)
    return {
        "file": str(path),
        "updated_at": last_row.get("dateTime"),
        "top": metrics,
        "count": len(metrics),
    }


def read_recent_log_events(limit: int = 12) -> list[str]:
    path = TRAFFIC_LOG_DIR / "runtime_main.log"
    if not path.exists():
        return []
    lines: deque[str] = deque(maxlen=200)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            lines.append(line.rstrip())
    interesting = [
        line
        for line in lines
        if "[ERROR]" in line or "Traceback" in line or "NameError" in line or "[WARNING]" in line
    ]
    return interesting[-limit:]


def get_calibration_status() -> list[dict[str, Any]]:
    items = []
    for name, path in CALIBRATION_FILES.items():
        exists = path.exists()
        stat = path.stat() if exists else None
        items.append(
            {
                "name": name,
                "path": str(path),
                "exists": exists,
                "size": stat.st_size if stat else 0,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)) if stat else None,
            }
        )
    return items


def runtime_summary() -> dict[str, Any]:
    active_interface = get_active_interface()
    current_network = get_network_info(active_interface) if active_interface else {}
    signal_config = get_signal_controller_config()
    signal_ping, signal_tcp = get_signal_checks(signal_config["host"], signal_config["port"])
    return {
        "hostname": get_hostname(),
        "active_interface": active_interface,
        "current_network": current_network,
        "services": [service_status(name) for name in SERVICES],
        "signal_controller": {
            "host": signal_config["host"],
            "port": signal_config["port"],
            "ping": signal_ping,
            "tcp": signal_tcp,
        },
        "metrics": {
            "flow": read_latest_csv_summary("flow"),
            "headway": read_latest_csv_summary("headway"),
            "queue": read_latest_csv_summary("queueLen"),
        },
        "recent_events": read_recent_log_events(),
        "calibration": get_calibration_status(),
    }


@app.get("/")
def index():
    signal_config = get_signal_controller_config()
    return render_template(
        "index.html",
        signal_host=signal_config["host"],
        signal_port=signal_config["port"],
        services=SERVICES,
    )


@app.get("/api/status")
def api_status():
    active_interface = get_active_interface()
    current_network = get_network_info(active_interface) if active_interface else {}
    return jsonify(
        {
            "ok": True,
            "hostname": get_hostname(),
            "active_interface": active_interface,
            "interfaces": get_interfaces(),
            "current_network": current_network,
            "services": [service_status(name) for name in SERVICES],
        }
    )


@app.get("/api/interfaces/<path:interface>")
def api_interface_detail(interface: str):
    return jsonify({"ok": True, "interface": get_interface_payload(interface)})


@app.post("/api/network")
def api_network():
    body = request.get_json(force=True)
    interface = str(body.get("interface", "")).strip()
    address = str(body.get("address", "")).strip()
    netmask = str(body.get("netmask", "")).strip()
    gateway = str(body.get("gateway", "")).strip()
    dns_text = str(body.get("dns", "")).strip()
    note = str(body.get("note", "")).strip()
    if not interface:
        return jsonify({"ok": False, "message": "未选择网卡"}), 400
    ensure_ipv4(address, "IP")
    ensure_ipv4(netmask, "子网掩码")
    ensure_ipv4(gateway, "网关")
    prefix = mask_to_prefix(netmask)

    connection_name = ""
    for item in get_interfaces():
        if item["device"] == interface:
            connection_name = item["connection"]
            break
    if not connection_name:
        return jsonify({"ok": False, "message": f"未找到网卡 {interface} 对应连接"}), 400

    dns_list = [part for part in dns_text.split() if part]
    for dns in dns_list:
        ensure_ipv4(dns, "DNS")

    modify_cmd = [
        "nmcli",
        "connection",
        "modify",
        connection_name,
        "connection.interface-name",
        interface,
        "ipv4.method",
        "manual",
        "ipv4.addresses",
        f"{address}/{prefix}",
        "ipv4.gateway",
        gateway,
        "connection.autoconnect",
        "yes",
    ]
    if dns_list:
        modify_cmd += ["ipv4.dns", " ".join(dns_list)]
    else:
        modify_cmd += ["ipv4.dns", ""]

    modify_result = run_command(modify_cmd, require_root=True, timeout=30)
    if not modify_result["ok"]:
        return jsonify({"ok": False, "message": modify_result["stderr"] or modify_result["stdout"] or "修改网络失败"}), 500

    up_result = run_command(["nmcli", "connection", "up", connection_name], require_root=True, timeout=30)
    if not up_result["ok"]:
        return jsonify({"ok": False, "message": up_result["stderr"] or up_result["stdout"] or "应用网络失败"}), 500

    notes = load_interface_notes()
    notes[interface] = note
    save_interface_notes(notes)

    message = f"网络配置已应用：{interface} -> {address}/{prefix}，网关 {gateway}"
    log_line(f"[NETWORK] {message}")
    return jsonify({"ok": True, "message": message})


@app.get("/api/video-sources")
def api_video_sources():
    return jsonify({"ok": True, "sources": parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH)})


@app.post("/api/video-sources")
def api_video_sources_save():
    body = request.get_json(force=True)
    sources = body.get("sources")
    if not isinstance(sources, list):
        return jsonify({"ok": False, "message": "sources 必须是数组"}), 400
    for item in sources:
        if not isinstance(item, dict):
            return jsonify({"ok": False, "message": "source 项格式错误"}), 400
        uri = str(item.get("uri", "")).strip()
        if item.get("enable") and not uri:
            return jsonify({"ok": False, "message": f"source{item.get('index')} 启用时 RTSP 不能为空"}), 400
    update_deepstream_sources(DEEPSTREAM_CONFIG_PATH, sources)
    log_line(f"[VIDEO] 已保存视频源配置到 {DEEPSTREAM_CONFIG_PATH}")
    return jsonify({"ok": True, "message": f"视频源配置已保存到 {DEEPSTREAM_CONFIG_PATH}"})


@app.post("/api/video-sources/check")
def api_video_sources_check():
    sources = parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH)
    results = []
    for item in sources:
        if not item["enable"]:
            results.append({"source": item["index"], "ok": True, "message": "未启用，跳过检查"})
            continue
        check = check_rtsp_connectivity(item["uri"])
        results.append({"source": item["index"], **check})
    return jsonify({"ok": True, "results": results})


@app.get("/api/camera-bindings")
def api_camera_bindings():
    return jsonify({"ok": True, "items": build_camera_bindings()})


@app.post("/api/camera-bindings")
def api_camera_bindings_save():
    body = request.get_json(force=True)
    items = body.get("items")
    if not isinstance(items, list):
        return jsonify({"ok": False, "message": "items 必须是数组"}), 400
    try:
        cameras = save_camera_bindings(items)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    log_line("[CAMERA] 已更新相机绑定配置")
    return jsonify({"ok": True, "message": "相机绑定已保存", "items": cameras})


@app.post("/api/camera-bindings/check")
def api_camera_bindings_check():
    items = build_camera_bindings()
    results = []
    for item in items:
        if not item["enable"]:
            results.append({"index": item["index"], "ok": True, "message": "未启用，已跳过"})
            continue
        result = tcp_check(item["host"], item["port"] or 554)
        results.append({"index": item["index"], "name": item["name"], "host": item["host"], **result})
    return jsonify({"ok": True, "results": results})


@app.get("/api/calibration-status")
def api_calibration_status():
    return jsonify({"ok": True, "items": get_calibration_status()})


@app.get("/api/runtime-summary")
def api_runtime_summary():
    return jsonify({"ok": True, "summary": runtime_summary()})


@app.get("/api/signal-controller")
def api_signal_controller():
    return jsonify({"ok": True, "signal_controller": get_signal_controller_config()})


@app.post("/api/signal-controller/check")
def api_signal_controller_check():
    body = request.get_json(silent=True) or {}
    current = get_signal_controller_config()
    host = str(body.get("host", current["host"])).strip()
    port_raw = body.get("port", current["port"])
    try:
        ensure_ipv4(host, "信号机 IP")
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "信号机端口必须是数字"}), 400
    if not (1 <= port <= 65535):
        return jsonify({"ok": False, "message": "信号机端口超出范围"}), 400
    signal_ping, signal_tcp = get_signal_checks(host, port, force=True)
    both_ok = bool(signal_ping.get("ok") and signal_tcp.get("ok"))
    return jsonify(
        {
            "ok": True,
            "message": "信号机检查正常" if both_ok else "信号机检查完成：存在不通项",
            "signal_controller": {
                "host": host,
                "port": port,
                "ping": signal_ping,
                "tcp": signal_tcp,
            },
        }
    )


@app.post("/api/signal-controller")
def api_signal_controller_save():
    body = request.get_json(force=True)
    host = str(body.get("host", "")).strip()
    port_raw = body.get("port", DEFAULT_SIGNAL_CONTROLLER_PORT)
    try:
        ensure_ipv4(host, "信号机 IP")
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "信号机端口必须是数字"}), 400
    if not (1 <= port <= 65535):
        return jsonify({"ok": False, "message": "信号机端口超出范围"}), 400

    runtime_env = load_runtime_env()
    runtime_env["GB_TSC_IP"] = host
    runtime_env["GB_TSC_PORT"] = str(port)
    save_runtime_env(runtime_env)

    restart_result = run_command(["systemctl", "restart", "traffic_detect.service"], require_root=True, timeout=40)
    if not restart_result["ok"]:
        return jsonify({"ok": False, "message": restart_result["stderr"] or restart_result["stdout"] or "已保存，但自动重启路口感知检测服务失败"}), 500

    log_line(f"[SIGNAL] 已更新信号机配置 {host}:{port}，并重启 traffic_detect.service")
    signal_config = get_signal_controller_config()
    signal_ping, signal_tcp = get_signal_checks(signal_config["host"], signal_config["port"])
    return jsonify(
        {
            "ok": True,
            "message": f"信号机配置已保存，路口感知检测服务已自动重启：{host}:{port}",
            "signal_controller": {
                "host": signal_config["host"],
                "port": signal_config["port"],
                "ping": signal_ping,
                "tcp": signal_tcp,
            },
        }
    )


@app.post("/api/services/<path:name>/<action>")
def api_service_action(name: str, action: str):
    if name not in SERVICES:
        return jsonify({"ok": False, "message": f"不允许操作的服务: {name}"}), 400
    if action not in {"start", "restart", "status", "stop", "enable", "disable"}:
        return jsonify({"ok": False, "message": f"不支持的动作: {action}"}), 400
    if action == "status":
        return jsonify({"ok": True, "message": "状态已刷新", "service": service_status(name, use_cache=False)})

    systemctl_action = action
    result = run_command(["systemctl", systemctl_action, name], require_root=True, timeout=30)
    if not result["ok"]:
        action_error = {
            "start": "启动失败",
            "restart": "重启失败",
            "stop": "暂停失败",
            "enable": "开启重启自动启动失败",
            "disable": "关闭重启自动启动失败",
        }
        default_message = action_error.get(action, "操作失败")
        return jsonify({"ok": False, "message": result["stderr"] or result["stdout"] or default_message}), 500
    log_line(f"[SERVICE] {systemctl_action} {name}")
    _SERVICE_STATUS_CACHE.pop(name, None)
    action_text = {
        "start": "已启动",
        "restart": "已重启",
        "stop": "已暂停",
        "enable": "已开启重启自动启动",
        "disable": "已关闭重启自动启动",
    }.get(action, "已完成")
    return jsonify({"ok": True, "message": f"{service_display_name(name)}{action_text}"})


@app.post("/api/checks")
def api_checks():
    summary = runtime_summary()
    cameras = build_camera_bindings()
    camera_checks = []
    for item in cameras:
        if not item["enable"]:
            camera_checks.append({"index": item["index"], "ok": True, "message": "未启用，跳过检查"})
            continue
        camera_checks.append({"index": item["index"], **ping_host(item["host"], count=1)})
    results = {
        "runtime": summary,
        "cameras": camera_checks,
        "video_sources": parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH),
    }
    return jsonify({"ok": True, "results": results})


if __name__ == "__main__":
    app.run(host=WEB_HOST, port=WEB_PORT, threaded=True)
