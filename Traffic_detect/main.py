import os
import glob
import time
import datetime
import threading
import subprocess
import sys
import logging
import struct
import json
import configparser
import re
from collections import deque
from logging.handlers import RotatingFileHandler

from config import settings
from modules.line_counter import MultiLineCounter
from modules.headway_calculator import PassFlagCalculator
from modules.zone_counter import ZoneCounter
from modules.queue_calculator import QueueCalculator
from modules.sse_server import SSEServer
from modules.data_integrator import TrafficDataIntegrator
from modules.stream_monitor import StreamMonitor

from source.devices.Detector import Detector
from source.devices.TrafficSignalController import TrafficSignalController
from source.constants import DEVICE_TYPE_BIT_MAP


class _StreamToLogger:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self._buffer = ""

    def write(self, message):
        if not message:
            return
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8", errors="replace")
            except Exception:
                message = str(message)
        elif not isinstance(message, str):
            message = str(message)
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self.logger.log(self.level, line)

    def flush(self):
        if self._buffer:
            line = self._buffer.rstrip()
            if line:
                self.logger.log(self.level, line)
            self._buffer = ""


def setup_runtime_logging():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.getenv("RUNTIME_LOG_DIR", os.path.join(base_dir, "log"))
    max_total_mb = int(os.getenv("RUNTIME_LOG_MAX_MB", "500"))
    file_mb = int(os.getenv("RUNTIME_LOG_FILE_MB", "50"))

    file_mb = max(1, file_mb)
    max_total_mb = max(file_mb, max_total_mb)
    max_bytes = file_mb * 1024 * 1024
    total_files = max(1, max_total_mb // file_mb)
    backup_count = max(0, total_files - 1)

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "runtime_main.log")

    runtime_logger = logging.getLogger("runtime_main")
    runtime_logger.setLevel(logging.INFO)
    runtime_logger.propagate = False
    runtime_logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setFormatter(formatter)

    runtime_logger.addHandler(file_handler)
    runtime_logger.addHandler(console_handler)

    sys.stdout = _StreamToLogger(runtime_logger, logging.INFO)
    sys.stderr = _StreamToLogger(runtime_logger, logging.ERROR)

    runtime_logger.info(
        "Runtime logging enabled: path=%s, file_mb=%d, max_total_mb=%d, backup_count=%d",
        log_path,
        file_mb,
        max_total_mb,
        backup_count,
    )

# ==========================================
# 1. Helper functions
# ==========================================
def get_file_info(filename):
    try:
        parts = filename.replace(".txt", "").split("_")
        if len(parts) >= 3:
            source_id = int(parts[1])
            try:
                frame_id = int(parts[2])
            except Exception:
                frame_id = -1
            return source_id, frame_id
    except Exception as e:
        print(f"Error parsing filename {filename}: {e}")
    return None, None

def parse_kitti_file(filepath):
    objects = []
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
            for line in lines:
                parts = line.strip().split(" ")
                if len(parts) < 17:
                    continue

                cls = parts[0]
                if cls not in settings.TARGET_CLASSES:
                    continue

                tid = int(parts[1])
                bbox = [float(parts[5]), float(parts[6]), float(parts[7]), float(parts[8])]
                cx = (bbox[0] + bbox[2]) / 2
                cy = bbox[3]

                objects.append(
                    {
                        "class": cls,
                        "track_id": tid,
                        "bbox": bbox,
                        "center": (cx, cy),
                    }
                )
    except Exception as e:
        print(f"Read error {filepath}: {e}")
    return objects

def cleanup_folder(folder_path, max_files_to_keep):
    try:
        pattern = os.path.join(folder_path, "*.txt")
        files = glob.glob(pattern)

        if len(files) > max_files_to_keep:
            files.sort(key=os.path.getmtime)
            files_to_remove = len(files) - max_files_to_keep

            for i in range(files_to_remove):
                file_to_remove = files[i]
                try:
                    os.remove(file_to_remove)
                except Exception as e:
                    print(f"[Cleanup] Error removing {file_to_remove}: {e}")

    except Exception as e:
        print(f"[Cleanup] Error in cleanup_folder for {folder_path}: {e}")

# ==========================================
# 2. Frame Buffer (optimized for 25 fps)
# ==========================================
class FrameBuffer:
    def __init__(self, source_id, max_buffer_size=50):
        self.source_id = source_id
        self.max_buffer_size = max_buffer_size
        self.buffer = {}
        self.expected_frame = 0
        self.last_processed_time = time.time()
        self.frame_interval = 0.04
        self.last_processed_frame = -1
        self.frame_rate_stats = {
            "frames_processed": 0,
            "start_time": time.time(),
            "last_report_time": time.time(),
        }

    def add_frame(self, frame_id, objects, timestamp):
        if frame_id < 0 or frame_id <= self.last_processed_frame:
            return None
        if frame_id in self.buffer:
            return None

        self.buffer[frame_id] = (timestamp, objects)

        if len(self.buffer) > self.max_buffer_size:
            self.flush_old_frames()

        if self.expected_frame in self.buffer:
            return self.process_frame(self.expected_frame)

        return None

    def process_frame(self, frame_id):
        if frame_id not in self.buffer or frame_id <= self.last_processed_frame:
            return None

        timestamp, objects = self.buffer.pop(frame_id)
        self.expected_frame = frame_id + 1
        self.last_processed_time = time.time()
        self.last_processed_frame = frame_id

        self.frame_rate_stats["frames_processed"] += 1

        next_frame = self.expected_frame
        result = (frame_id, objects, timestamp)

        while next_frame in self.buffer:
            _, next_objects = self.buffer.pop(next_frame)
            result = (next_frame, next_objects, timestamp)
            self.expected_frame = next_frame + 1
            self.last_processed_frame = next_frame
            self.frame_rate_stats["frames_processed"] += 1
            next_frame = self.expected_frame

        return result

    def flush_old_frames(self):
        current_time = time.time()
        frames_to_remove = []

        for frame_id, (ts, _) in self.buffer.items():
            if frame_id < self.expected_frame:
                frames_to_remove.append(frame_id)
            elif current_time - ts > 3.0:
                frames_to_remove.append(frame_id)

        for frame_id in frames_to_remove:
            if frame_id in self.buffer:
                del self.buffer[frame_id]

        if self.expected_frame not in self.buffer and len(self.buffer) > 0:
            min_frame = min(self.buffer.keys())
            if min_frame > self.expected_frame + 5:
                self.expected_frame = min_frame

    def get_frame_rate(self):
        current_time = time.time()
        elapsed = current_time - self.frame_rate_stats["start_time"]

        if elapsed > 0:
            fps = self.frame_rate_stats["frames_processed"] / elapsed
            if current_time - self.frame_rate_stats["last_report_time"] > 10:
                self.frame_rate_stats["start_time"] = current_time
                self.frame_rate_stats["frames_processed"] = 0
                self.frame_rate_stats["last_report_time"] = current_time
            return fps
        return 0

# ==========================================
# 3. File Router
# ==========================================
class FileRouter:
    def __init__(self):
        self.stats = {
            "files_processed": 0,
            "files_moved": 0,
            "files_removed": 0,
            "errors": 0,
            "race_miss": 0,
        }

    def route_files(self):
        print("[Router] Bypassed: DeepStream writes directly into source_* folders")
        while True:
            time.sleep(5)

    def get_stats(self):
        stats = self.stats.copy()
        try:
            stats["files_processed"] = sum(
                len(glob.glob(os.path.join(folder_path, "*.txt")))
                for folder_path in settings.SOURCE_DIRS.values()
            )
        except Exception:
            pass
        return stats

# ==========================================
# 4. Source Worker
# ==========================================
def source_worker(source_id, watch_dir, modules):
    print(f"[Worker-{source_id}] Monitoring: {watch_dir}")

    frame_buffer = FrameBuffer(source_id, max_buffer_size=50)
    processed_files = {}
    last_log_time = time.time()
    last_cleanup_time = time.time()
    last_folder_check_time = time.time()

    stats = {
        "frames_processed": 0,
        "frames_buffered": 0,
        "files_parsed": 0,
        "buffer_size": 0,
        "avg_processing_time": 0,
    }

    while True:
        try:
            current_files = glob.glob(os.path.join(watch_dir, "*.txt"))
            new_files = [f for f in current_files if f not in processed_files]

            if not new_files:
                time.sleep(0.005)
                continue

            new_files.sort(key=lambda x: os.path.basename(x))
            files_to_process = new_files[:10]

            for file_path in files_to_process:
                process_start_time = time.time()

                try:
                    fname = os.path.basename(file_path)
                    _, frame_id = get_file_info(fname)
                    if frame_id is None:
                        frame_id = -1
                except Exception:
                    frame_id = -1

                frame_objects = parse_kitti_file(file_path)
                current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                result = frame_buffer.add_frame(frame_id, frame_objects, time.time())

                if result:
                    actual_frame_id, actual_objects, _frame_timestamp = result
                    for module in modules:
                        try:
                            module.process(source_id, actual_frame_id, actual_objects, current_time_str)
                        except Exception as e:
                            print(f"[Worker-{source_id}] Module {module.__class__.__name__} error: {e}")
                    stats["frames_processed"] += 1
                elif frame_id >= 0:
                    stats["frames_buffered"] += 1

                processed_files[file_path] = time.time()
                stats["files_parsed"] += 1

                processing_time = time.time() - process_start_time
                stats["avg_processing_time"] = stats["avg_processing_time"] * 0.9 + processing_time * 0.1

            current_time = time.time()
            if current_time - last_folder_check_time > 10:
                current_file_count = len(glob.glob(os.path.join(watch_dir, "*.txt")))
                if current_file_count > settings.MAX_FILES_KEEP:
                    print(f"[Worker-{source_id}] Folder cleanup: {current_file_count} files > {settings.MAX_FILES_KEEP}")
                    cleanup_folder(watch_dir, settings.MAX_FILES_KEEP)
                last_folder_check_time = current_time

            if current_time - last_cleanup_time > 30:
                files_to_remove = [f for f, t in processed_files.items() if current_time - t > 300]
                for f in files_to_remove:
                    processed_files.pop(f, None)
                last_cleanup_time = current_time

            stats["buffer_size"] = len(frame_buffer.buffer)
            if current_time - last_log_time > 5.0:
                fps = frame_buffer.get_frame_rate()
                print(
                    f"[Worker-{source_id}] Stats: FPS={fps:.1f}, processed={stats['frames_processed']}, "
                    f"buffered={stats['frames_buffered']}, buffer={stats['buffer_size']}, "
                    f"avg_time={stats['avg_processing_time']*1000:.1f}ms"
                )
                last_log_time = current_time

        except Exception as e:
            print(f"[Worker-{source_id}] Critical error: {e}")
            time.sleep(1)

# ==========================================
# 5. Cleanup
# ==========================================
def clean_old_trajectory_files():
    print("=" * 50)
    print("Cleaning up old trajectory files...")

    for sid, folder_path in settings.SOURCE_DIRS.items():
        if os.path.exists(folder_path):
            for file in glob.glob(os.path.join(folder_path, "*.txt")):
                try:
                    os.remove(file)
                except Exception as e:
                    print(f"[Cleanup] Failed to remove {file}: {e}")

    print("Cleanup completed")
    print("=" * 50)

# ==========================================
# 6. Deepstream watchdog
# ==========================================
def _load_ini_config(config_path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    with open(config_path, "r", encoding="utf-8") as fp:
        parser.read_file(fp)
    return parser


def _write_ini_config(parser, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as fp:
        parser.write(fp, space_around_delimiters=False)


def _parse_source_id(section_name):
    if section_name.startswith("source") and section_name[6:].isdigit():
        return int(section_name[6:])
    return None


def _resolve_ds_path(deepstream_root, value):
    if not value:
        return value
    normalized = value.strip().strip("\"'")
    if os.path.isabs(normalized):
        unix_value = normalized.replace("\\", "/")
        marker = "/DeepStream-Yolo/"
        if marker in unix_value:
            suffix = unix_value.split(marker, 1)[1]
            return os.path.abspath(os.path.join(deepstream_root, *suffix.split("/")))
        return normalized
    return os.path.abspath(os.path.join(deepstream_root, normalized))


def get_enabled_deepstream_sources(app_config_path):
    parser = _load_ini_config(app_config_path)
    enabled = []
    for section in parser.sections():
        sid = _parse_source_id(section)
        if sid is None:
            continue
        if parser.get(section, "enable", fallback="0").strip() == "1":
            enabled.append(sid)
    return sorted(enabled)


def build_single_source_infer_config(source_id, deepstream_root, infer_template_path, runtime_dir):
    engine_path = os.path.join(deepstream_root, "model_b1_gpu0_fp16.engine")

    with open(infer_template_path, "r", encoding="utf-8") as fp:
        content = fp.read()

    def _replace_yaml_key(text, key, value):
        pattern = rf"^(\s*{re.escape(key)}:\s*).*$"
        replacement = rf"\g<1>{value}"
        new_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
        if count == 0:
            if not new_text.endswith("\n"):
                new_text += "\n"
            new_text += f"  {key}: {value}\n"
        return new_text

    def _extract_yaml_value(text, key):
        match = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", text, flags=re.MULTILINE)
        return match.group(1).strip() if match else None

    onnx_file = _extract_yaml_value(content, "onnx-file")
    label_file = _extract_yaml_value(content, "labelfile-path")
    custom_lib = _extract_yaml_value(content, "custom-lib-path")

    content = _replace_yaml_key(content, "batch-size", "1")
    if onnx_file:
        content = _replace_yaml_key(content, "onnx-file", _resolve_ds_path(deepstream_root, onnx_file))
    if label_file:
        content = _replace_yaml_key(content, "labelfile-path", _resolve_ds_path(deepstream_root, label_file))
    if custom_lib:
        content = _replace_yaml_key(content, "custom-lib-path", _resolve_ds_path(deepstream_root, custom_lib))
    content = _replace_yaml_key(content, "model-engine-file", engine_path)

    infer_config_path = os.path.join(runtime_dir, f"config_infer_primary_source_{source_id}.yaml")
    os.makedirs(os.path.dirname(infer_config_path), exist_ok=True)
    with open(infer_config_path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(content)
    return infer_config_path


def build_single_source_app_config(source_id, deepstream_root, app_template_path, infer_config_path, retry_interval_s):
    parser = _load_ini_config(app_template_path)

    for section in parser.sections():
        sid = _parse_source_id(section)
        if sid is None:
            continue
        parser[section]["enable"] = "1" if sid == source_id else "0"
        parser[section]["latency"] = parser[section].get("latency", "1000")
        parser[section]["udp-buffer-size"] = parser[section].get("udp-buffer-size", "2000000")
        parser[section]["rtsp-reconnect-interval-sec"] = str(int(retry_interval_s))
        parser[section]["rtsp-reconnect-attempts"] = "-1"

    if parser.has_section("streammux"):
        parser["streammux"]["batch-size"] = "1"

    if parser.has_section("application"):
        kitti_dir = os.path.join(deepstream_root, "output_kitti_data", f"source_{source_id}")
        os.makedirs(kitti_dir, exist_ok=True)
        parser["application"]["kitti-track-output-dir"] = kitti_dir

    if parser.has_section("tracker"):
        tracker_cfg = parser["tracker"].get("ll-config-file")
        if tracker_cfg:
            parser["tracker"]["ll-config-file"] = _resolve_ds_path(deepstream_root, tracker_cfg)

    if parser.has_section("analytics"):
        analytics_cfg = parser["analytics"].get("config-file")
        if analytics_cfg:
            parser["analytics"]["config-file"] = _resolve_ds_path(deepstream_root, analytics_cfg)

    if parser.has_section("primary-gie"):
        parser["primary-gie"]["batch-size"] = "1"
        parser["primary-gie"]["config-file"] = infer_config_path

    runtime_dir = os.path.dirname(infer_config_path)
    app_config_path = os.path.join(runtime_dir, f"deepstream_source_{source_id}.txt")
    _write_ini_config(parser, app_config_path)
    return app_config_path


def prepare_deepstream_runtime_configs(deepstream_root, retry_interval_s=10):
    app_template_path = os.path.join(deepstream_root, "deepstream_app_config.txt")
    infer_template_path = os.path.join(deepstream_root, "config_infer_primary_yolo11.yaml")
    runtime_root = os.path.join(deepstream_root, "generated_runtime")
    enabled_source_ids = get_enabled_deepstream_sources(app_template_path)
    generated = {}

    for source_id in enabled_source_ids:
        runtime_dir = os.path.join(runtime_root, f"source_{source_id}")
        os.makedirs(runtime_dir, exist_ok=True)
        infer_config_path = build_single_source_infer_config(
            source_id=source_id,
            deepstream_root=deepstream_root,
            infer_template_path=infer_template_path,
            runtime_dir=runtime_dir,
        )
        app_config_path = build_single_source_app_config(
            source_id=source_id,
            deepstream_root=deepstream_root,
            app_template_path=app_template_path,
            infer_config_path=infer_config_path,
            retry_interval_s=retry_interval_s,
        )
        generated[source_id] = app_config_path

    return enabled_source_ids, generated


def start_deepstream_source(source_id, app_config_path, deepstream_root, retry_interval_s=10, startup_delay_s=0):
    command = ["deepstream-app", "-c", app_config_path]

    while True:
        if startup_delay_s > 0:
            print(
                f"[DeepStream-watchdog][source-{source_id}] Initial stagger delay "
                f"{int(startup_delay_s)} seconds..."
            )
            time.sleep(startup_delay_s)
            startup_delay_s = 0

        print(
            f"[DeepStream-watchdog][source-{source_id}] Starting in 3 seconds... "
            f"(work dir: {deepstream_root})"
        )
        time.sleep(3)

        try:
            print(
                f"[DeepStream-watchdog][source-{source_id}] launch begin "
                f"config={app_config_path}"
            )
            process = subprocess.Popen(
                command,
                cwd=deepstream_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            print(
                f"[DeepStream-watchdog][source-{source_id}] launch ok "
                f"pid={process.pid}"
            )
            print(
                f"[DeepStream-watchdog][source-{source_id}] process started "
                f"source_id={source_id} pid={process.pid}"
            )

            def read_output(pipe, name):
                try:
                    for line in iter(pipe.readline, ""):
                        if not line:
                            break
                        print(f"[DeepStream-source-{source_id}-{name}] {line.strip()}")
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            threading.Thread(target=read_output, args=(process.stdout, "stdout"), daemon=True).start()
            threading.Thread(target=read_output, args=(process.stderr, "stderr"), daemon=True).start()

            rc = process.wait()
            print(
                f"[DeepStream-watchdog][source-{source_id}] process exited "
                f"source_id={source_id} rc={rc}"
            )

        except FileNotFoundError:
            print(f"[DeepStream-watchdog][source-{source_id}] Error: Cannot find deepstream-app command")
        except Exception as e:
            print(f"[DeepStream-watchdog][source-{source_id}] Failed to start/run DeepStream: {e}")

        print(
            f"[DeepStream-watchdog][source-{source_id}] reconnect scheduled "
            f"source_id={source_id} after={int(retry_interval_s)}s"
        )
        print(
            f"[DeepStream-watchdog][source-{source_id}] Restarting in "
            f"{int(retry_interval_s)} seconds..."
        )
        time.sleep(retry_interval_s)


def wait_for_shared_engine(engine_path, timeout_s=900, stable_s=5, poll_s=1.0):
    start_ts = time.time()
    stable_since = None
    last_size = None

    while time.time() - start_ts < timeout_s:
        try:
            if os.path.exists(engine_path):
                size = os.path.getsize(engine_path)
                if size > 0:
                    if size == last_size:
                        if stable_since is None:
                            stable_since = time.time()
                        elif time.time() - stable_since >= stable_s:
                            print(
                                f"[DeepStream-watchdog] shared engine ready: {engine_path} "
                                f"size={size} stable_for={stable_s}s"
                            )
                            return True
                    else:
                        last_size = size
                        stable_since = time.time()
        except Exception as e:
            print(f"[DeepStream-watchdog] shared engine wait check failed: {e}")

        time.sleep(poll_s)

    print(
        f"[DeepStream-watchdog] shared engine wait timeout after {int(timeout_s)}s: "
        f"{engine_path}"
    )
    return False


def choose_engine_bootstrap_source(enabled_source_ids):
    if not enabled_source_ids:
        return None
    requested = os.getenv("DEEPSTREAM_ENGINE_BOOTSTRAP_SOURCE", "").strip()
    if requested:
        try:
            requested_id = int(requested)
        except ValueError:
            print(f"[DeepStream-watchdog] invalid DEEPSTREAM_ENGINE_BOOTSTRAP_SOURCE={requested}")
        else:
            if requested_id in enabled_source_ids:
                return requested_id
            print(
                f"[DeepStream-watchdog] DEEPSTREAM_ENGINE_BOOTSTRAP_SOURCE={requested_id} "
                f"is not enabled, fallback to automatic selection"
            )
    non_zero_sources = [sid for sid in enabled_source_ids if sid != 0]
    if non_zero_sources:
        return non_zero_sources[0]
    return enabled_source_ids[0]


def broadcast_timer(modules):
    next_tick = int(time.time()) + 1
    while True:
        now = time.time()
        sleep_s = next_tick - now
        if sleep_s > 0:
            time.sleep(sleep_s)

        current_second = int(time.time())
        while next_tick <= current_second:
            for module in modules:
                if hasattr(module, "broadcast_aggregated_data"):
                    try:
                        module.broadcast_aggregated_data(next_tick)
                    except Exception as e:
                        print(f"[BroadcastTimer] Error in {module.__class__.__name__}: {e}")
            next_tick += 1

# ==========================================
# 7. Main
# ==========================================
def main():
    setup_runtime_logging()
    clean_old_trajectory_files()

    project_dir = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
    default_deepstream_root = os.path.join(project_dir, "DeepStream-Yolo")
    deepstream_root = os.getenv("DEEPSTREAM_ROOT", default_deepstream_root)
    per_source_retry_interval_s = float(os.getenv("DEEPSTREAM_RETRY_INTERVAL_S", "10"))
    shared_engine_path = os.path.join(deepstream_root, "model_b1_gpu0_fp16.engine")
    enabled_source_ids, deepstream_runtime_configs = prepare_deepstream_runtime_configs(
        deepstream_root=deepstream_root,
        retry_interval_s=per_source_retry_interval_s,
    )
    if not enabled_source_ids:
        enabled_source_ids = sorted(settings.SOURCE_DIRS.keys())
        print(
            f"[DeepStream-watchdog] No enabled sources found in template config, "
            f"fallback to settings.SOURCE_DIRS: {enabled_source_ids}"
        )
    else:
        print(f"[DeepStream-watchdog] Enabled independent sources: {enabled_source_ids}")

    # SSE
    sse_server = None
    if settings.SSE_ENABLED:
        sse_host = os.getenv("SSE_HOST", settings.SSE_HOST)
        sse_port = int(os.getenv("SSE_PORT", str(settings.SSE_PORT)))
        sse_server = SSEServer(
            host=sse_host,
            port=sse_port,
            client_queue_maxsize=10,
            verbose=False,
        )
        sse_server.start()
        print(f"[Main] Dashboard: http://{sse_host}:{sse_port}/")
        print(f"[Main] SSE Stream: http://{sse_host}:{sse_port}/sse")

    # Integrator
    data_integrator = TrafficDataIntegrator(
        sse_server=sse_server,
        verbose=False,
        lines_config_path=settings.LINES_CONFIG_PATH,
        zones_config_path=settings.ZONES_CONFIG_PATH,
    )
    if sse_server and hasattr(sse_server, "set_history_dir"):
        sse_server.set_history_dir(data_integrator.queue_csv_dir)

    # Stream monitor
    stream_monitor = StreamMonitor(
        sse_server=sse_server,
        source_ids=enabled_source_ids,
        timeout_s=30.0,
        check_interval_s=0.2,
        verbose=False,
    )

    # Modules
    shared_modules = [
        MultiLineCounter(config_path=settings.LINES_CONFIG_PATH, sse_server=sse_server, verbose=False),
        PassFlagCalculator(config_path=settings.HEADWAY_CONFIG_PATH, sse_server=sse_server, verbose=False),
        ZoneCounter(config_path=settings.ZONES_CONFIG_PATH, sse_server=sse_server, verbose=False),
        QueueCalculator(config_path=settings.QUEUE_CONFIG_PATH, sse_server=sse_server, verbose=False),
        stream_monitor,
    ]
    for module in shared_modules:
        module.data_integrator = data_integrator
    for module in shared_modules:
        if isinstance(module, PassFlagCalculator):
            data_integrator.pass_flag_source = module
            break
    stream_monitor.start()

    # DeepStream
    bootstrap_source_started = None
    if enabled_source_ids and (not os.path.exists(shared_engine_path)):
        bootstrap_source_id = choose_engine_bootstrap_source(enabled_source_ids)
        bootstrap_config_path = deepstream_runtime_configs.get(bootstrap_source_id)
        if bootstrap_source_id is not None and bootstrap_config_path:
            print(
                f"[DeepStream-watchdog] shared engine missing, bootstrap with source_{bootstrap_source_id} first: "
                f"{shared_engine_path}"
            )
            threading.Thread(
                target=start_deepstream_source,
                args=(
                    bootstrap_source_id,
                    bootstrap_config_path,
                    deepstream_root,
                    per_source_retry_interval_s,
                    0,
                ),
                daemon=True,
            ).start()
            bootstrap_source_started = bootstrap_source_id
            wait_timeout_s = float(os.getenv("DEEPSTREAM_SHARED_ENGINE_WAIT_S", "900"))
            if not wait_for_shared_engine(shared_engine_path, timeout_s=wait_timeout_s):
                print(
                    f"[DeepStream-watchdog] shared engine not ready after bootstrap wait; "
                    f"continue launching remaining enabled sources: {enabled_source_ids}"
                )

    for index, source_id in enumerate(enabled_source_ids):
        if source_id == bootstrap_source_started:
            continue
        app_config_path = deepstream_runtime_configs.get(source_id)
        if not app_config_path:
            print(f"[DeepStream-watchdog][source-{source_id}] skip: no generated config")
            continue
        threading.Thread(
            target=start_deepstream_source,
            args=(
                source_id,
                app_config_path,
                deepstream_root,
                per_source_retry_interval_s,
                index * 2,
            ),
            daemon=True,
        ).start()

    # Timers
    threading.Thread(target=broadcast_timer, args=(shared_modules,), daemon=True).start()

    def integrator_timer():
        while True:
            time.sleep(1.0)
            try:
                data_integrator.integrate_and_broadcast()
            except Exception as e:
                print(f"[IntegratorTimer] Error: {e}")

    threading.Thread(target=integrator_timer, daemon=True).start()

    def passflag_timer():
        while True:
            time.sleep(0.2)
            try:
                data_integrator.integrate_and_broadcast_pass_flags(interval_seconds=0.2)
            except Exception as e:
                print(f"[PassFlagTimer] Error: {e}")

    threading.Thread(target=passflag_timer, daemon=True).start()

    # ================
    # GB43229 Link + B.7.1 uploader
    # ================
    AREA_CODE = 330784
    DEVICE_NO = 1
    LOCAL_PORT = 40000

    LOCAL_IP = os.getenv("GB_LOCAL_IP", "0.0.0.0")
    TSC_IP = os.getenv("GB_TSC_IP", "172.16.4.246")
    TSC_PORT = int(os.getenv("GB_TSC_PORT", "40000"))

    detector_type = next((k for k, v in DEVICE_TYPE_BIT_MAP.items() if v == 4), None)
    if detector_type is None:
        raise RuntimeError("Cannot find detector device type (bit=4) in DEVICE_TYPE_BIT_MAP")

    detector = Detector(
        area_code=AREA_CODE,
        device_type=detector_type,
        device_no=DEVICE_NO,
        ip=LOCAL_IP,
        port=LOCAL_PORT,
    )
    tsc = TrafficSignalController(
        area_code=AREA_CODE,
        device_no=1,
        ip=TSC_IP,
        port=TSC_PORT,
    )
    b71_context_lock = threading.Lock()
    b71_recent_contexts = deque(maxlen=120)
    b71_tx_seq = 0
    b71_err_file_lock = threading.Lock()
    gb_link_lock = threading.Lock()
    gb_state_lock = threading.Lock()
    gb_last_rx_monotonic = time.monotonic()
    gb_last_rx_wall = time.time()
    gb_last_reconnect_monotonic = 0.0
    gb_last_force_reset_monotonic = 0.0
    gb_reconnect_count = 0
    RX_HEARTBEAT_TIMEOUT_S = float(os.getenv("GB_RX_HEARTBEAT_TIMEOUT_S", "15"))
    RX_RECONNECT_MIN_INTERVAL_S = float(os.getenv("GB_RX_RECONNECT_MIN_INTERVAL_S", "10"))
    RX_FORCE_RESET_ON_TIMEOUT = os.getenv("GB_RX_FORCE_RESET_ON_TIMEOUT", "1") == "1"
    RX_FORCE_RESET_MIN_INTERVAL_S = float(os.getenv("GB_RX_FORCE_RESET_MIN_INTERVAL_S", "10"))
    if RX_HEARTBEAT_TIMEOUT_S < 3:
        RX_HEARTBEAT_TIMEOUT_S = 3
    if RX_RECONNECT_MIN_INTERVAL_S < 2:
        RX_RECONNECT_MIN_INTERVAL_S = 2
    if RX_FORCE_RESET_MIN_INTERVAL_S < 10:
        RX_FORCE_RESET_MIN_INTERVAL_S = 10
    b71_err_log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "log",
        "b71_err_context.jsonl",
    )
    B71_ERR_FILE_MB = int(os.getenv("GB_B71_ERR_FILE_MB", "20"))
    B71_ERR_TOTAL_MB = int(os.getenv("GB_B71_ERR_TOTAL_MB", "200"))
    if B71_ERR_FILE_MB < 1:
        B71_ERR_FILE_MB = 1
    if B71_ERR_TOTAL_MB < B71_ERR_FILE_MB:
        B71_ERR_TOTAL_MB = B71_ERR_FILE_MB

    def _list_b71_err_files():
        log_dir = os.path.dirname(b71_err_log_path)
        files = glob.glob(os.path.join(log_dir, "b71_err_context*.jsonl"))
        return [p for p in files if os.path.isfile(p)]

    def _rotate_b71_err_file_if_needed():
        max_bytes = B71_ERR_FILE_MB * 1024 * 1024
        if not os.path.exists(b71_err_log_path):
            return
        try:
            if os.path.getsize(b71_err_log_path) < max_bytes:
                return
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            rotated = b71_err_log_path.replace(".jsonl", f"_{ts}.jsonl")
            os.replace(b71_err_log_path, rotated)
            print(f"[GB43229][RX][ERR_B71] rotate file -> {rotated}")
        except Exception as e:
            print(f"[GB43229][RX][ERR_B71] rotate failed: {e}")

    def _cleanup_b71_err_files_if_needed():
        max_total_bytes = B71_ERR_TOTAL_MB * 1024 * 1024
        try:
            files = _list_b71_err_files()
            if not files:
                return
            entries = []
            total = 0
            for p in files:
                try:
                    st = os.stat(p)
                    entries.append((st.st_mtime, st.st_size, p))
                    total += st.st_size
                except Exception:
                    continue
            if total <= max_total_bytes:
                return
            entries.sort(key=lambda x: x[0])  # oldest first
            for _, size, p in entries:
                if total <= max_total_bytes:
                    break
                # Keep current active file as the last deletion candidate.
                if p == b71_err_log_path and len(entries) > 1:
                    continue
                try:
                    os.remove(p)
                    total -= size
                except Exception:
                    continue
        except Exception as e:
            print(f"[GB43229][RX][ERR_B71] cleanup failed: {e}")

    def save_b71_err_context(record: dict):
        with b71_err_file_lock:
            try:
                os.makedirs(os.path.dirname(b71_err_log_path), exist_ok=True)
                _rotate_b71_err_file_if_needed()
                with open(b71_err_log_path, "a", encoding="utf-8") as fp:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                _cleanup_b71_err_files_if_needed()
            except Exception as e:
                print(f"[GB43229][RX][ERR_B71] persist failed: {e}")

    def mark_gb_rx():
        nonlocal gb_last_rx_monotonic, gb_last_rx_wall
        now_mono = time.monotonic()
        now_wall = time.time()
        with gb_state_lock:
            gb_last_rx_monotonic = now_mono
            gb_last_rx_wall = now_wall

    def get_gb_rx_age_sec() -> float:
        with gb_state_lock:
            return max(0.0, time.monotonic() - gb_last_rx_monotonic)

    def refresh_gb_link(reason: str):
        nonlocal gb_last_reconnect_monotonic, gb_last_force_reset_monotonic, gb_reconnect_count
        now_mono = time.monotonic()
        reason_lc = str(reason).lower()
        immediate_fast_path = ("errno_9" in reason_lc) or ("errno_32" in reason_lc)
        with gb_link_lock:
            if (not immediate_fast_path) and (
                now_mono - gb_last_reconnect_monotonic < RX_RECONNECT_MIN_INTERVAL_S
            ):
                return
            gb_last_reconnect_monotonic = now_mono
            gb_reconnect_count += 1
            rx_age = get_gb_rx_age_sec()
            actions = []

            # Optional hard reset: close stale client socket before reconnecting.
            if immediate_fast_path:
                try:
                    cli = getattr(detector, "_client_socket", None)
                    if cli:
                        cli.close()
                        detector._client_socket = None
                        actions.append("force_socket_reset_immediate")
                    gb_last_force_reset_monotonic = now_mono
                except Exception as e:
                    actions.append(f"force_reset_immediate_failed:{e}")
            elif (
                RX_FORCE_RESET_ON_TIMEOUT
                and now_mono - gb_last_force_reset_monotonic >= RX_FORCE_RESET_MIN_INTERVAL_S
            ):
                try:
                    cli = getattr(detector, "_client_socket", None)
                    if cli:
                        cli.close()
                        detector._client_socket = None
                        actions.append("force_socket_reset")
                    gb_last_force_reset_monotonic = now_mono
                except Exception as e:
                    actions.append(f"force_reset_failed:{e}")

            try:
                if getattr(detector, "_client_socket", None) is None:
                    detector.connect(tsc)
                    actions.append("connect")
            except Exception as e:
                actions.append(f"connect_failed:{e}")

            try:
                detector.send_connection_request()
                actions.append("send_connection_request")
            except Exception as e:
                actions.append(f"connection_request_failed:{e}")

            print(
                f"[GB43229][LINK] reconnect_try={gb_reconnect_count} "
                f"reason={reason} rx_age={rx_age:.1f}s actions={','.join(actions) if actions else 'none'}"
            )

    def on_gb_msg(is_valid, sender, recierver, operation, object_id, content, addr):
        mark_gb_rx()
        print(
            f"[GB43229][RX] from {addr} valid={is_valid} "
            f"op=0x{int(operation):x} obj=0x{int(object_id):x} len={len(content)} sender={sender}"
        )
        if int(operation) == 0x86 and int(object_id) == 0x0301:
            err_hex = content.hex(" ").upper() if content else ""
            err_u32_be = None
            err_u32_le = None
            if content and len(content) >= 4:
                try:
                    err_u32_be = struct.unpack(">I", content[:4])[0]
                    err_u32_le = struct.unpack("<I", content[:4])[0]
                except Exception:
                    pass
            print(
                f"[GB43229][RX][ERR_B71] payload_hex={err_hex} "
                f"u32_be={err_u32_be} u32_le={err_u32_le}"
            )
            matched_ctx = None
            with b71_context_lock:
                if b71_recent_contexts:
                    matched_ctx = b71_recent_contexts[-1]
            if matched_ctx:
                err_record = {
                    "rx_time": time.time(),
                    "rx_datetime": datetime.datetime.now().isoformat(timespec="milliseconds"),
                    "remote_addr": f"{addr[0]}:{addr[1]}",
                    "operation": int(operation),
                    "object_id": int(object_id),
                    "error_payload_hex": err_hex,
                    "error_u32_be": err_u32_be,
                    "error_u32_le": err_u32_le,
                    "tx_context": matched_ctx,
                }
                save_b71_err_context(err_record)
                print(
                    f"[GB43229][RX][ERR_B71][CTX] tx_seq={matched_ctx.get('tx_seq')} "
                    f"tx_time={matched_ctx.get('tx_datetime')} "
                    f"lane_count={matched_ctx.get('lane_count')} "
                    f"path={b71_err_log_path}"
                )

    detector.set_message_handler(on_gb_msg)
    detector.connect(tsc)
    detector.send_connection_request()
    print(
        f"[GB43229][CFG] rx_timeout_s={RX_HEARTBEAT_TIMEOUT_S:.1f} "
        f"reconnect_interval_s={RX_RECONNECT_MIN_INTERVAL_S:.1f} "
        f"force_reset_on_timeout={int(RX_FORCE_RESET_ON_TIMEOUT)} "
        f"force_reset_interval_s={RX_FORCE_RESET_MIN_INTERVAL_S:.1f}"
    )
    print(
        f"[GB43229][CFG] b71_err_file_mb={B71_ERR_FILE_MB} "
        f"b71_err_total_mb={B71_ERR_TOTAL_MB}"
    )

    def gb43229_link_watchdog_thread():
        while True:
            time.sleep(1.0)
            try:
                rx_age = get_gb_rx_age_sec()
                if rx_age >= RX_HEARTBEAT_TIMEOUT_S:
                    refresh_gb_link(reason=f"rx_timeout>{RX_HEARTBEAT_TIMEOUT_S:.1f}s")
            except Exception as e:
                print(f"[GB43229][LINK] watchdog error: {e}")

    threading.Thread(target=gb43229_link_watchdog_thread, daemon=True).start()

    # Production upload switches
    ENABLE_B71_UPLOAD = os.getenv("GB_ENABLE_B71", "1") == "1"
    ENABLE_B81_UPLOAD = os.getenv("GB_ENABLE_B81", "1") == "1"
    # B.7.1/B.8.1 channel whitelist, default 1~30.
    # Examples:
    #   GB_B71_CHANNEL_WHITELIST="1-30"
    #   GB_B71_CHANNEL_WHITELIST="1,2,3,5-8"
    B71_CHANNEL_WHITELIST = os.getenv("GB_B71_CHANNEL_WHITELIST", "1-30")
    # Skip B.7.1 upload when summed flow_a is zero.
    # Default to False so B.7.1 is still sent even when flow is 0.
    SKIP_B71_WHEN_ZERO_FLOW = os.getenv("GB_B71_SKIP_ZERO_FLOW", "0") == "1"
    # Skip B.7.1 upload when no channel remains after whitelist filtering.
    SKIP_B71_WHEN_NO_CHANNEL = os.getenv("GB_B71_SKIP_NO_CHANNEL", "1") == "1"
    # Startup protection: if queue is large but flow is still 0, inject minimal request.
    # Disabled by default because synthetic flow may be rejected by strict signal controllers.
    B71_STARTUP_PROTECT_ENABLE = os.getenv("GB_B71_STARTUP_PROTECT", "1") == "1"
    B71_STARTUP_QUEUE_THRESHOLD_M = float(os.getenv("GB_B71_STARTUP_QUEUE_THRESHOLD_M", "60"))
    B71_STARTUP_MIN_FLOW_A = int(os.getenv("GB_B71_STARTUP_MIN_FLOW_A", "1"))
    B71_LANE_DEBUG = os.getenv("GB_B71_LANE_DEBUG", "1") == "1"
    B71_SAMPLE_COUNT = int(os.getenv("GB_B71_SAMPLE_COUNT", "10"))
    B71_DEFAULT_SPEED = int(os.getenv("GB_B71_DEFAULT_SPEED", "30"))
    B71_DEFAULT_LENGTH_M = float(os.getenv("GB_B71_DEFAULT_LENGTH_M", "4.5"))
    if B71_STARTUP_QUEUE_THRESHOLD_M < 0:
        B71_STARTUP_QUEUE_THRESHOLD_M = 0.0
    if B71_STARTUP_MIN_FLOW_A < 1:
        B71_STARTUP_MIN_FLOW_A = 1
    if B71_STARTUP_MIN_FLOW_A > 255:
        B71_STARTUP_MIN_FLOW_A = 255
    if B71_SAMPLE_COUNT < 1:
        B71_SAMPLE_COUNT = 1
    if B71_SAMPLE_COUNT > 255:
        B71_SAMPLE_COUNT = 255
    if B71_DEFAULT_SPEED < 0:
        B71_DEFAULT_SPEED = 0
    if B71_DEFAULT_SPEED > 255:
        B71_DEFAULT_SPEED = 255
    if B71_DEFAULT_LENGTH_M < 0:
        B71_DEFAULT_LENGTH_M = 0.0
    if B71_DEFAULT_LENGTH_M > 6553.5:
        B71_DEFAULT_LENGTH_M = 6553.5

    def parse_channel_whitelist(spec: str) -> set[int]:
        channels = set()
        for token in (spec or "").split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                left, right = token.split("-", 1)
                try:
                    start = int(left.strip())
                    end = int(right.strip())
                except ValueError:
                    continue
                if start > end:
                    start, end = end, start
                for ch in range(start, end + 1):
                    channels.add(ch)
            else:
                try:
                    channels.add(int(token))
                except ValueError:
                    continue
        return {ch for ch in channels if 1 <= ch <= 128}

    allowed_channels = parse_channel_whitelist(B71_CHANNEL_WHITELIST)
    if not allowed_channels:
        # Fallback to protocol-valid default if env var is malformed/empty.
        allowed_channels = set(range(1, 31))
    print(
        f"[GB43229][CFG] B71 whitelist size={len(allowed_channels)} "
        f"min={min(allowed_channels)} max={max(allowed_channels)}"
    )
    print(
        f"[GB43229][CFG] B71 startup_protect={int(B71_STARTUP_PROTECT_ENABLE)} "
        f"queue_threshold_m={B71_STARTUP_QUEUE_THRESHOLD_M:.1f} "
        f"min_flow_a={B71_STARTUP_MIN_FLOW_A}"
    )
    print(
        f"[GB43229][CFG] B71 sample_count={B71_SAMPLE_COUNT} "
        f"default_speed={B71_DEFAULT_SPEED} "
        f"default_length_m={B71_DEFAULT_LENGTH_M:.1f} "
        f"skip_zero_flow={int(SKIP_B71_WHEN_ZERO_FLOW)}"
    )
    print(f"[GB43229][CFG] B71 lane_debug={int(B71_LANE_DEBUG)}")

    def gb43229_b71_uploader_thread():
        nonlocal b71_tx_seq
        while True:
            time.sleep(1.0)
            try:
                snapshot = data_integrator.get_latest_snapshot()
                if not snapshot:
                    print("[GB43229][TX] B.7.1 skipped: no aggregated snapshot yet")
                    continue
                lane_info_list = snapshot.get("lane_info_list", [])

                channel_details = []
                startup_protect_count = 0
                tx_lane_context = []
                for lane in lane_info_list:
                    lane_no = int(lane.get("laneNo", 1))
                    if lane_no not in allowed_channels:
                        continue
                    raw_cross_num = int(lane.get("crossNumber", 0))
                    cross_num = max(0, min(raw_cross_num, 255))
                    queue_len = float(lane.get("queueLen", 0.0))
                    head_headway = float(lane.get("headHeadway", 0.0))

                    startup_protected = (
                        B71_STARTUP_PROTECT_ENABLE
                        and queue_len >= B71_STARTUP_QUEUE_THRESHOLD_M
                        and cross_num == 0
                    )
                    if startup_protected:
                        cross_num = max(cross_num, B71_STARTUP_MIN_FLOW_A)
                        startup_protect_count += 1

                    if B71_LANE_DEBUG:
                        print(
                            f"[GB43229][TX][lane] lane={lane_no} "
                            f"cross_raw={raw_cross_num} cross_tx={cross_num} "
                            f"headway={head_headway:.2f}s queue={queue_len:.2f}m "
                            f"startup_protected={int(startup_protected)} "
                            f"allowed=1"
                        )

                    occupancy = float(lane.get("occupancy", 0.0))
                    occupancy = max(0.0, min(100.0, occupancy))
                    occupancy_ones = int(round((occupancy / 100.0) * B71_SAMPLE_COUNT))
                    occupancy_ones = max(0, min(B71_SAMPLE_COUNT, occupancy_ones))
                    occupancy_data = [1] * occupancy_ones + [0] * (B71_SAMPLE_COUNT - occupancy_ones)

                    avg_speed = B71_DEFAULT_SPEED if cross_num > 0 else 0
                    avg_length = B71_DEFAULT_LENGTH_M if cross_num > 0 else 0.0

                    space_headway = 0.0
                    try:
                        vehicle_num = int(lane.get("vehicleNum", 0))
                        if vehicle_num > 0 and queue_len > 0:
                            # Approximate with per-vehicle queue share when only queue length is available.
                            space_headway = queue_len / float(vehicle_num)
                    except Exception:
                        space_headway = 0.0

                    # B.37 fields are encoded in 0.1 units with 1 byte, clamp to protocol range.
                    head_headway = max(0.0, min(25.5, head_headway))
                    space_headway = max(0.0, min(25.5, space_headway))

                    channel_details.append(
                        {
                            "channel_id": lane_no,
                            "flow_a": cross_num,
                            "flow_b": 0,
                            "flow_c": 0,
                            "occupancy": occupancy,
                            "avg_speed": avg_speed,
                            "avg_length": avg_length,
                            "head_headway": head_headway,
                            "space_headway": space_headway,
                            "stop_count": 0.0,
                            "stop_duration": 0.0,
                            "sample_count": B71_SAMPLE_COUNT,
                            "occupancy_data": occupancy_data,
                        }
                    )
                    tx_lane_context.append(
                        {
                            "lane": lane_no,
                            "flow_a": cross_num,
                            "headway_s": round(head_headway, 3),
                            "queue_m": round(queue_len, 3),
                            "startup_protected": int(startup_protected),
                        }
                    )

                if not channel_details and SKIP_B71_WHEN_NO_CHANNEL:
                    print("[GB43229][TX] B.7.1 skipped: no channel after whitelist filter")
                    continue

                if SKIP_B71_WHEN_ZERO_FLOW:
                    send_channel_details = [item for item in channel_details if int(item["flow_a"]) != 0]
                    send_lane_context = [lane for lane in tx_lane_context if int(lane["flow_a"]) != 0]
                else:
                    send_channel_details = channel_details
                    send_lane_context = tx_lane_context
                if not send_channel_details:
                    print("[GB43229][TX] B.7.1 skipped: all lanes flow_a=0")
                    continue
                flow_total = sum(item["flow_a"] for item in send_channel_details)

                flow_data = {
                    "time": time.time(),
                    "channel_details": send_channel_details,
                }
                frame = detector.builder.build(
                    receiver_id=detector.reciever_id,
                    operation_type=0x82,
                    object_id=0x0301,
                    payload=flow_data,
                )
                send_ok = detector.send(frame)
                if not send_ok:
                    last_errno = getattr(detector, "_last_send_errno", None)
                    if last_errno in (9, 32):
                        refresh_gb_link(reason=f"send_errno_{last_errno}")
                    else:
                        refresh_gb_link(reason="send_failed_b71")
                    continue
                tx_payload_hex = ""
                try:
                    parsed_tx = detector.parser.parse(frame=frame)
                    tx_payload = parsed_tx.get("payload", b"")
                    if isinstance(tx_payload, (bytes, bytearray)):
                        tx_payload_hex = bytes(tx_payload).hex(" ").upper()
                except Exception:
                    pass

                b71_tx_seq += 1
                tx_ctx = {
                    "tx_seq": b71_tx_seq,
                    "tx_time": flow_data["time"],
                    "tx_datetime": datetime.datetime.now().isoformat(timespec="milliseconds"),
                    "lane_count": len(send_lane_context),
                    "flow_total": flow_total,
                    "startup_protect_count": startup_protect_count,
                    "tx_payload_hex": tx_payload_hex,
                    "tx_frame_hex": frame.hex(" ").upper(),
                    "lanes": send_lane_context,
                }
                with b71_context_lock:
                    b71_recent_contexts.append(tx_ctx)
                print(
                    f"[GB43229][TX] B.7.1 lanes={len(send_channel_details)} "
                    f"flow_total={flow_total} "
                    f"startup_protect={startup_protect_count} "
                    f"occupancy_avg="
                    f"{(sum(item['occupancy'] for item in send_channel_details) / len(send_channel_details)) if send_channel_details else 0.0:.1f}% "
                    f"headway_avg="
                    f"{(sum(item['head_headway'] for item in send_channel_details) / len(send_channel_details)) if send_channel_details else 0.0:.2f}s"
                )
            except Exception as e:
                print(f"[GB43229] upload error: {e}")

    def gb43229_b81_uploader_thread():
        while True:
            time.sleep(1.0)
            try:
                snapshot = data_integrator.get_latest_snapshot()
                if not snapshot:
                    print("[GB43229][TX] B.8.1 skipped: no aggregated snapshot yet")
                    continue
                lane_info_list = snapshot.get("lane_info_list", [])

                channel_details = []
                for lane in lane_info_list:
                    lane_no = int(lane.get("laneNo", 1))
                    queue_len_m = int(round(float(lane.get("queueLen", 0.0))))
                    queue_len_m = max(0, min(queue_len_m, 65535))
                    vehicle_num = int(lane.get("vehicleNum", 0))
                    vehicle_num = max(0, min(vehicle_num, 65535))

                    channel_details.append(
                        {
                            "channel_id": lane_no,
                            "vehicle_count": vehicle_num,
                            "occupancy": float(lane.get("occupancy", 0.0)),
                            "queue_len": queue_len_m,
                            "head_pos": 0,
                            "rear_pos": 0,
                            "avg_speed": 0,
                            "head_speed": 0,
                            "rear_speed": 0,
                            "space_headway": 0.0,
                        }
                    )

                status_data = {
                    "time": time.time(),
                    "channel_details": channel_details,
                }
                frame = detector.builder.build(
                    receiver_id=detector.reciever_id,
                    operation_type=0x82,
                    object_id=0x0401,
                    payload=status_data,
                )
                send_ok = detector.send(frame)
                if not send_ok:
                    last_errno = getattr(detector, "_last_send_errno", None)
                    if last_errno in (9, 32):
                        refresh_gb_link(reason=f"send_errno_{last_errno}")
                    else:
                        refresh_gb_link(reason="send_failed_b81")
                    continue
                print(
                    f"[GB43229][TX] B.8.1 lanes={len(channel_details)} "
                    f"queue_total={sum(item['queue_len'] for item in channel_details)}m"
                )
            except Exception as e:
                print(f"[GB43229] B.8.1 upload error: {e}")

    if ENABLE_B71_UPLOAD:
        threading.Thread(target=gb43229_b71_uploader_thread, daemon=True).start()
    if ENABLE_B81_UPLOAD:
        threading.Thread(target=gb43229_b81_uploader_thread, daemon=True).start()

    # Router + workers
    file_router = FileRouter()
    threading.Thread(target=file_router.route_files, daemon=True).start()

    for sid in enabled_source_ids:
        folder_path = settings.SOURCE_DIRS.get(sid, os.path.join(settings.ROOT_WATCH_DIR, f"source_{sid}"))
        os.makedirs(folder_path, exist_ok=True)
        threading.Thread(target=source_worker, args=(sid, folder_path, shared_modules), daemon=True).start()

    print(f"Started {len(enabled_source_ids)} workers")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
        router_stats = file_router.get_stats()
        print("\nFile Router Stats:")
        print(f"  Files processed: {router_stats['files_processed']}")
        print(f"  Files moved: {router_stats['files_moved']}")
        print(f"  Files removed: {router_stats['files_removed']}")
        print(f"  Race miss (file disappeared): {router_stats['race_miss']}")
        print(f"  Errors: {router_stats['errors']}")

if __name__ == "__main__":
    main()
