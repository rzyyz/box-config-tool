import configparser
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEEPSTREAM_CONFIG_PATH = PROJECT_ROOT / "DeepStream-Yolo" / "deepstream_app_config.txt"
QUEUE_CSV_DIR = SCRIPT_DIR / "queue_csv"
OUTPUT_KITTI_DIR = PROJECT_ROOT / "DeepStream-Yolo" / "output_kitti_data"
MAIN_SCRIPT = SCRIPT_DIR / "main.py"

RESTART_ON_RECOVERY_IDLE_SECONDS = float(os.getenv("TRAFFIC_RECOVERY_IDLE_SECONDS", "60"))
REACHABLE_CONFIRM_ROUNDS = int(os.getenv("TRAFFIC_RECOVERY_CONFIRM_ROUNDS", "3"))
MONITOR_INTERVAL_SECONDS = float(os.getenv("TRAFFIC_RECOVERY_MONITOR_INTERVAL", "5"))
STARTUP_GRACE_SECONDS = float(os.getenv("TRAFFIC_STARTUP_GRACE_SECONDS", "180"))
POST_RECOVERY_GRACE_SECONDS = float(os.getenv("TRAFFIC_POST_RECOVERY_GRACE_SECONDS", "20"))
RESTART_COOLDOWN_SECONDS = float(os.getenv("TRAFFIC_RESTART_COOLDOWN_SECONDS", "30"))
STALE_RESTART_WHEN_REACHABLE_SECONDS = float(os.getenv("TRAFFIC_REACHABLE_STALE_RESTART_SECONDS", "300"))


def log(message: str) -> None:
    print(f"[watchdog] {time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def load_enabled_rtsp_targets() -> list[tuple[str, int]]:
    if not DEEPSTREAM_CONFIG_PATH.exists():
        return []
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(DEEPSTREAM_CONFIG_PATH, encoding="utf-8")
    targets: list[tuple[str, int]] = []
    for section in parser.sections():
        if not section.startswith("source"):
            continue
        if parser.get(section, "enable", fallback="0").strip() != "1":
            continue
        uri = parser.get(section, "uri", fallback="").strip()
        if not uri.lower().startswith("rtsp://"):
            continue
        parsed = urlparse(uri)
        host = parsed.hostname or ""
        port = int(parsed.port or 554)
        if host:
            targets.append((host, port))
    deduped: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in targets:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def can_connect(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _latest_mtime_in_dir(root: Path, patterns: list[str]) -> float | None:
    latest_ts = 0.0
    found = False
    if not root.exists():
        return None
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_ts:
                latest_ts = mtime
                found = True
    return latest_ts if found else None


def latest_data_activity_ts() -> float | None:
    latest_ts = 0.0
    found = False
    for candidate in (
        _latest_mtime_in_dir(QUEUE_CSV_DIR, ["flow_*.csv", "headway_*.csv", "queueLen_*.csv"]),
        _latest_mtime_in_dir(OUTPUT_KITTI_DIR, ["source_*/*.txt"]),
    ):
        if candidate is None:
            continue
        if candidate > latest_ts:
            latest_ts = candidate
            found = True
    return latest_ts if found else None


def terminate_process_tree(proc: subprocess.Popen, timeout: float = 20.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=timeout)
        return
    except Exception:
        pass
    if proc.poll() is None:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def spawn_main() -> subprocess.Popen:
    if not MAIN_SCRIPT.exists():
        raise FileNotFoundError(f"main.py 不存在: {MAIN_SCRIPT}")
    cmd = [sys.executable, str(MAIN_SCRIPT)]
    log(f"starting child process: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=str(SCRIPT_DIR), env=os.environ.copy())


def main() -> int:
    targets = load_enabled_rtsp_targets()
    log(f"enabled rtsp targets: {targets if targets else 'none'}")

    child = spawn_main()
    child_started_at = time.time()
    last_restart_at = 0.0
    reachable_rounds = 0
    disconnect_observed = False
    recovery_started_at: float | None = None

    while True:
        now = time.time()
        exit_code = child.poll()
        if exit_code is not None:
            log(f"child exited with code {exit_code}, requesting service restart")
            return 75

        latest_activity = latest_data_activity_ts()
        idle_seconds = None if latest_activity is None else max(0.0, now - latest_activity)

        reachable_any = False
        if targets:
            reachable_any = any(can_connect(host, port) for host, port in targets)
        if reachable_any:
            reachable_rounds += 1
        else:
            reachable_rounds = 0
            disconnect_observed = True
            recovery_started_at = None

        confirmed_reachable = reachable_rounds >= max(1, REACHABLE_CONFIRM_ROUNDS)
        if disconnect_observed and confirmed_reachable and recovery_started_at is None:
            recovery_started_at = now
            log("network connectivity recovered, waiting for data to resume")

        startup_grace_ok = (now - child_started_at) >= STARTUP_GRACE_SECONDS
        restart_cooldown_ok = (now - last_restart_at) >= RESTART_COOLDOWN_SECONDS

        should_restart = False
        restart_reason = ""

        if startup_grace_ok and restart_cooldown_ok and idle_seconds is not None:
            if recovery_started_at is not None:
                recovered_for = now - recovery_started_at
                if recovered_for >= POST_RECOVERY_GRACE_SECONDS and idle_seconds >= RESTART_ON_RECOVERY_IDLE_SECONDS:
                    should_restart = True
                    restart_reason = (
                        f"network recovered for {recovered_for:.1f}s but data idle for {idle_seconds:.1f}s"
                    )
            elif confirmed_reachable and idle_seconds >= STALE_RESTART_WHEN_REACHABLE_SECONDS:
                should_restart = True
                restart_reason = f"inputs reachable but data idle for {idle_seconds:.1f}s"

        if should_restart:
            log(f"requesting service restart: {restart_reason}")
            terminate_process_tree(child)
            return 76

        time.sleep(max(1.0, MONITOR_INTERVAL_SECONDS))


if __name__ == "__main__":
    raise SystemExit(main())
