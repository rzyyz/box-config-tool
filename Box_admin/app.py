import configparser
import csv
import http.cookiejar
import ipaddress
import json
import os
import re
import shutil
import shlex
import socket
import subprocess
import time
import uuid
from io import StringIO
from collections import deque
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import quote, unquote, urlencode, urlparse, urlunparse

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
STEP_TOOL_BASE_URL = os.getenv("BOX_ADMIN_STEP_TOOL_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
STEP_TOOL_TIMEOUT = float(os.getenv("BOX_ADMIN_STEP_TOOL_TIMEOUT", "5"))
STEP_TOOL_CSRF_PATH = os.getenv("BOX_ADMIN_STEP_TOOL_CSRF_PATH", "/login")
STEP_TOOL_LOGIN_USERNAME = os.getenv("BOX_ADMIN_STEP_TOOL_LOGIN_USERNAME", "admin")
STEP_TOOL_LOGIN_PASSWORD = os.getenv("BOX_ADMIN_STEP_TOOL_LOGIN_PASSWORD", "admin123")
CTRL_MODE_LABELS = {
    0: "本地时段控制",
    1: "关灯控制",
    2: "黄闪控制",
    3: "全红控制",
    4: "定周期控制",
    5: "协调绿波控制",
    6: "协议红波控制",
    7: "全感应控制",
    8: "半感应控制",
    9: "协调绿波全感应控制",
    10: "步进控制",
    12: "行人过街控制",
    13: "单点自适应控制",
    14: "静态干线控制",
    15: "动态干线控制",
    16: "区域优化控制",
    17: "单点优化控制",
    18: "公交优先控制",
}


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


def find_deepstream_source_blocks(lines: list[str]) -> list[tuple[int, int, int]]:
    blocks = []
    index = 0
    section_pattern = re.compile(r"\[[^\]]+\]\s*$")
    source_pattern = re.compile(r"\[source(\d+)\]\s*$")
    while index < len(lines):
        match = source_pattern.match(lines[index].strip())
        if not match:
            index += 1
            continue
        source_index = int(match.group(1))
        start = index
        index += 1
        while index < len(lines) and not section_pattern.match(lines[index].strip()):
            index += 1
        blocks.append((source_index, start, index))
    return blocks


def set_source_block_value(block: list[str], key: str, value: str) -> list[str]:
    key_prefix = f"{key}="
    output = []
    replaced = False
    for line in block:
        if not replaced and line.strip().startswith(key_prefix):
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if replaced:
        return output
    insert_at = len(output)
    while insert_at > 1 and output[insert_at - 1].strip() == "":
        insert_at -= 1
    output.insert(insert_at, f"{key}={value}")
    return output


def build_deepstream_source_block(template: list[str], index: int, update: dict[str, Any]) -> list[str]:
    if template:
        block = list(template)
        block[0] = f"[source{index}]"
    else:
        block = [
            f"[source{index}]",
            "enable=1",
            "type=2",
            "uri=",
            "num-sources=1",
            "gpu-id=0",
            "cudadec-memtype=2",
            "",
        ]
    block = set_source_block_value(block, "enable", "1" if update["enable"] else "0")
    block = set_source_block_value(block, "uri", str(update["uri"]))
    if block and block[-1].strip():
        block.append("")
    return block


def update_deepstream_sources(path: Path, updates: list[dict[str, Any]]) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    by_index = {int(item["index"]): item for item in updates}
    blocks = find_deepstream_source_blocks(lines)
    existing_indices = {index for index, _start, _end in blocks}
    current_section = None
    output = []
    section_pattern = re.compile(r"\[([^\]]+)\]\s*$")
    source_pattern = re.compile(r"source(\d+)$")
    for line in lines:
        section_match = section_pattern.match(line.strip())
        if section_match:
            source_match = source_pattern.fullmatch(section_match.group(1))
            current_section = int(source_match.group(1)) if source_match else None
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
    new_indices = sorted(index for index in by_index if index not in existing_indices)
    if new_indices:
        updated_blocks = find_deepstream_source_blocks(output)
        if updated_blocks:
            _template_index, template_start, template_end = updated_blocks[-1]
            template = output[template_start:template_end]
            insert_at = template_end
        else:
            template = []
            insert_at = len(output)
        new_lines = []
        for index in new_indices:
            if index < 0:
                raise ValueError("source id 不能为负数")
            new_lines.extend(build_deepstream_source_block(template, index, by_index[index]))
        output[insert_at:insert_at] = new_lines
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def delete_deepstream_source(path: Path, index: int) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sources = {item["index"]: item for item in parse_deepstream_sources(path)}
    if index not in sources:
        raise ValueError(f"source{index} 不存在")
    for source_index, start, end in find_deepstream_source_blocks(lines):
        if source_index != index:
            continue
        del lines[start:end]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return sources[index]
    raise ValueError(f"source{index} 不存在")


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


def sanitize_rtsp_error_message(message: str, uri: str) -> str:
    text = message or ""
    if uri:
        text = text.replace(uri, "[RTSP地址]")
    parsed = urlparse(uri)
    if parsed.username and parsed.hostname:
        auth_host = f"{parsed.username}"
        if parsed.password:
            auth_host += f":{parsed.password}"
        auth_host += f"@{parsed.hostname}"
        text = text.replace(auth_host, f"***@{parsed.hostname}")
    return text


def classify_rtsp_error(message: str) -> tuple[str, str]:
    text = (message or "").lower()
    if any(key in text for key in ["unauthorized", "401", "authentication", "not authorized", "permission denied"]):
        return "auth_failed", "RTSP 认证失败，请检查相机账号或密码"
    if any(key in text for key in ["404", "not found", "not-found"]):
        return "path_failed", "RTSP 路径不存在，请检查视频流路径"
    if any(key in text for key in ["timeout", "timed out", "connection timed out"]):
        return "timeout", "视频流拉流超时，请检查网络、相机负载或 RTSP 地址"
    if any(key in text for key in ["connection refused", "could not connect", "no route to host", "network is unreachable"]):
        return "connect_failed", "无法连接相机视频流端口，请检查相机网络或端口"
    if any(key in text for key in ["could not open resource", "open resource"]):
        return "open_failed", "无法打开 RTSP 视频流，请检查地址、账号、密码或路径"
    if "not-linked" in text:
        return "no_video", "已连接到 RTSP，但未识别到视频流"
    return "stream_failed", "视频流拉流失败，请检查账号、密码、路径和相机状态"


def gst_output_confirms_stream(message: str) -> bool:
    text = (message or "").lower()
    success_markers = [
        "setting pipeline to playing",
        "new clock",
        "stream-start",
        "gstmessage-stream-start",
        "async-done",
        "pipeline is live and does not need preroll",
        "pipeline is prerolled",
        "redistribute latency",
    ]
    return any(marker in text for marker in success_markers)


def check_rtsp_stream(uri: str, timeout: int = 8) -> dict[str, Any]:
    if not uri:
        return {"ok": False, "reason": "empty_uri", "message": "RTSP 地址为空"}
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
        return {"ok": False, "reason": "invalid_uri", "message": "RTSP 地址格式无效"}

    tcp_result = tcp_check(parsed.hostname, parsed.port or 554, timeout_sec=2.0)
    if not tcp_result["ok"]:
        return {
            "ok": False,
            "reason": "connect_failed",
            "message": f"RTSP 端口不可达：{tcp_result['message']}",
        }

    gst_launch = shutil.which("gst-launch-1.0")
    if not gst_launch:
        return {"ok": False, "reason": "missing_tool", "message": "缺少 gst-launch-1.0，无法按 DeepStream/GStreamer 链路验证拉流"}

    cmd = [
        gst_launch,
        "-m",
        "rtspsrc",
        f"location={uri}",
        "protocols=tcp",
        "latency=200",
        "timeout=5000000",
        "!",
        "application/x-rtp,media=video",
        "!",
        "fakesink",
        "sync=false",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        raw_output = (result.stderr or "") + "\n" + (result.stdout or "")
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        raw_output = f"{stderr}\n{stdout}"
        if gst_output_confirms_stream(raw_output):
            return {"ok": True, "reason": "stream_ok", "message": "GStreamer 已进入播放状态，视频流可用"}
        raw_message = sanitize_rtsp_error_message(raw_output.strip() or "GStreamer 未确认收到视频流", uri)
        detail = raw_message[:200]
        message = "视频流拉流超时，未确认进入播放或收到视频流"
        if detail:
            message = f"{message}；详情：{detail}"
        return {"ok": False, "reason": "timeout", "message": message[:260]}
    if result.returncode == 0 and gst_output_confirms_stream(raw_output):
        return {"ok": True, "reason": "stream_ok", "message": "GStreamer 拉流正常"}
    if result.returncode == 0:
        raw_message = sanitize_rtsp_error_message(raw_output.strip() or "GStreamer 未确认收到视频流", uri)
        detail = raw_message[:200]
        message = "GStreamer 退出但未确认进入播放或收到视频流"
        if detail:
            message = f"{message}；详情：{detail}"
        return {"ok": False, "reason": "no_video", "message": message[:260]}
    raw_message = sanitize_rtsp_error_message((raw_output or "GStreamer 拉流失败").strip(), uri)
    reason, friendly_message = classify_rtsp_error(raw_message)
    detail = raw_message[:200]
    if detail and detail != friendly_message:
        friendly_message = f"{friendly_message}；详情：{detail}"
    return {"ok": False, "reason": reason, "message": friendly_message[:260]}


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


def step_tool_csrf_opener() -> tuple[urlrequest.OpenerDirector, str, str]:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urlrequest.build_opener(urlrequest.HTTPCookieProcessor(cookie_jar))
    login_url = f"{STEP_TOOL_BASE_URL}{STEP_TOOL_CSRF_PATH}"
    try:
        with opener.open(login_url, timeout=STEP_TOOL_TIMEOUT) as response:
            html = response.read().decode("utf-8", errors="replace")
            final_url = response.geturl()
    except Exception as exc:
        raise RuntimeError(f"无法获取智能控制安全令牌：{exc}") from exc
    match = re.search(r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)["\']', html)
    if not match:
        match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']_csrf["\']', html)
    if not match:
        raise RuntimeError("智能控制未返回安全令牌，请确认服务登录页是否正常")
    return opener, match.group(1), final_url or login_url


def step_tool_login_session() -> tuple[urlrequest.OpenerDirector, str, str]:
    opener, csrf_token, login_url = step_tool_csrf_opener()
    payload = urlencode(
        {
            "username": STEP_TOOL_LOGIN_USERNAME,
            "password": STEP_TOOL_LOGIN_PASSWORD,
            "_csrf": csrf_token,
        }
    ).encode("utf-8")
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": step_tool_origin(),
        "Referer": login_url,
        "User-Agent": "box-config-tool/1.0",
    }
    req = urlrequest.Request(login_url, data=payload, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=STEP_TOOL_TIMEOUT) as response:
            html = response.read().decode("utf-8", errors="replace")
            final_url = response.geturl()
    except urlerror.URLError as exc:
        raise RuntimeError(f"无法登录智能控制平台：{exc}") from exc
    except TimeoutError as exc:
        raise RuntimeError("登录智能控制平台超时") from exc
    if final_url.rstrip("/").endswith("/login"):
        raise RuntimeError(
            f"智能控制平台网页登录失败，请检查固定账号密码是否仍为 {STEP_TOOL_LOGIN_USERNAME}/{STEP_TOOL_LOGIN_PASSWORD}"
        )
    match = re.search(r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)["\']', html)
    if not match:
        match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']_csrf["\']', html)
    session_csrf = match.group(1) if match else csrf_token
    return opener, session_csrf, final_url or login_url


def step_tool_origin() -> str:
    parsed = urlparse(STEP_TOOL_BASE_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def step_tool_headers(csrf_token: str | None = None, referer: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "box-config-tool/1.0",
    }
    if csrf_token:
        headers.update(
            {
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Origin": step_tool_origin(),
                "Referer": referer or f"{STEP_TOOL_BASE_URL}{STEP_TOOL_CSRF_PATH}",
            }
        )
    return headers


def step_tool_decode_json(raw: str, final_url: str) -> dict[str, Any]:
    if final_url.rstrip("/").endswith("/login"):
        raise RuntimeError("智能控制要求安全令牌或登录态，当前请求被重定向到登录页")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("智能控制返回内容不是有效 JSON") from exc
    if result.get("code") != 200:
        raise RuntimeError(str(result.get("message") or "智能控制接口返回失败"))
    return result


def step_tool_request(
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    session: tuple[urlrequest.OpenerDirector, str, str] | None = None,
) -> dict[str, Any]:
    url = f"{STEP_TOOL_BASE_URL}{path}"
    headers = step_tool_headers()
    data = None
    if session is None:
        opener, csrf_token, referer = step_tool_login_session()
    else:
        opener, csrf_token, referer = session
    if method.upper() not in ("GET", "HEAD"):
        headers = step_tool_headers(csrf_token=csrf_token, referer=referer)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=STEP_TOOL_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            final_url = response.geturl()
    except urlerror.URLError as exc:
        raise RuntimeError(f"无法连接智能控制服务：{exc}") from exc
    except TimeoutError as exc:
        raise RuntimeError("连接智能控制服务超时") from exc
    return step_tool_decode_json(raw, final_url)


def step_tool_upload(path: str, filename: str, content: bytes, mimetype: str) -> dict[str, Any]:
    url = f"{STEP_TOOL_BASE_URL}{path}"
    opener, csrf_token, referer = step_tool_login_session()
    boundary = f"----box-config-tool-{uuid.uuid4().hex}"
    safe_filename = Path(filename or "config.json").name.replace('"', "")
    content_type = mimetype or "application/octet-stream"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="file"; filename="{safe_filename}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    req = urlrequest.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            **step_tool_headers(csrf_token=csrf_token, referer=referer),
        },
        method="POST",
    )
    try:
        with opener.open(req, timeout=STEP_TOOL_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            final_url = response.geturl()
    except urlerror.URLError as exc:
        raise RuntimeError(f"无法连接智能控制服务：{exc}") from exc
    except TimeoutError as exc:
        raise RuntimeError("连接智能控制服务超时") from exc
    return step_tool_decode_json(raw, final_url)


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


def camera_check_items_from_request() -> list[dict[str, Any]]:
    body = request.get_json(silent=True) or {}
    raw_items = body.get("items")
    if not isinstance(raw_items, list):
        return build_camera_bindings()

    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("index", len(items)))
        except (TypeError, ValueError):
            index = len(items)
        host = str(raw.get("host", "")).strip()
        username = str(raw.get("username", "")).strip()
        password = str(raw.get("password", "")).strip()
        path = str(raw.get("path", "/ch1/main")).strip() or "/ch1/main"
        try:
            port = int(raw.get("port", 554) or 554)
        except (TypeError, ValueError):
            port = 554
        uri = str(raw.get("uri", "")).strip()
        if not uri and host:
            uri = generate_rtsp_uri(host, username, password, port, path)
        if not host and uri:
            parsed_host, parsed_port = parse_rtsp_target(uri)
            host = parsed_host
            port = parsed_port
        items.append(
            {
                "index": index,
                "name": str(raw.get("name", f"CAM_{index:02d}")),
                "enable": bool(raw.get("enable", True)),
                "host": host,
                "port": port,
                "uri": uri,
            }
        )
    return items


def save_camera_bindings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_sources = {item["index"]: item for item in parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH)}
    aliases = load_camera_aliases()
    updates = []
    seen_indices = set()
    for item in items:
        idx = int(item["index"])
        if idx < 0:
            raise ValueError("source id 不能为负数")
        if idx in seen_indices:
            raise ValueError(f"source{idx} 重复，请刷新页面后重试")
        seen_indices.add(idx)
        current = current_sources.get(idx)
        default_enable = current["enable"] if current else True
        default_uri = current["uri"] if current else ""
        uri = str(item.get("uri", default_uri)).strip()
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
        enable = bool(item.get("enable", default_enable))
        if enable and not uri:
            raise ValueError(f"source{idx} 启用时 RTSP 不能为空")
        updates.append({"index": idx, "enable": enable, "uri": uri})
        aliases[str(idx)] = str(item.get("name", aliases.get(str(idx), f"CAM_{idx:02d}"))).strip() or f"CAM_{idx:02d}"
    update_deepstream_sources(DEEPSTREAM_CONFIG_PATH, updates)
    save_camera_aliases(aliases)
    return build_camera_bindings()


def latest_csv_file(prefix: str) -> Path | None:
    files = [path for path in TRAFFIC_QUEUE_DIR.glob(f"{prefix}_*.csv") if ".bak" not in path.name]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def lane_sort_key(lane: str) -> tuple[int, Any]:
    lane_text = str(lane)
    return (0, int(lane_text)) if lane_text.isdigit() else (1, lane_text)


def read_csv_tail_rows(path: Path, max_lines: int = 12) -> tuple[str, list[str]]:
    with path.open("rb") as handle:
        header = handle.readline().decode("utf-8", errors="ignore").strip()
        handle.seek(0, os.SEEK_END)
        pos = handle.tell()
        tail = b""
        block_size = 8192
        while pos > 0 and tail.count(b"\n") <= max_lines:
            read_size = min(block_size, pos)
            pos -= read_size
            handle.seek(pos)
            tail = handle.read(read_size) + tail
    rows = [line for line in tail.decode("utf-8", errors="ignore").splitlines() if line.strip()]
    if rows and rows[0].strip() == header:
        rows = rows[1:]
    return header, rows[-max_lines:]


def read_latest_csv_summary(prefix: str) -> dict[str, Any]:
    path = latest_csv_file(prefix)
    if path is None:
        return {"file": None, "updated_at": None, "top": []}
    try:
        header, data_lines = read_csv_tail_rows(path, max_lines=8)
        if not data_lines:
            return {"file": str(path), "updated_at": None, "top": []}
        reader = csv.DictReader(StringIO(header + "\n" + data_lines[-1] + "\n"))
        last_row = next(reader, None)
    except Exception as exc:
        return {"file": str(path), "updated_at": None, "top": [], "error": str(exc)}
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


def load_base_length_summary() -> dict[str, float]:
    path = CALIBRATION_FILES.get("base_length")
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in payload.items():
        try:
            result[str(key)] = round(float(value), 2)
        except (TypeError, ValueError):
            continue
    return result


def read_metric_series(prefix: str, minutes: int, aggregate_mode: str = "avg") -> dict[str, Any]:
    safe_minutes = max(1, min(int(minutes or 30), 180))
    path = latest_csv_file(prefix)
    empty = {
        "file": str(path) if path else None,
        "minutes": safe_minutes,
        "lanes": [],
        "series": {},
        "rows": 0,
        "updated_at": None,
        "latest_by_lane": {},
        "peak_by_lane": {},
        "avg_by_lane": {},
        "total_by_lane": {},
    }
    if path is None:
        return empty
    max_lines = min(max(int(safe_minutes * 65) + 60, 800), 120000)
    try:
        header, data_lines = read_csv_tail_rows(path, max_lines=max_lines)
        if not data_lines:
            return empty
        reader = csv.DictReader(StringIO(header + "\n" + "\n".join(data_lines) + "\n"))
        rows = list(reader)
        latest_ts = None
        latest_dt = None
        for row in reversed(rows):
            try:
                latest_ts = float(row.get("ts", ""))
                latest_dt = row.get("dateTime")
                break
            except (TypeError, ValueError):
                continue
        if latest_ts is None:
            return empty
        start_ts = latest_ts - safe_minutes * 60
        series_by_lane: dict[str, list[dict[str, Any]]] = {}
        used_rows = 0
        for row in rows:
            try:
                row_ts = float(row.get("ts", ""))
            except (TypeError, ValueError):
                continue
            if row_ts < start_ts:
                continue
            used_rows += 1
            row_label = str(row.get("dateTime") or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row_ts)))
            for key, value in row.items():
                if not key.startswith("lane_"):
                    continue
                lane = key.replace("lane_", "")
                try:
                    metric_value = round(float(value or 0.0), 2)
                except (TypeError, ValueError):
                    continue
                series_by_lane.setdefault(lane, []).append(
                    {
                        "ts": round(row_ts, 3),
                        "label": row_label,
                        "value": metric_value,
                    }
                )
        lanes = sorted(series_by_lane.keys(), key=lane_sort_key)
        latest_by_lane: dict[str, float] = {}
        peak_by_lane: dict[str, float] = {}
        avg_by_lane: dict[str, float] = {}
        total_by_lane: dict[str, float] = {}
        for lane in lanes:
            lane_values = [float(item["value"]) for item in series_by_lane[lane]]
            if not lane_values:
                continue
            latest_by_lane[lane] = round(lane_values[-1], 2)
            peak_by_lane[lane] = round(max(lane_values), 2)
            total_by_lane[lane] = round(sum(lane_values), 2)
            if aggregate_mode == "avg_positive":
                positive_values = [value for value in lane_values if value > 0]
                avg_by_lane[lane] = round(sum(positive_values) / len(positive_values), 2) if positive_values else 0.0
            else:
                avg_by_lane[lane] = round(sum(lane_values) / len(lane_values), 2)
        return {
            "file": str(path),
            "minutes": safe_minutes,
            "lanes": lanes,
            "series": series_by_lane,
            "rows": used_rows,
            "updated_at": latest_dt,
            "latest_by_lane": latest_by_lane,
            "peak_by_lane": peak_by_lane,
            "avg_by_lane": avg_by_lane,
            "total_by_lane": total_by_lane,
        }
    except Exception as exc:
        empty["error"] = str(exc)
        return empty


def moving_average(values: list[float], window: int = 5) -> list[float]:
    if not values:
        return []
    safe_window = max(1, int(window or 1))
    result: list[float] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= safe_window:
            running -= values[index - safe_window]
        count = min(index + 1, safe_window)
        result.append(round(running / count, 2))
    return result


def summarize_queue_behavior(series: list[dict[str, Any]]) -> dict[str, Any]:
    if not series:
        return {
            "trend": "no_data",
            "trend_label": "暂无数据",
            "note": "最近 30 分钟还没有排队长度记录。",
            "swing": 0.0,
            "delta": 0.0,
            "smooth_series": [],
        }
    values = [round(float(item.get("value", 0.0)), 2) for item in series]
    smooth_values = moving_average(values, window=5)
    smooth_series = [
        {
            "ts": series[index]["ts"],
            "label": series[index]["label"],
            "value": smooth_values[index],
        }
        for index in range(len(series))
    ]
    lookback = min(len(smooth_values), 120)
    recent_smooth = smooth_values[-lookback:] if lookback else smooth_values
    recent_raw = values[-lookback:] if lookback else values
    first_value = recent_smooth[0] if recent_smooth else 0.0
    last_value = recent_smooth[-1] if recent_smooth else 0.0
    delta = round(last_value - first_value, 2)
    swing = round((max(recent_raw) - min(recent_raw)) if recent_raw else 0.0, 2)
    noisy = swing > max(3.0, abs(delta) * 1.8 + 2.0)
    if delta >= 2.0:
        trend = "rising"
        trend_label = "缓慢上升" if not noisy else "整体上升但波动偏大"
        note = "排队长度最近整体在上升，通常说明车辆在持续积压。"
        if noisy:
            note = "排队长度虽然整体上升，但抖动偏大，建议核对排队区、停止线或车辆框是否稳定。"
    elif delta <= -2.0:
        trend = "falling"
        trend_label = "明显回落"
        note = "排队长度明显回落，通常表示车辆开始放行。"
    else:
        trend = "steady"
        trend_label = "基本持平" if not noisy else "总体持平但有抖动"
        note = "排队长度大体持平，说明当前排队规模变化不大。"
        if noisy:
            note = "排队长度总体没有明显涨跌，但瞬时波动偏大，建议结合现场画面再看一眼。"
    return {
        "trend": trend,
        "trend_label": trend_label,
        "note": note,
        "swing": swing,
        "delta": delta,
        "smooth_series": smooth_series,
    }


def read_metric_window(prefix: str, minutes: int, mode: str) -> dict[str, Any]:
    safe_minutes = max(1, min(int(minutes or 3), 1440))
    path = latest_csv_file(prefix)
    if path is None:
        return {"file": None, "minutes": safe_minutes, "lanes": [], "by_lane": {}, "rows": 0, "updated_at": None}
    max_lines = min(max(int(safe_minutes * 65) + 30, 400), 100000)
    try:
        header, data_lines = read_csv_tail_rows(path, max_lines=max_lines)
        if not data_lines:
            return {"file": str(path), "minutes": safe_minutes, "lanes": [], "by_lane": {}, "rows": 0, "updated_at": None}
        reader = csv.DictReader(StringIO(header + "\n" + "\n".join(data_lines) + "\n"))
        rows = list(reader)
        latest_ts = None
        latest_dt = None
        for row in reversed(rows):
            try:
                latest_ts = float(row.get("ts", ""))
                latest_dt = row.get("dateTime")
                break
            except (TypeError, ValueError):
                continue
        if latest_ts is None:
            return {"file": str(path), "minutes": safe_minutes, "lanes": [], "by_lane": {}, "rows": 0, "updated_at": None}
        start_ts = latest_ts - safe_minutes * 60
        sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        used_rows = 0
        for row in rows:
            try:
                row_ts = float(row.get("ts", ""))
            except (TypeError, ValueError):
                continue
            if row_ts < start_ts:
                continue
            used_rows += 1
            for key, value in row.items():
                if not key.startswith("lane_"):
                    continue
                lane = key.replace("lane_", "")
                try:
                    num = float(value or 0)
                except (TypeError, ValueError):
                    continue
                if mode == "sum":
                    sums[lane] = sums.get(lane, 0.0) + num
                    counts[lane] = counts.get(lane, 0) + 1
                elif mode == "avg_positive":
                    if num > 0:
                        sums[lane] = sums.get(lane, 0.0) + num
                        counts[lane] = counts.get(lane, 0) + 1
                else:
                    sums[lane] = sums.get(lane, 0.0) + num
                    counts[lane] = counts.get(lane, 0) + 1

        def lane_sort_key(lane: str) -> tuple[int, Any]:
            return (0, int(lane)) if lane.isdigit() else (1, lane)

        lanes = sorted(set(sums.keys()) | set(counts.keys()), key=lane_sort_key)
        by_lane: dict[str, float] = {}
        for lane in lanes:
            if mode == "sum":
                by_lane[lane] = round(sums.get(lane, 0.0), 2)
            else:
                count = counts.get(lane, 0)
                by_lane[lane] = round((sums.get(lane, 0.0) / count) if count > 0 else 0.0, 2)
        return {
            "file": str(path),
            "minutes": safe_minutes,
            "lanes": lanes,
            "by_lane": by_lane,
            "rows": used_rows,
            "updated_at": latest_dt,
        }
    except Exception as exc:
        return {"file": str(path), "minutes": safe_minutes, "lanes": [], "by_lane": {}, "rows": 0, "updated_at": None, "error": str(exc)}


def read_recent_lane_metrics_summary(minutes: int = 3) -> dict[str, Any]:
    safe_minutes = max(1, min(int(minutes or 3), 1440))
    flow = read_metric_window("flow", safe_minutes, mode="sum")
    headway = read_metric_window("headway", safe_minutes, mode="avg_positive")
    queue = read_metric_window("queueLen", safe_minutes, mode="avg")
    base_lengths = load_base_length_summary()

    lanes = sorted(
        set(flow.get("lanes", [])) | set(headway.get("lanes", [])) | set(queue.get("lanes", [])) | set(base_lengths.keys()),
        key=lane_sort_key,
    )
    flow_by_lane = {lane: round(float(flow.get("by_lane", {}).get(lane, 0.0)), 2) for lane in lanes}
    headway_by_lane = {lane: round(float(headway.get("by_lane", {}).get(lane, 0.0)), 2) for lane in lanes}
    base_by_lane = {lane: round(float(base_lengths.get(lane, 0.0)), 2) for lane in lanes}
    queue_avg_by_lane: dict[str, float] = {}
    queue_increment_by_lane: dict[str, float] = {}
    for lane in lanes:
        base_val = base_by_lane[lane]
        measured_avg = round(float(queue.get("by_lane", {}).get(lane, 0.0)), 2)
        increment_avg = round(max(measured_avg - base_val, 0.0), 2)
        queue_increment_by_lane[lane] = increment_avg
        queue_avg_by_lane[lane] = round(base_val + increment_avg, 2)
    updated_candidates = [item.get("updated_at") for item in (flow, headway, queue) if item.get("updated_at")]
    return {
        "minutes": safe_minutes,
        "updated_at": updated_candidates[0] if updated_candidates else None,
        "lanes": lanes,
        "flow_total": flow_by_lane,
        "headway_avg": headway_by_lane,
        "base_queue": base_by_lane,
        "queue_increment_avg": queue_increment_by_lane,
        "queue_avg": queue_avg_by_lane,
        "rows_used": {
            "flow": flow.get("rows", 0),
            "headway": headway.get("rows", 0),
            "queue": queue.get("rows", 0),
        },
    }


def read_flow_window_summary(minutes: int) -> dict[str, Any]:
    safe_minutes = max(1, min(int(minutes or 60), 1440))
    path = latest_csv_file("flow")
    if path is None:
        return {"file": None, "minutes": safe_minutes, "lanes": [], "by_lane": {}, "total": 0, "rows": 0}
    max_lines = min(max(int(safe_minutes * 65) + 30, 400), 100000)
    try:
        header, data_lines = read_csv_tail_rows(path, max_lines=max_lines)
        if not data_lines:
            return {"file": str(path), "minutes": safe_minutes, "lanes": [], "by_lane": {}, "total": 0, "rows": 0}
        reader = csv.DictReader(StringIO(header + "\n" + "\n".join(data_lines) + "\n"))
        rows = list(reader)
        latest_ts = None
        for row in reversed(rows):
            try:
                latest_ts = float(row.get("ts", ""))
                break
            except (TypeError, ValueError):
                continue
        if latest_ts is None:
            return {"file": str(path), "minutes": safe_minutes, "lanes": [], "by_lane": {}, "total": 0, "rows": 0}
        start_ts = latest_ts - safe_minutes * 60
        sums: dict[str, float] = {}
        used_rows = 0
        for row in rows:
            try:
                row_ts = float(row.get("ts", ""))
            except (TypeError, ValueError):
                continue
            if row_ts < start_ts:
                continue
            used_rows += 1
            for key, value in row.items():
                if not key.startswith("lane_"):
                    continue
                lane = key.replace("lane_", "")
                try:
                    sums[lane] = sums.get(lane, 0.0) + float(value or 0)
                except (TypeError, ValueError):
                    continue

        lanes = sorted(sums.keys(), key=lane_sort_key)
        by_lane = {lane: round(sums[lane], 2) for lane in lanes}
        total = round(sum(by_lane.values()), 2)
        return {
            "file": str(path),
            "minutes": safe_minutes,
            "lanes": lanes,
            "by_lane": by_lane,
            "total": total,
            "rows": used_rows,
            "start_ts": start_ts,
            "end_ts": latest_ts,
        }
    except Exception as exc:
        return {"file": str(path), "minutes": safe_minutes, "lanes": [], "by_lane": {}, "total": 0, "rows": 0, "error": str(exc)}


def read_recent_log_events(limit: int = 12) -> list[str]:
    path = TRAFFIC_LOG_DIR / "runtime_main.log"
    if not path.exists():
        return []
    lines: deque[str] = deque(maxlen=200)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            pos = handle.tell()
            tail = b""
            block_size = 8192
            while pos > 0 and tail.count(b"\n") <= 400:
                read_size = min(block_size, pos)
                pos -= read_size
                handle.seek(pos)
                tail = handle.read(read_size) + tail
        for line in tail.decode("utf-8", errors="ignore").splitlines():
            lines.append(line.rstrip())
    except Exception as exc:
        return [f"读取日志失败: {exc}"]
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
    signal_config = get_signal_controller_config()
    signal_ping, signal_tcp = get_signal_checks(signal_config["host"], signal_config["port"])
    return {
        "hostname": get_hostname(),
        "active_interface": active_interface,
        "services": [service_status(name) for name in SERVICES],
        "signal_controller": {
            "host": signal_config["host"],
            "port": signal_config["port"],
            "ping": signal_ping,
            "tcp": signal_tcp,
        },
    }


def data_summary(minutes: int = 60) -> dict[str, Any]:
    return {
        "latest_metrics_3m": read_recent_lane_metrics_summary(3),
        "flow_window": read_flow_window_summary(minutes),
        "recent_events": read_recent_log_events(),
    }


def build_data_log_summary(minutes: int = 30) -> dict[str, Any]:
    safe_minutes = max(1, min(int(minutes or 30), 180))
    flow = read_metric_series("flow", safe_minutes, aggregate_mode="sum")
    headway = read_metric_series("headway", safe_minutes, aggregate_mode="avg_positive")
    queue = read_metric_series("queueLen", safe_minutes)
    base_lengths = load_base_length_summary()
    lanes = sorted(
        set(flow.get("lanes", [])) | set(headway.get("lanes", [])) | set(queue.get("lanes", [])) | set(base_lengths.keys()),
        key=lane_sort_key,
    )
    now_ts = time.time()
    lane_items: list[dict[str, Any]] = []
    latest_timestamps: list[float] = []
    for lane in lanes:
        flow_series = list(flow.get("series", {}).get(lane, []))
        headway_series = list(headway.get("series", {}).get(lane, []))
        queue_series = list(queue.get("series", {}).get(lane, []))
        latest_candidates = [series[-1]["ts"] for series in (flow_series, headway_series, queue_series) if series]
        latest_ts = max(latest_candidates) if latest_candidates else None
        if latest_ts is not None:
            latest_timestamps.append(latest_ts)
        stale_seconds = round(max(now_ts - latest_ts, 0.0), 1) if latest_ts is not None else None
        if latest_ts is None:
            freshness = "empty"
            freshness_label = "等待数据"
        elif stale_seconds <= 20:
            freshness = "fresh"
            freshness_label = "已更新"
        elif stale_seconds <= 90:
            freshness = "lagging"
            freshness_label = "最近更新"
        else:
            freshness = "stale"
            freshness_label = "等待刷新"
        queue_behavior = summarize_queue_behavior(queue_series)
        lane_items.append(
            {
                "lane": lane,
                "latest_at": queue_series[-1]["label"] if queue_series else (
                    headway_series[-1]["label"] if headway_series else (
                        flow_series[-1]["label"] if flow_series else None
                    )
                ),
                "stale_seconds": stale_seconds,
                "freshness": freshness,
                "freshness_label": freshness_label,
                "flow": {
                    "current": flow.get("latest_by_lane", {}).get(lane, 0.0),
                    "total": flow.get("total_by_lane", {}).get(lane, 0.0),
                    "peak": flow.get("peak_by_lane", {}).get(lane, 0.0),
                    "average": flow.get("avg_by_lane", {}).get(lane, 0.0),
                    "series": flow_series,
                },
                "headway": {
                    "current": headway.get("latest_by_lane", {}).get(lane, 0.0),
                    "peak": headway.get("peak_by_lane", {}).get(lane, 0.0),
                    "average": headway.get("avg_by_lane", {}).get(lane, 0.0),
                    "series": headway_series,
                },
                "queue": {
                    "base": round(float(base_lengths.get(lane, 0.0)), 2),
                    "current": queue.get("latest_by_lane", {}).get(lane, 0.0),
                    "peak": queue.get("peak_by_lane", {}).get(lane, 0.0),
                    "average": queue.get("avg_by_lane", {}).get(lane, 0.0),
                    "series": queue_series,
                    "smooth_series": queue_behavior["smooth_series"],
                    "trend": queue_behavior["trend"],
                    "trend_label": queue_behavior["trend_label"],
                    "trend_note": queue_behavior["note"],
                    "swing": queue_behavior["swing"],
                    "delta": queue_behavior["delta"],
                },
            }
        )
    latest_at = None
    if latest_timestamps:
        latest_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(max(latest_timestamps)))
    return {
        "minutes": safe_minutes,
        "latest_at": latest_at,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts)),
        "lane_count": len(lane_items),
        "source_files": {
            "flow": flow.get("file"),
            "headway": headway.get("file"),
            "queue": queue.get("file"),
        },
        "lanes": lane_items,
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
    before_sources = parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH)
    before_stream_map = {
        int(item["index"]): {
            "enable": bool(item["enable"]),
            "uri": str(item["uri"]),
        }
        for item in before_sources
    }
    try:
        cameras = save_camera_bindings(items)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    after_stream_map = {
        int(item["index"]): {
            "enable": bool(item["enable"]),
            "uri": str(item["uri"]),
        }
        for item in parse_deepstream_sources(DEEPSTREAM_CONFIG_PATH)
    }
    stream_changed = before_stream_map != after_stream_map
    restart_result = None
    if stream_changed:
        restart_result = run_command(["systemctl", "restart", "traffic_detect.service"], require_root=True, timeout=40)
        if not restart_result["ok"]:
            log_line("[CAMERA] 已更新相机绑定配置，但自动重启 traffic_detect.service 失败")
            return jsonify(
                {
                    "ok": False,
                    "message": restart_result["stderr"] or restart_result["stdout"] or "相机绑定已保存，但自动重启路口感知检测服务失败",
                    "items": cameras,
                    "stream_changed": stream_changed,
                }
            ), 500
    log_line("[CAMERA] 已更新相机绑定配置")
    message = "相机绑定已保存"
    if stream_changed:
        message = "相机绑定已保存，路口感知检测服务已自动重启"
    return jsonify(
        {
            "ok": True,
            "message": message,
            "items": cameras,
            "stream_changed": stream_changed,
            "restart": restart_result,
        }
    )


@app.post("/api/camera-bindings/<int:index>/delete")
def api_camera_binding_delete(index: int):
    if index < 0:
        return jsonify({"ok": False, "message": "source id 不能为负数"}), 400
    try:
        deleted_source = delete_deepstream_source(DEEPSTREAM_CONFIG_PATH, index)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    aliases = load_camera_aliases()
    aliases.pop(str(index), None)
    save_camera_aliases(aliases)
    restart_result = run_command(["systemctl", "restart", "traffic_detect.service"], require_root=True, timeout=40)
    cameras = build_camera_bindings()
    if not restart_result["ok"]:
        log_line(f"[CAMERA] 已彻底删除 source{index}，但自动重启 traffic_detect.service 失败")
        return jsonify(
            {
                "ok": False,
                "message": restart_result["stderr"] or restart_result["stdout"] or "source 已删除，但自动重启路口感知检测服务失败",
                "items": cameras,
                "deleted": deleted_source,
            }
        ), 500
    log_line(f"[CAMERA] 已彻底删除 source{index}")
    return jsonify(
        {
            "ok": True,
            "message": f"source{index} 已彻底删除，路口感知检测服务已自动重启",
            "items": cameras,
            "deleted": deleted_source,
            "restart": restart_result,
        }
    )


@app.post("/api/camera-bindings/check")
def api_camera_bindings_check():
    items = camera_check_items_from_request()
    results = []
    for item in items:
        if not item["enable"]:
            results.append(
                {
                    "index": item["index"],
                    "ok": True,
                    "message": "未启用，已跳过",
                    "ping": {"ok": True, "message": "未启用，已跳过"},
                    "stream": {"ok": True, "message": "未启用，已跳过"},
                }
            )
            continue
        ping_result = ping_host(item["host"], count=1)
        stream_result = check_rtsp_stream(item["uri"])
        results.append(
            {
                "index": item["index"],
                "name": item["name"],
                "host": item["host"],
                "uri": item["uri"],
                "ok": bool(ping_result.get("ok") and stream_result.get("ok")),
                "ping": ping_result,
                "stream": stream_result,
            }
        )
    return jsonify({"ok": True, "results": results})


@app.get("/api/calibration-status")
def api_calibration_status():
    return jsonify({"ok": True, "items": get_calibration_status()})


@app.get("/api/runtime-summary")
def api_runtime_summary():
    return jsonify({"ok": True, "summary": runtime_summary()})


@app.get("/api/data-summary")
def api_data_summary():
    raw_minutes = request.args.get("minutes")
    if raw_minutes is None and request.args.get("hours") is not None:
        try:
            raw_minutes = str(round(float(request.args.get("hours", "1")) * 60))
        except (TypeError, ValueError):
            raw_minutes = "60"
    raw_minutes = raw_minutes or "60"
    try:
        minutes = int(raw_minutes)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "统计时长必须是整数分钟"}), 400
    if not (1 <= minutes <= 1440):
        return jsonify({"ok": False, "message": "统计分钟数必须在 1 到 1440 之间"}), 400
    return jsonify({"ok": True, "summary": data_summary(minutes)})


@app.get("/api/data-log")
def api_data_log():
    raw_minutes = request.args.get("minutes", "30")
    try:
        minutes = int(raw_minutes)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "数据日志时长必须是整数分钟"}), 400
    if not (1 <= minutes <= 180):
        return jsonify({"ok": False, "message": "数据日志时长必须在 1 到 180 分钟之间"}), 400
    return jsonify({"ok": True, "summary": build_data_log_summary(minutes)})


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


@app.get("/api/step-tool/status")
def api_step_tool_status():
    try:
        result = step_tool_request("/api/v1/status")
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc), "online": False}), 502
    online = result.get("data") is True
    return jsonify(
        {
            "ok": True,
            "message": "智能控制在线" if online else "智能控制离线",
            "online": online,
            "raw": result,
        }
    )


@app.get("/api/step-tool/service-status")
def api_step_tool_service_status():
    try:
        result = step_tool_request("/api/v1/service/status")
    except RuntimeError as exc:
        fallback = tcp_check("127.0.0.1", 8080, timeout_sec=1.0)
        if fallback["ok"]:
            return jsonify(
                {
                    "ok": True,
                    "message": "智能控制服务端口已开启，但 /api/v1/service/status 暂未返回 JSON",
                    "running": True,
                    "fallback": True,
                    "detail": str(exc),
                }
            )
        return jsonify({"ok": False, "message": str(exc), "running": False, "fallback": True}), 502
    data = result.get("data")
    if isinstance(data, bool):
        running = data
    elif isinstance(data, str):
        running = data.strip().lower() in ("true", "1", "running", "active", "open", "on")
    elif isinstance(data, dict):
        running = any(
            data.get(key) is True or str(data.get(key)).strip().lower() in ("true", "1", "running", "active", "open", "on")
            for key in ("running", "active", "online", "status", "serviceStatus")
        )
    else:
        running = bool(data)
    return jsonify(
        {
            "ok": True,
            "message": "智能控制服务已开启" if running else "智能控制服务未开启",
            "running": running,
            "raw": result,
        }
    )


@app.post("/api/step-tool/restart-service")
def api_step_tool_restart_service():
    service_name = "preplan-control.service"
    result = run_command(["systemctl", "restart", service_name], require_root=True, timeout=40)
    if not result["ok"]:
        return jsonify({"ok": False, "message": result["stderr"] or result["stdout"] or "智能控制服务重启失败"}), 500
    log_line(f"[STEP] restart {service_name}")
    return jsonify({"ok": True, "message": "智能控制服务已重启，请稍后重新查询状态"})


def normalize_step_tool_config(body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    host = str(body.get("ip") or body.get("host") or "").strip()
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    port_raw = body.get("port")
    try:
        ensure_ipv4(host, "信号机 IP")
    except ValueError as exc:
        return None, str(exc)
    if not username:
        return None, "账户不能为空"
    if not password:
        return None, "密码不能为空"
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        return None, "端口号必须是数字"
    if not (1 <= port <= 65535):
        return None, "端口号超出范围"
    return {"ip": host, "port": port, "username": username, "password": password}, None


def phase_id_from_status(data: dict[str, Any]) -> int | None:
    sorted_phase_status = data.get("sortedPhaseStatus")
    if isinstance(sorted_phase_status, list):
        for item in sorted_phase_status:
            if isinstance(item, dict) and item.get("phaseID") is not None:
                try:
                    return int(item["phaseID"])
                except (TypeError, ValueError):
                    continue
    phase_ring = data.get("phaseRing")
    if isinstance(phase_ring, list):
        for item in phase_ring:
            try:
                return int(item)
            except (TypeError, ValueError):
                continue
    phase_status = data.get("phaseStatus")
    if isinstance(phase_status, dict):
        for key, item in phase_status.items():
            phase_id = item.get("phaseID") if isinstance(item, dict) else key
            try:
                return int(phase_id)
            except (TypeError, ValueError):
                continue
    return None


@app.post("/api/step-tool/tsc-config")
def api_step_tool_tsc_config():
    body = request.get_json(force=True)
    payload, error_message = normalize_step_tool_config(body)
    if error_message:
        return jsonify({"ok": False, "message": error_message}), 400

    try:
        session = step_tool_csrf_opener()
        test_result = step_tool_request(
            "/api/v1/tsc/connection/test",
            method="POST",
            payload=payload,
            session=session,
        )
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502
    test_success = test_result.get("data") is not False
    if not test_success:
        return jsonify(
            {
                "ok": False,
                "message": str(test_result.get("message") or "信号机登录测试失败"),
                "success": False,
                "connection_test": test_result,
            }
        ), 502
    try:
        result = step_tool_request(
            "/api/v1/tsc/config",
            method="POST",
            payload=payload,
            session=session,
        )
    except RuntimeError as exc:
        return jsonify(
            {
                "ok": False,
                "message": f"信号机登录测试成功，但保存参数失败：{exc}",
                "success": False,
                "connection_test": test_result,
            }
        ), 502
    success = result.get("data") is not False
    if not success:
        return jsonify(
            {
                "ok": False,
                "message": str(result.get("message") or "信号机登录测试成功，但保存参数失败"),
                "success": False,
                "raw": result,
                "connection_test": test_result,
            }
        ), 502
    return jsonify(
        {
            "ok": True,
            "message": str(result.get("message") or "信号机登录测试成功，参数已保存"),
            "success": True,
            "raw": result,
            "connection_test": test_result,
        }
    )


@app.post("/api/step-tool/tsc-connection-test")
def api_step_tool_tsc_connection_test():
    body = request.get_json(force=True)
    payload, error_message = normalize_step_tool_config(body)
    if error_message:
        return jsonify({"ok": False, "message": error_message}), 400
    try:
        result = step_tool_request("/api/v1/tsc/connection/test", method="POST", payload=payload)
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc), "success": False}), 502
    success = result.get("data") is not False
    return jsonify(
        {
            "ok": success,
            "message": str(result.get("message") or ("信号机登录测试成功" if success else "信号机登录测试失败")),
            "success": success,
            "raw": result,
        }
    ), 200 if success else 502


@app.get("/api/step-tool/tsc-config")
def api_step_tool_tsc_config_get():
    try:
        result = step_tool_request("/api/v1/tsc/config")
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502
    data = result.get("data") or {}
    return jsonify(
        {
            "ok": True,
            "message": str(result.get("message") or "当前参数读取成功"),
            "config": {
                "ip": data.get("ip") or "",
                "port": data.get("port") or "",
                "username": data.get("username") or "",
                "password": data.get("password") or "",
            },
            "raw": result,
        }
    )


@app.get("/api/step-tool/tsc-status")
def api_step_tool_tsc_status():
    try:
        result = step_tool_request("/api/v1/tsc/status")
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502
    data = result.get("data") or {}
    ctrl_mode = data.get("ctrlMode")
    try:
        ctrl_mode_id = int(ctrl_mode)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "智能控制返回的控制模式无效", "raw": result}), 502
    label = CTRL_MODE_LABELS.get(ctrl_mode_id, f"未知控制模式 {ctrl_mode_id}")
    return jsonify(
        {
            "ok": True,
            "message": f"当前控制模式：{label}",
            "ctrl_mode": ctrl_mode_id,
            "ctrl_mode_label": label,
            "step_control": bool(data.get("stepControl")),
            "phase_id": phase_id_from_status(data),
            "status_data": data,
            "raw": result,
        }
    )


@app.post("/api/step-tool/step-control-test")
def api_step_tool_step_control_test():
    body = request.get_json(silent=True) or {}
    try:
        duration = int(body.get("duration", 30))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "步进控制时长必须是整数秒"}), 400
    if not (1 <= duration <= 3600):
        return jsonify({"ok": False, "message": "步进控制时长必须在 1 到 3600 秒之间"}), 400
    try:
        before_result = step_tool_request("/api/v1/tsc/status")
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": f"获取当前控制状态失败：{exc}"}), 502
    before_data = before_result.get("data") or {}
    phase_id = phase_id_from_status(before_data)
    if phase_id is None:
        return jsonify({"ok": False, "message": "未从智能控制状态中找到可测试的 phaseID", "raw": before_result}), 502
    try:
        control_result = step_tool_request(
            "/api/v1/tsc/stepControl",
            method="POST",
            payload={"phaseId": phase_id, "duration": duration},
        )
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": f"步进控制指令发送失败：{exc}", "phase_id": phase_id}), 502
    control_success = control_result.get("data") is not False
    if not control_success:
        return jsonify(
            {
                "ok": False,
                "message": str(control_result.get("message") or "步进控制指令发送失败"),
                "phase_id": phase_id,
                "before": before_result,
                "control": control_result,
            }
        ), 502
    try:
        after_result = step_tool_request("/api/v1/tsc/status")
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": f"步进控制已发送，但刷新控制状态失败：{exc}", "phase_id": phase_id}), 502
    after_data = after_result.get("data") or {}
    ctrl_mode = after_data.get("ctrlMode")
    try:
        ctrl_mode_id = int(ctrl_mode)
    except (TypeError, ValueError):
        ctrl_mode_id = None
    label = CTRL_MODE_LABELS.get(ctrl_mode_id, f"未知控制模式 {ctrl_mode_id}") if ctrl_mode_id is not None else "未知控制模式"
    step_control = bool(after_data.get("stepControl")) or ctrl_mode_id == 10
    message = f"已对 phaseID {phase_id} 发送 {duration} 秒步进控制，当前控制模式：{label}"
    if step_control:
        message = f"{message}，步进控制已生效"
    else:
        message = f"{message}，暂未确认进入步进控制"
    return jsonify(
        {
            "ok": True,
            "message": message,
            "success": step_control,
            "phase_id": phase_id,
            "duration": duration,
            "ctrl_mode": ctrl_mode_id,
            "ctrl_mode_label": label,
            "step_control": step_control,
            "before": before_result,
            "control": control_result,
            "after": after_result,
            "status_data": after_data,
        }
    )


@app.post("/api/step-tool/step-control-cancel")
def api_step_tool_step_control_cancel():
    try:
        cancel_result = step_tool_request("/api/v1/tsc/stepControl/cancel", method="POST")
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": f"取消步进控制失败：{exc}"}), 502
    success = cancel_result.get("data") is not False
    if not success:
        return jsonify({"ok": False, "message": str(cancel_result.get("message") or "取消步进控制失败"), "raw": cancel_result}), 502
    try:
        status_result = step_tool_request("/api/v1/tsc/status")
    except RuntimeError:
        status_result = None
    status_data = (status_result or {}).get("data") or {}
    return jsonify(
        {
            "ok": True,
            "message": str(cancel_result.get("message") or "已取消步进控制"),
            "success": True,
            "raw": cancel_result,
            "after": status_result,
            "status_data": status_data,
        }
    )


@app.post("/api/step-tool/tsc-config-upload")
def api_step_tool_tsc_config_upload():
    upload_file = request.files.get("file")
    if upload_file is None:
        return jsonify({"ok": False, "message": "请选择要上传的配置文件"}), 400
    content = upload_file.read()
    if not content:
        return jsonify({"ok": False, "message": "配置文件内容为空"}), 400
    try:
        result = step_tool_upload(
            "/api/v1/tsc/config/upload",
            filename=upload_file.filename or "config.json",
            content=content,
            mimetype=upload_file.mimetype or "application/octet-stream",
        )
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502
    data = result.get("data") or {}
    filename = data.get("filename") or upload_file.filename or "配置文件"
    size = data.get("size") or len(content)
    return jsonify(
        {
            "ok": True,
            "message": f"配置文件上传成功：{filename}（{size} 字节）",
            "file": {"filename": filename, "size": size},
            "raw": result,
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
