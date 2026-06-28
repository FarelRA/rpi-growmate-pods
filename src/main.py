#!/usr/bin/env python3
"""GrowMate V2 Pods — Main Application Loop."""

import os
import re
import sys
import signal
import logging
import asyncio
import subprocess
import threading
from typing import Optional
from pathlib import Path


# ── Load .env file if present ─────────────────────────────────────────────────
# Searches project root, script dir, then $HOME.
# Skips when running under pytest to avoid polluting test environment.
def _load_dotenv() -> None:
    if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
        return
    for candidate in (
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
        Path.home() / ".env",
    ):
        if candidate.is_file():
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip().strip("\"'")
                    if key and key not in os.environ:
                        os.environ[key] = val
            break

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

sys.path.insert(0, str(Path(__file__).parent))

from config_manager import ConfigManager
from sensors import SensorReader
from actuators import ActuatorController
from api_client import APIClient
from camera_service import CameraService
from network_manager import NetworkManager
from onboarding_portal import run_onboarding_server
from queue_manager import QueueManager
from upload_processor import UploadProcessor
from health_monitor import HealthMonitor, run_health_monitor
from config_watcher import ConfigWatcher
from utils import (
    SENSOR_INTERVAL_SECONDS,
    FAILURE_THRESHOLD,
    QUEUE_DATABASE_PATH,
    QUEUE_CLEANUP_INTERVAL,
    QUEUE_MAX_AGE_HOURS,
    FIRMWARE_VERSION,
)
from logging_config import (
    setup_logging,
    generate_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    update_log_levels,
)


logger = logging.getLogger("growmate")


class GrowMateApp:

    def __init__(self):
        _load_dotenv()
        self.config_manager = ConfigManager()
        self.config = {}

        self.sensors: Optional[SensorReader] = None
        self.actuators: Optional[ActuatorController] = None
        self.api_client: Optional[APIClient] = None
        self.camera: Optional[CameraService] = None
        self.network: Optional[NetworkManager] = None
        self.queue: Optional[QueueManager] = None
        self.upload_processor: Optional[UploadProcessor] = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.config_watcher: Optional[ConfigWatcher] = None

        self.scheduler: Optional[AsyncIOScheduler] = None

        self.upload_processor_task: Optional[asyncio.Task] = None
        self.health_monitor_task: Optional[asyncio.Task] = None

        self.consecutive_failures = 0
        self.shutdown_event = asyncio.Event()
        self._onboarding_complete = threading.Event()

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self.shutdown_event.set)
        except RuntimeError:
            pass
        self._onboarding_complete.set()

    def load_configuration(self) -> bool:
        try:
            self.config = self.config_manager.load()

            device_id = self.config.get('device', {}).get('id', 'unknown')
            setup_logging(self.config, device_id=device_id)

            logger.info("Configuration loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            self.config = self.config_manager.get_default_config()

            device_id = self.config.get('device', {}).get('id', 'unknown')
            setup_logging(self.config, device_id=device_id)

            return False

    async def initialize_components(self) -> None:
        logger.info("Initializing components...")

        try:
            import RPi.GPIO as _GPIO
            _GPIO.setmode(_GPIO.BCM)
            act_cfg = self.config.get('actuators', {}).get('pins', {})
            for _pin in [act_cfg.get(k, 0) for k in ('pump', 'fertilizer', 'pesticide')]:
                if _pin:
                    _GPIO.setup(_pin, _GPIO.OUT, initial=_GPIO.LOW)
                    _GPIO.output(_pin, _GPIO.LOW)
            _GPIO.cleanup()
        except Exception as e:
            logger.warning(f"GPIO init failed: {e}")

        try:
            sensors_cfg = self.config.get('sensors', {})
            self.sensors = SensorReader(sensors_cfg)
            logger.info("Sensors initialized")
        except Exception as e:
            logger.warning(f"Sensors init failed: {e}")

        try:
            actuators_cfg = self.config.get('actuators', {})
            self.actuators = ActuatorController(actuators_cfg)
            logger.info("Actuators initialized")
        except Exception as e:
            logger.warning(f"Actuators init failed: {e}")

        try:
            self.api_client = APIClient(self.config)
            await self.api_client.initialize()
            logger.info("API client initialized")
        except Exception as e:
            logger.warning(f"API client init failed: {e}")
            self.api_client = None

        try:
            camera_cfg = self.config.get('camera', {})
            self.camera = CameraService(camera_cfg)
            if self.camera.start_stream():
                logger.info("Camera stream initialized")
            else:
                logger.warning("Camera stream failed to start, watchdog will retry")
        except Exception as e:
            logger.warning(f"Camera init failed: {e}")
            self.camera = None

        try:
            self.network = NetworkManager(self.config)
            logger.info("Network manager initialized")
        except Exception as e:
            logger.warning(f"Network manager init failed: {e}")
            self.network = None

        try:
            queue_enabled = self.config.get('queue', {}).get('enabled', True)
            if queue_enabled:
                db_path = Path(
                    self.config.get('queue', {}).get('db_path', QUEUE_DATABASE_PATH)
                )
                max_entries = self.config.get('queue', {}).get('max_sensor_entries', 1440)
                self.queue = QueueManager(db_path, max_sensor_entries=max_entries)
                if await self.queue.async_initialize():
                    logger.info("Queue manager initialized")
                else:
                    logger.warning("Queue manager init failed")
                    self.queue = None
                if self.queue:
                    self.upload_processor = UploadProcessor(self.queue, self.api_client, self.config)
                    logger.info("Upload processor initialized")
            else:
                logger.warning("Queue disabled, running in online-only mode")
        except Exception as e:
            logger.warning(f"Queue init failed: {e}")
            self.queue = None

        try:
            self.health_monitor = HealthMonitor(
                api_client=self.api_client,
                queue_manager=self.queue,
                upload_processor=self.upload_processor,
                camera_service=self.camera,
            )
            hm_cfg = self.config.get('health_monitor', {})
            if hm_cfg.get('history_size'):
                self.health_monitor.max_history_size = hm_cfg['history_size']
            if hm_cfg.get('camera_crash_threshold'):
                self.health_monitor._camera_crash_threshold = hm_cfg['camera_crash_threshold']
            logger.info("Health monitor initialized")
        except Exception as e:
            logger.warning(f"Health monitor init failed: {e}")
            self.health_monitor = None

    async def enter_onboarding_mode(self, network: Optional[NetworkManager] = None):
        logger.info("Entering onboarding mode (AP mode + web portal)")

        if network is None:
            network = NetworkManager(self.config)

        try:
            if not await network.start_ap_mode():
                logger.error("Failed to start AP mode")
                return

            self._onboarding_complete.clear()

            portal_thread = threading.Thread(
                target=run_onboarding_server,
                kwargs={
                    'config': self.config,
                    'network_mgr': network,
                    'callback': self._onboarding_complete.set,
                },
                daemon=True,
            )
            portal_thread.start()

            await asyncio.to_thread(self._onboarding_complete.wait)
            logger.info("Onboarding complete, stopping AP mode")

            portal_thread.join(timeout=5)

            await network.stop_ap_mode()

            await self._connect_onboarding_wifi(network)

        except Exception as e:
            logger.error(f"Onboarding mode error: {e}")
            try:
                await network.stop_ap_mode()
            except Exception:
                pass

    async def _connect_onboarding_wifi(self, network: NetworkManager):
        try:
            ssid = self.config_manager.get('network.wifi_ssid', '')
            password = self.config_manager.get('network.wifi_password', '')
            if ssid and await network.connect_to_wifi(ssid, password):
                self.config_manager.set('network.provisioned', True)
                self.config_manager.save()
                logger.info(f"Connected to WiFi: {ssid}")
        except Exception as e:
            logger.warning(f"Failed to connect to WiFi after onboarding: {e}")

    async def _get_tailscale_ip(self) -> Optional[str]:
        try:
            result = await asyncio.create_subprocess_exec(
                "tailscale", "ip", "-4",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()
            if result.returncode == 0:
                ip = stdout.decode().strip()
                if ip:
                    return ip
            logger.warning(f"Failed to get Tailscale IP: {stderr.decode().strip()}")
        except FileNotFoundError:
            logger.warning("tailscale command not found (not installed or not a Pi)")
        except Exception as e:
            logger.warning(f"Failed to get Tailscale IP: {e}")

        return None

    async def _register_stream_with_retry(self):
        if not self.api_client:
            return

        tailscale_ip = await self._get_tailscale_ip()
        if not tailscale_ip:
            tailscale_ip = "127.0.0.1"
            logger.info(
                f"Tailscale IP not available, using {tailscale_ip} "
                "(stream registration will be attempted with this IP)"
            )

        stream_url = f"tcp://{tailscale_ip}:{self.camera._port if self.camera else 8554}"
        sr_cfg = self.config.get('stream_registration', {})
        max_attempts = sr_cfg.get('max_attempts', 10)
        base_delay = sr_cfg.get('base_delay', 1.0)
        max_delay = sr_cfg.get('max_delay', 60.0)

        for attempt in range(1, max_attempts + 1):
            if self.shutdown_event.is_set():
                return

            logger.info(
                f"Stream registration attempt {attempt}/{max_attempts}: {stream_url}"
            )
            success = await self.api_client.register_stream(stream_url)

            if success:
                logger.info(f"Stream registered successfully: {stream_url}")
                return

            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.warning(
                    f"Stream registration failed, retrying in {delay:.0f}s "
                    f"(attempt {attempt}/{max_attempts})"
                )
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=delay,
                    )
                    return
                except asyncio.TimeoutError:
                    pass

        logger.error(
            f"Stream registration failed after {max_attempts} attempts"
        )

    async def sensor_reading_job(self):
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)

        try:
            sensor_data = await self.sensors.async_read_all_sensors()

            if not sensor_data:
                logger.warning("No sensor data available")
                self.consecutive_failures += 1
                return

            actuator_state = await self.actuators.async_get_state()
            current_state = await self.sensors.async_get_current_state(actuator_state)

            if self.queue:
                device_id = self.api_client.device_id
                success = await self.queue.async_enqueue_sensor_data(
                    device_id,
                    FIRMWARE_VERSION,
                    sensor_data,
                    current_state,
                )

                if success:
                    logger.debug("Sensor data enqueued successfully")
                    self.consecutive_failures = 0
                else:
                    logger.warning("Failed to enqueue sensor data")
                    self.consecutive_failures += 1
            else:
                if self.network and not await self.network.is_connected():
                    logger.error("WiFi not connected and queue disabled")
                    self.consecutive_failures += 1
                    return

                commands = await self.api_client.upload_sensor_data(
                    sensor_data, current_state
                )

                if commands is not None:
                    self.consecutive_failures = 0
                    if commands:
                        await self.actuators.async_process_commands(commands)
                else:
                    self.consecutive_failures += 1

        except Exception as e:
            logger.error(f"Sensor reading job error: {e}")
            self.consecutive_failures += 1
        finally:
            clear_correlation_id()

    async def failure_monitor_job(self):
        try:
            threshold = self.config.get('failure', {}).get('consecutive_threshold', FAILURE_THRESHOLD)
            if self.consecutive_failures >= threshold:
                logger.warning(
                    f"Repeated failures detected ({self.consecutive_failures}), "
                    f"re-entering onboarding mode"
                )

                if self.scheduler:
                    self.scheduler.shutdown(wait=False)

                if self.upload_processor_task:
                    self.upload_processor_task.cancel()
                    try:
                        await self.upload_processor_task
                    except asyncio.CancelledError:
                        pass

                await self.cleanup()

                await self.enter_onboarding_mode()

                self.load_configuration()

                if await self.initialize_components():
                    await self.setup_scheduler()

                    if self.queue and self.upload_processor:
                        self.upload_processor_task = asyncio.create_task(
                            self.upload_processor.run_continuous(self.shutdown_event)
                        )

                self.consecutive_failures = 0
        except Exception as e:
            logger.error(f"Failure monitor job error: {e}")

    async def camera_watchdog_job(self):
        if not self.camera:
            return

        try:
            if not self.camera.is_process_alive():
                logger.warning("rpicam-vid process died, restarting...")
                restarted = await asyncio.to_thread(self.camera.restart_stream)
                if restarted:
                    logger.info("rpicam-vid restarted successfully")
                    await self._register_stream_with_retry()
        except Exception as e:
            logger.error(f"Camera watchdog error: {e}")

    async def queue_cleanup_job(self):
        try:
            if self.queue:
                max_age = self.config.get('queue', {}).get(
                    'max_age_hours', QUEUE_MAX_AGE_HOURS
                )
                sensor_count = await self.queue.async_cleanup_old_entries(max_age)

                if sensor_count > 0:
                    logger.info(
                        f"Queue cleanup: removed {sensor_count} sensors "
                        f"(older than {max_age}h)"
                    )
        except Exception as e:
            logger.error(f"Queue cleanup job error: {e}")

    async def queue_stats_job(self):
        try:
            if self.queue:
                stats = await self.queue.async_get_queue_stats()

                sensor_queue = stats.get('sensor_queue', {})
                sensor_pending = sensor_queue.get('pending', 0)

                if sensor_pending > 0:
                    logger.info(
                        f"Queue status: {sensor_pending} sensors pending"
                    )

                max_sensors = self.config.get('queue', {}).get(
                    'max_sensor_entries', 1440
                )

                if sensor_pending > max_sensors * 0.8:
                    logger.warning(
                        f"Sensor queue approaching capacity: "
                        f"{sensor_pending}/{max_sensors}"
                    )

                if self.upload_processor:
                    proc_stats = self.upload_processor.get_stats()
                    logger.debug(
                        f"Upload processor stats: "
                        f"{proc_stats['sensor_uploads_success']} sensors uploaded, "
                        f"{proc_stats['sensor_uploads_failed']} failed, "
                        f"{proc_stats['total_processed']} total"
                    )
        except Exception as e:
            logger.error(f"Queue stats job error: {e}")

    def _on_config_file_changed(self):
        try:
            logger.info("Config file changed, reloading...")
            changes = self.config_manager.reload()
            logger.info(f"Config reloaded successfully with {len(changes)} changes")
            if changes:
                self.on_config_reload(changes)
        except Exception as e:
            logger.error(f"Failed to reload config: {e}", exc_info=True)

    def on_config_reload(self, changes: dict):
        logger.info(f"Configuration changed, applying {len(changes)} changes...")

        try:
            self.config = self.config_manager.config

            if 'intervals.sensor_reading' in changes:
                old_val, new_val = changes['intervals.sensor_reading']
                if self.scheduler:
                    self.scheduler.reschedule_job(
                        'sensor_reading',
                        trigger=IntervalTrigger(seconds=new_val),
                    )
                    logger.info(
                        f"Rescheduled sensor reading job: {old_val}s -> {new_val}s"
                    )

            retry_changes = {
                k: v for k, v in changes.items() if k.startswith('retry.')
            }
            if retry_changes:
                logger.info(f"Retry settings changed: {list(retry_changes.keys())}")
                if self.api_client:
                    self.api_client.update_retry_config(
                        self.config.get('retry', {})
                    )
                    logger.info("Retry configuration updated (hot-reload)")

            cb_changes = {
                k: v
                for k, v in changes.items()
                if k.startswith('circuit_breaker.')
            }
            if cb_changes:
                logger.info(
                    f"Circuit breaker settings changed: {list(cb_changes.keys())}"
                )
                if self.api_client:
                    self.api_client.update_circuit_breaker_config(
                        self.config.get('circuit_breaker', {})
                    )
                    logger.info("Circuit breaker configuration updated (hot-reload)")

            logging_changes = {
                k: v for k, v in changes.items() if k.startswith('logging.')
            }
            if logging_changes:
                logger.info(f"Logging settings changed: {list(logging_changes.keys())}")
                update_log_levels(self.config)
                logger.info("Log levels updated successfully")

            feature_changes = {
                k: v for k, v in changes.items() if k.startswith('features.')
            }
            if feature_changes:
                logger.info(
                    f"Feature flags changed: {list(feature_changes.keys())}"
                )
                logger.info("Feature flag changes applied immediately")

            logger.info("Configuration reload complete")

        except Exception as e:
            logger.error(f"Error applying config changes: {e}", exc_info=True)

    async def setup_scheduler(self):
        self.scheduler = AsyncIOScheduler()

        intervals = self.config.get('intervals', {})
        sensor_interval = intervals.get('sensor_reading', SENSOR_INTERVAL_SECONDS)
        failure_interval = intervals.get('failure_monitor', 30)
        watchdog_interval = intervals.get('camera_watchdog', 30)
        cleanup_interval = intervals.get('queue_cleanup',
            self.config.get('queue', {}).get('cleanup_interval', QUEUE_CLEANUP_INTERVAL))
        vacuum_interval = intervals.get('queue_vacuum',
            self.config.get('queue', {}).get('vacuum_interval', 604800))
        stats_interval = intervals.get('queue_stats', 300)
        health_check_interval = intervals.get('health_check', 300)

        self.scheduler.add_job(
            self.sensor_reading_job,
            trigger=IntervalTrigger(seconds=sensor_interval),
            id='sensor_reading',
            name='Sensor Reading',
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"Scheduled sensor reading job: every {sensor_interval}s")

        self.scheduler.add_job(
            self.failure_monitor_job,
            trigger=IntervalTrigger(seconds=failure_interval),
            id='failure_monitor',
            name='Failure Monitor',
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"Scheduled failure monitor job: every {failure_interval}s")

        self.scheduler.add_job(
            self.camera_watchdog_job,
            trigger=IntervalTrigger(seconds=watchdog_interval),
            id='camera_watchdog',
            name='Camera Watchdog',
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"Scheduled camera watchdog job: every {watchdog_interval}s")

        if self.queue:
            self.scheduler.add_job(
                self.queue_cleanup_job,
                trigger=IntervalTrigger(seconds=cleanup_interval),
                id='queue_cleanup',
                name='Queue Cleanup',
                max_instances=1,
                coalesce=True,
            )
            logger.info(f"Scheduled queue cleanup job: every {cleanup_interval}s")

            self.scheduler.add_job(
                self.queue.async_vacuum,
                trigger=IntervalTrigger(seconds=vacuum_interval),
                id='queue_vacuum',
                name='Queue Vacuum',
                max_instances=1,
                coalesce=True,
            )
            logger.info(f"Scheduled queue vacuum job: every {vacuum_interval}s")

            self.scheduler.add_job(
                self.queue_stats_job,
                trigger=IntervalTrigger(seconds=stats_interval),
                id='queue_stats',
                name='Queue Statistics',
                max_instances=1,
                coalesce=True,
            )
            logger.info(f"Scheduled queue stats job: every {stats_interval}s")

        self.scheduler.start()
        logger.info("Scheduler started")

    async def cleanup(self):
        logger.info("Cleaning up resources...")

        if self.config_watcher:
            logger.info("Stopping config watcher...")
            self.config_watcher.stop()
            logger.info("Config watcher stopped")

        if self.health_monitor_task:
            logger.info("Stopping health monitor...")
            self.health_monitor_task.cancel()
            try:
                await self.health_monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("Health monitor stopped")

        if self.upload_processor_task:
            logger.info("Stopping upload processor...")
            self.upload_processor_task.cancel()
            try:
                await self.upload_processor_task
            except asyncio.CancelledError:
                pass
            logger.info("Upload processor stopped")

        if self.actuators:
            try:
                await self.actuators.async_cleanup()
            except Exception as e:
                logger.warning(f"Actuator cleanup error: {e}")

        if self.sensors:
            try:
                self.sensors.cleanup()
            except Exception as e:
                logger.warning(f"Sensor cleanup error: {e}")

        if self.camera:
            try:
                logger.info("Stopping camera stream...")
                self.camera.cleanup()
                logger.info("Camera stream stopped")
            except Exception as e:
                logger.warning(f"Camera cleanup error: {e}")

        if self.network:
            logger.info("Stopping AP mode if active...")
            try:
                await self.network.stop_ap_mode()
            except Exception:
                pass

        if self.api_client:
            try:
                await self.api_client.cleanup()
            except Exception as e:
                logger.warning(f"API client cleanup error: {e}")

        if self.queue:
            try:
                await self.queue.async_close()
                logger.info("Queue manager closed")
            except Exception as e:
                logger.warning(f"Queue cleanup error: {e}")

        logger.info("Cleanup complete")

    async def run_async(self):
        logger.info("Starting async application loop (V2)")

        try:
            await self.initialize_components()

            await self._register_stream_with_retry()

            await self.setup_scheduler()

            if self.queue and self.upload_processor:
                self.upload_processor_task = asyncio.create_task(
                    self.upload_processor.run_continuous(self.shutdown_event)
                )
                logger.info("Upload processor task started")

            if self.health_monitor:
                health_check_interval = self.config.get('intervals', {}).get('health_check', 300)
                self.health_monitor_task = asyncio.create_task(
                    run_health_monitor(
                        self.health_monitor,
                        interval=health_check_interval,
                        shutdown_event=self.shutdown_event,
                    )
                )
                logger.info(
                    f"Health monitor task started (interval: {health_check_interval}s)"
                )

            hot_reload_enabled = self.config.get(
                'features', {}
            ).get('hot_reload', True)
            if hot_reload_enabled:
                self.config_watcher = ConfigWatcher(
                    config_path=self.config_manager.config_path,
                    callback=self._on_config_file_changed,
                    debounce_seconds=1.0,
                )
                loop = asyncio.get_running_loop()
                self.config_watcher.start(loop)
                logger.info("Config watcher started (hot-reload enabled)")
            else:
                logger.info("Config watcher disabled (hot-reload feature flag is off)")

            logger.info("Application running, waiting for shutdown signal...")
            await self.shutdown_event.wait()

            logger.info("Shutdown signal received, stopping...")

            if self.scheduler:
                self.scheduler.shutdown(wait=True)
                logger.info("Scheduler stopped")

            return 0

        except Exception as e:
            logger.error(f"Fatal error in async loop: {e}", exc_info=True)
            return 1

        finally:
            await self.cleanup()

    def run(self):
        logger.info("=" * 60)
        logger.info("GrowMate V2 Pods - Raspberry Pi Zero W")
        logger.info("Web Interface - Minimal Onboarding (AP mode)")
        logger.info("=" * 60)

        try:
            self.load_configuration()

            if not self.config_manager.is_provisioned():
                logger.info("Device not provisioned — dormant AP mode only")
                asyncio.run(self.enter_onboarding_mode())
                logger.info("Onboarding complete, exiting for restart with full stack")
                return 0

            return asyncio.run(self.run_async())

        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            return 1


def main():
    app = GrowMateApp()
    sys.exit(app.run())


if __name__ == '__main__':
    main()
