import asyncio
import logging
import subprocess
import time
import os
import signal
from typing import Dict, Optional, List


logger = logging.getLogger("growmate.camera")


CAMERA_DEFAULTS = {
    "port": 8554,
    "width": 640,
    "height": 480,
    "framerate": 15,
    "bitrate": 1000000,
    "profile": "baseline",
    "level": "3.1",
    "denoise": "cdn_off",
    "restart_delay": 0.5,
}


class CameraService:

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self._enabled = cfg.get("enabled", True)
        port = cfg.get("port", CAMERA_DEFAULTS["port"])
        width = cfg.get("width", CAMERA_DEFAULTS["width"])
        height = cfg.get("height", CAMERA_DEFAULTS["height"])
        framerate = cfg.get("framerate", CAMERA_DEFAULTS["framerate"])
        bitrate = cfg.get("bitrate", CAMERA_DEFAULTS["bitrate"])
        profile = cfg.get("profile", CAMERA_DEFAULTS["profile"])
        level = cfg.get("level", CAMERA_DEFAULTS["level"])
        denoise = cfg.get("denoise", CAMERA_DEFAULTS["denoise"])
        self._restart_delay = cfg.get("restart_delay", CAMERA_DEFAULTS["restart_delay"])

        self._port = port

        self._cmd: List[str] = [
            "rpicam-vid", "-t", "0", "--inline", "--listen",
            "-o", f"tcp://0.0.0.0:{port}",
            "--width", str(width),
            "--height", str(height),
            "--framerate", str(framerate),
            "--bitrate", str(bitrate),
            "--profile", profile,
            "--level", level,
            "--denoise", denoise,
        ]

        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self.crash_count = 0
        self.last_crash_time: Optional[float] = None
        self.crash_timestamps: List[float] = []
        self._monitor_task: Optional[asyncio.Task] = None

    def start_stream(self) -> bool:
        if not self._enabled:
            logger.info("Camera disabled in config, skipping stream start")
            return False

        try:
            logger.info(f"Starting rpicam-vid stream (tcp://0.0.0.0:{self._port})...")
            self.process = subprocess.Popen(
                self._cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.running = True
            logger.info(f"rpicam-vid started (PID {self.process.pid})")
            self._try_start_monitoring()
            return True

        except FileNotFoundError:
            logger.error("rpicam-vid not found (install rpicam-apps package)")
            self.running = False
            return False
        except Exception as e:
            logger.error(f"Failed to start rpicam-vid: {e}")
            self.running = False
            return False

    def _is_pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def is_process_alive(self) -> bool:
        if not self.running:
            return False
        if self.process is not None:
            return self.process.poll() is None
        return self._is_pid_alive(self._get_pid()) if self._get_pid() is not None else False

    def _get_pid(self) -> Optional[int]:
        try:
            if self.process is not None and self.process.poll() is None:
                return self.process.pid
        except Exception:
            pass
        return None

    def stop_stream(self):
        self._cancel_monitoring()

        pid = self._get_pid()

        if pid is None:
            self.running = False
            return

        logger.info(f"Stopping rpicam-vid (PID {pid})...")

        try:
            os.kill(pid, signal.SIGTERM)
            self._wait_for_exit(pid, timeout=5)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"Error stopping rpicam-vid: {e}")

        self.running = False
        self.process = None

    def _wait_for_exit(self, pid: int, timeout: float = 5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                return
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass

    def restart_stream(self) -> bool:
        logger.warning(
            f"Restarting rpicam-vid (crash #{self.crash_count + 1})"
        )
        self.stop_stream()
        time.sleep(self._restart_delay)
        success = self.start_stream()
        if success:
            self.crash_count += 1
            self.last_crash_time = time.time()
            self.crash_timestamps.append(time.time())
            cutoff = time.time() - 3600
            self.crash_timestamps = [
                t for t in self.crash_timestamps if t > cutoff
            ]
            logger.info(
                f"rpicam-vid restarted (total crashes: {self.crash_count})"
            )
        return success

    def _try_start_monitoring(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._monitor_task is not None:
            return

        async def _monitor_loop():
            while self.running:
                if self.process is None:
                    await asyncio.sleep(1)
                    continue
                returncode = self.process.poll()
                if returncode is not None:
                    if not self.running:
                        break
                    logger.warning(
                        f"rpicam-vid exited (code {returncode}), restarting..."
                    )
                    self.stop_stream()
                    await asyncio.sleep(self._restart_delay)
                    self.start_stream()
                await asyncio.sleep(1)

        self._monitor_task = loop.create_task(_monitor_loop())

    def _cancel_monitoring(self):
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            self._monitor_task = None

    def get_stream_url(self, tailscale_ip: str) -> str:
        return f"tcp://{tailscale_ip}:{self._port}"

    def get_stats(self) -> Dict:
        now = time.time()
        cutoff = now - 3600
        recent_crashes = sum(1 for t in self.crash_timestamps if t > cutoff)
        alive = self.is_process_alive()
        pid = self._get_pid()
        return {
            "running": self.running,
            "process_alive": alive,
            "crash_count": self.crash_count,
            "recent_crashes_1h": recent_crashes,
            "last_crash_time": self.last_crash_time,
            "pid": pid,
        }

    def cleanup(self):
        logger.info("Camera service cleanup")
        self.stop_stream()
