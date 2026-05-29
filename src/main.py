#!/usr/bin/env python3
"""
GrowMate Pods - Main Application

Raspberry Pi Zero W plant monitoring system with sensors, camera, and cloud API.

Converted to async architecture with APScheduler for RPI optimization.
- Implemented proper async/await with concurrent operations
- Added APScheduler for independent task scheduling
- Graceful shutdown with signal handling

Integrated structured JSON logging with correlation IDs.
- JSON logs for machine-readable output
- Human-readable console logs with colors
- Correlation IDs for tracing operations across components
- Per-module log levels (hot-reloadable)
"""

import sys
import signal
import logging
import asyncio
from typing import Optional
from pathlib import Path

# APScheduler for task scheduling
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config_manager import ConfigManager
from sensors import SensorReader
from camera_service import CameraService
from actuators import ActuatorController
from api_client import APIClient
from network_manager import NetworkManager
from onboarding_portal import run_onboarding_server
from queue_manager import QueueManager
from upload_processor import UploadProcessor
from health_monitor import HealthMonitor
from config_watcher import ConfigWatcher
from utils import (
    SENSOR_INTERVAL_SECONDS,
    CAMERA_INTERVAL_SECONDS,
    FAILURE_THRESHOLD,
    QUEUE_DATABASE_PATH,
    QUEUE_CLEANUP_INTERVAL,
    QUEUE_MAX_AGE_HOURS,
    FIRMWARE_VERSION
)
# Structured logging with correlation IDs
from logging_config import (
    setup_logging,
    generate_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    update_log_levels
)


logger = logging.getLogger("growmate")


class GrowMateApp:
    """Main GrowMate application with async architecture."""
    
    def __init__(self):
        """Initialize application."""
        self.config_manager = ConfigManager()
        self.config = {}
        
        # Components (initialized in async context)
        self.sensors: Optional[SensorReader] = None
        self.actuators: Optional[ActuatorController] = None
        self.api_client: Optional[APIClient] = None
        self.network: Optional[NetworkManager] = None
        self.camera: Optional[CameraService] = None
        self.queue: Optional[QueueManager] = None
        self.upload_processor: Optional[UploadProcessor] = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.config_watcher: Optional[ConfigWatcher] = None
        
        # Scheduler for independent task scheduling (replaces loop counter)
        self.scheduler: Optional[AsyncIOScheduler] = None
        
        # Async tasks
        self.upload_processor_task: Optional[asyncio.Task] = None  # continuous queue processing
        self.health_monitor_task: Optional[asyncio.Task] = None    # continuous health monitoring
        
        # State tracking
        self.consecutive_failures = 0
        self.shutdown_event = asyncio.Event()
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        # Set shutdown event (will be checked by async loop)
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self.shutdown_event.set)
        except RuntimeError:
            # No event loop running
            pass
    
    def load_configuration(self) -> bool:
        """
        Load configuration from file.
        
        Initializes structured logging after config is loaded.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.config = self.config_manager.load()
            
            # Setup structured logging with device ID
            device_id = self.config.get('device', {}).get('id', 'unknown')
            setup_logging(self.config, device_id=device_id)
            
            logger.info("Configuration loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            # Use default config
            self.config = self.config_manager.get_default_config()
            
            # Setup logging with default config
            device_id = self.config.get('device', {}).get('id', 'unknown')
            setup_logging(self.config, device_id=device_id)
            
            return False
    
    async def initialize_components(self) -> bool:
        """
        Initialize all hardware and software components (async).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Initializing components...")
            
            # Initialize sensors
            self.sensors = SensorReader(self.config)
            logger.info("Sensors initialized")
            
            # Initialize actuators
            self.actuators = ActuatorController()
            await self.actuators.async_start_housekeeping()
            logger.info("Actuators initialized")
            
            # Initialize API client
            self.api_client = APIClient(self.config)
            await self.api_client.initialize()
            logger.info("API client initialized")
            
            # Initialize network manager
            self.network = NetworkManager(self.config)
            logger.info("Network manager initialized")
            
            # Initialize camera (Persistent service)
            # Camera is initialized once and kept alive throughout application lifetime
            self.camera = CameraService(self.config)
            if await self.camera.async_initialize():
                logger.info("Camera service initialized (persistent)")
            else:
                logger.warning("Camera initialization failed, will retry on first capture")
            
            # Initialize queue manager (Offline operation)
            queue_enabled = self.config.get('queue', {}).get('enabled', True)
            if queue_enabled:
                from pathlib import Path
                self.queue = QueueManager(Path(QUEUE_DATABASE_PATH))
                if await self.queue.async_initialize():
                    logger.info("Queue manager initialized (offline operation enabled)")
                else:
                    logger.error("Queue manager initialization failed")
                    return False
                
                # Initialize upload processor
                self.upload_processor = UploadProcessor(self.queue, self.api_client, self.config)
                logger.info("Upload processor initialized")
            else:
                logger.warning("Queue disabled in configuration, running in online-only mode")
            
            # Initialize health monitor (Error handling & monitoring)
            self.health_monitor = HealthMonitor(
                api_client=self.api_client,
                queue_manager=self.queue,
                upload_processor=self.upload_processor
            )
            logger.info("Health monitor initialized")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            return False
    
    def enter_onboarding_mode(self):
        """
        Enter onboarding mode (AP mode with web portal).
        
        This is called when:
        - Device is not provisioned
        - Consecutive failures exceed threshold
        
        Note: Runs synchronously as it's a blocking operation.
        """
        logger.info("Entering onboarding mode")
        
        try:
            # Create temporary network manager for onboarding
            network = NetworkManager(self.config)
            
            # Start AP mode (synchronous)
            if not asyncio.run(network.start_ap_mode()):
                logger.error("Failed to start AP mode")
                return
            
            # Run onboarding web server (blocking)
            run_onboarding_server(self.config)
            
        except Exception as e:
            logger.error(f"Onboarding mode error: {e}")
        finally:
            # Stop AP mode
            try:
                asyncio.run(network.stop_ap_mode())
            except:
                pass
    
    async def sensor_reading_job(self):
        """
        Sensor reading job (scheduled every 15 seconds).
        
        Changed to enqueue data instead of direct upload.
        Upload is handled by continuous upload processor.
        Added correlation ID for tracing operations.
        """
        # Generate and set correlation ID for this cycle
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
        
        try:
            # Read sensors
            sensor_data = await self.sensors.async_read_all_sensors()
            
            if not sensor_data:
                logger.warning("No sensor data available")
                self.consecutive_failures += 1
                return
            
            # Get current actuator state
            current_state = await self.actuators.get_state()
            
            # Enqueue data instead of direct upload
            if self.queue:
                device_id = self.config.get('device', {}).get('id', 'unknown')
                success = await self.queue.async_enqueue_sensor_data(
                    device_id,
                    FIRMWARE_VERSION,
                    sensor_data,
                    current_state
                )
                
                if success:
                    logger.debug("Sensor data enqueued successfully")
                    self.consecutive_failures = 0
                else:
                    logger.warning("Failed to enqueue sensor data")
                    self.consecutive_failures += 1
            else:
                # Fallback: direct upload if queue disabled
                if not await self.network.is_connected():
                    logger.error("WiFi not connected and queue disabled")
                    self.consecutive_failures += 1
                    return
                
                commands = await self.api_client.upload_sensor_data(sensor_data, current_state)
                
                if commands is not None:
                    self.consecutive_failures = 0
                    # Process commands immediately in online-only mode
                    if commands:
                        await self.actuators.process_commands(commands)
                else:
                    self.consecutive_failures += 1
            
        except Exception as e:
            logger.error(f"Sensor reading job error: {e}")
            self.consecutive_failures += 1
        finally:
            # Clear correlation ID after job completes
            clear_correlation_id()
    
    async def camera_capture_job(self):
        """
        Camera capture job (scheduled every 15 minutes).
        
        Uses persistent camera service with EXIF metadata.
        Changed to enqueue images instead of direct upload.
        Added correlation ID for tracing operations.
        """
        # Generate and set correlation ID for this cycle
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
        
        try:
            # Get current sensor data for EXIF metadata (optional)
            sensor_data = None
            try:
                sensor_readings = await self.sensors.async_read_all_sensors()
                if sensor_readings:
                    # Extract temperature and humidity for EXIF
                    sensor_data = {}
                    for reading in sensor_readings:
                        if reading['kind'] == 'temperature':
                            sensor_data['temperature'] = reading['value']
                        elif reading['kind'] == 'air':
                            sensor_data['humidity'] = reading['value']
            except Exception as e:
                logger.warning(f"Failed to get sensor data for EXIF: {e}")
            
            # Capture image with sensor data in EXIF
            image_bytes = await self.camera.async_capture_jpeg(sensor_data)
            
            if not image_bytes:
                logger.warning("Failed to capture image")
                self.consecutive_failures += 1
                return
            
            # Enqueue image instead of direct upload
            if self.queue:
                device_id = self.config.get('device', {}).get('id', 'unknown')
                metadata = {'sensor_data': sensor_data} if sensor_data else None
                
                success = await self.queue.async_enqueue_image(
                    device_id,
                    image_bytes,
                    metadata
                )
                
                if success:
                    logger.info("Camera image enqueued successfully")
                    self.consecutive_failures = 0
                else:
                    logger.warning("Failed to enqueue camera image")
                    self.consecutive_failures += 1
            else:
                # Fallback: direct upload if queue disabled
                if not await self.network.is_connected():
                    logger.error("WiFi not connected and queue disabled")
                    self.consecutive_failures += 1
                    return
                
                success = await self.api_client.upload_camera_image(image_bytes)
                
                if success:
                    logger.info("Camera image uploaded successfully")
                    self.consecutive_failures = 0
                else:
                    logger.warning("Camera image upload failed")
                    self.consecutive_failures += 1
            
        except Exception as e:
            logger.error(f"Camera capture job error: {e}")
            self.consecutive_failures += 1
        finally:
            # Clear correlation ID after job completes
            clear_correlation_id()
    
    async def failure_monitor_job(self):
        """
        Monitor consecutive failures and trigger onboarding if threshold exceeded.
        
        Runs every 30 seconds to check failure count.
        """
        try:
            if self.consecutive_failures >= FAILURE_THRESHOLD:
                logger.warning(
                    f"Repeated network failures detected ({self.consecutive_failures}), "
                    f"reopening onboarding portal"
                )
                
                # Stop scheduler
                if self.scheduler:
                    self.scheduler.shutdown(wait=False)
                
                # Stop upload processor
                if self.upload_processor_task:
                    self.upload_processor_task.cancel()
                    try:
                        await self.upload_processor_task
                    except asyncio.CancelledError:
                        pass
                
                # Cleanup components
                await self.cleanup()
                
                # Enter onboarding mode (synchronous)
                self.enter_onboarding_mode()
                
                # Reload configuration
                self.load_configuration()
                
                # Reinitialize components
                await self.initialize_components()
                
                # Restart scheduler
                await self.setup_scheduler()
                
                # Restart upload processor
                if self.queue and self.upload_processor:
                    self.upload_processor_task = asyncio.create_task(
                        self.upload_processor.run_continuous(self.shutdown_event)
                    )
                
                # Reset failure counter
                self.consecutive_failures = 0
                
        except Exception as e:
            logger.error(f"Failure monitor job error: {e}")
    
    async def queue_cleanup_job(self):
        """
        Queue cleanup job (scheduled every hour).
        
        Removes old entries from queue (>24 hours).
        """
        try:
            if self.queue:
                max_age = self.config.get('queue', {}).get('max_age_hours', QUEUE_MAX_AGE_HOURS)
                sensor_count, image_count = await self.queue.async_cleanup_old_entries(max_age)
                
                if sensor_count > 0 or image_count > 0:
                    logger.info(
                        f"Queue cleanup: removed {sensor_count} sensors, "
                        f"{image_count} images (older than {max_age}h)"
                    )
        except Exception as e:
            logger.error(f"Queue cleanup job error: {e}")
    
    async def queue_stats_job(self):
        """
        Queue statistics monitoring job (scheduled every 5 minutes).
        
        Logs queue depth and statistics.
        """
        try:
            if self.queue:
                stats = await self.queue.async_get_queue_stats()
                
                sensor_queue = stats.get('sensor_queue', {})
                image_queue = stats.get('image_queue', {})
                
                sensor_pending = sensor_queue.get('pending', 0)
                image_pending = image_queue.get('pending', 0)
                
                if sensor_pending > 0 or image_pending > 0:
                    logger.info(
                        f"Queue status: {sensor_pending} sensors pending, "
                        f"{image_pending} images pending"
                    )
                
                # Warn if queue is getting full
                max_sensors = self.config.get('queue', {}).get('max_sensor_entries', 6000)
                max_images = self.config.get('queue', {}).get('max_image_entries', 100)
                
                if sensor_pending > max_sensors * 0.8:
                    logger.warning(
                        f"Sensor queue approaching capacity: {sensor_pending}/{max_sensors}"
                    )
                
                if image_pending > max_images * 0.8:
                    logger.warning(
                        f"Image queue approaching capacity: {image_pending}/{max_images}"
                    )
                
                # Log upload processor stats
                if self.upload_processor:
                    proc_stats = self.upload_processor.get_stats()
                    logger.debug(
                        f"Upload processor stats: "
                        f"{proc_stats['sensor_uploads_success']} sensors uploaded, "
                        f"{proc_stats['image_uploads_success']} images uploaded, "
                        f"{proc_stats['sensor_uploads_failed'] + proc_stats['image_uploads_failed']} failed"
                    )
        except Exception as e:
            logger.error(f"Queue stats job error: {e}")
    
    def _on_config_file_changed(self):
        """
        Wrapper callback for config file changes.
        
        Triggers config_manager.reload() which validates and notifies callbacks.
        """
        try:
            logger.info("Config file changed, reloading...")
            changes = self.config_manager.reload()
            logger.info(f"Config reloaded successfully with {len(changes)} changes")
        except Exception as e:
            logger.error(f"Failed to reload config: {e}", exc_info=True)
    
    def on_config_reload(self, changes: dict):
        """
        Handle configuration reload (hot-reload callback).
        
        Applies reloadable configuration changes without restart.
        Called by config_manager after successful validation.
        
        Args:
            changes: Dictionary of changes {key: (old_value, new_value)}
        """
        logger.info(f"Configuration changed, applying {len(changes)} changes...")
        
        try:
            # Config has already been validated and reloaded by config_manager
            # Just update our reference
            self.config = self.config_manager.config
            
            # Handle interval changes (reschedule jobs)
            if 'intervals.sensor_reading' in changes:
                old_val, new_val = changes['intervals.sensor_reading']
                if self.scheduler:
                    self.scheduler.reschedule_job(
                        'sensor_reading',
                        trigger=IntervalTrigger(seconds=new_val)
                    )
                    logger.info(f"Rescheduled sensor reading job: {old_val}s → {new_val}s")
            
            if 'intervals.camera_capture' in changes:
                old_val, new_val = changes['intervals.camera_capture']
                if self.scheduler:
                    self.scheduler.reschedule_job(
                        'camera_capture',
                        trigger=IntervalTrigger(seconds=new_val)
                    )
                    logger.info(f"Rescheduled camera capture job: {old_val}s → {new_val}s")
            
            # Handle camera settings changes (Hot-reload support)
            camera_changes = {k: v for k, v in changes.items() if k.startswith('camera.')}
            if camera_changes:
                logger.info(f"Camera settings changed: {list(camera_changes.keys())}")
                if self.camera:
                    new_camera_config = self.config.get('camera', {})
                    # Schedule camera config update in event loop
                    asyncio.create_task(self.camera.async_update_config(new_camera_config))
                    logger.info("Camera configuration updated (hot-reload)")
                else:
                    logger.warning("Camera not initialized, changes will apply on next restart")
            
            # Handle retry settings changes (Hot-reload support)
            retry_changes = {k: v for k, v in changes.items() if k.startswith('retry.')}
            if retry_changes:
                logger.info(f"Retry settings changed: {list(retry_changes.keys())}")
                if self.api_client:
                    new_retry_config = self.config.get('retry', {})
                    self.api_client.update_retry_config(new_retry_config)
                    logger.info("Retry configuration updated (hot-reload)")
                else:
                    logger.warning("API client not initialized, changes will apply on next restart")
            
            # Handle circuit breaker settings changes (Hot-reload support)
            cb_changes = {k: v for k, v in changes.items() if k.startswith('circuit_breaker.')}
            if cb_changes:
                logger.info(f"Circuit breaker settings changed: {list(cb_changes.keys())}")
                if self.api_client:
                    new_cb_config = self.config.get('circuit_breaker', {})
                    self.api_client.update_circuit_breaker_config(new_cb_config)
                    logger.info("Circuit breaker configuration updated (hot-reload)")
                else:
                    logger.warning("API client not initialized, changes will apply on next restart")
            
            # Handle logging changes (hot-reloadable)
            logging_changes = {k: v for k, v in changes.items() if k.startswith('logging.')}
            if logging_changes:
                logger.info(f"Logging settings changed: {list(logging_changes.keys())}")
                # Update log levels dynamically without restart
                update_log_levels(self.config)
                logger.info("Log levels updated successfully")
            
            # Handle feature flag changes
            feature_changes = {k: v for k, v in changes.items() if k.startswith('features.')}
            if feature_changes:
                logger.info(f"Feature flags changed: {list(feature_changes.keys())}")
                # Feature flags are read from config on each use, so they take effect immediately
                logger.info("Feature flag changes applied immediately")
            
            logger.info("Configuration reload complete")
            
        except Exception as e:
            logger.error(f"Error applying config changes: {e}", exc_info=True)
    
    async def setup_scheduler(self):
        """
        Setup APScheduler for time-based task scheduling.
        
        Configures independent jobs for sensor reading, camera capture,
        queue cleanup, and health monitoring with proper intervals.
        """
        self.scheduler = AsyncIOScheduler()
        
        # Sensor reading job: every 15 seconds
        self.scheduler.add_job(
            self.sensor_reading_job,
            trigger=IntervalTrigger(seconds=SENSOR_INTERVAL_SECONDS),
            id='sensor_reading',
            name='Sensor Reading',
            max_instances=1,
            coalesce=True
        )
        logger.info(f"Scheduled sensor reading job: every {SENSOR_INTERVAL_SECONDS}s")
        
        # Camera capture job: every 15 minutes
        self.scheduler.add_job(
            self.camera_capture_job,
            trigger=IntervalTrigger(seconds=CAMERA_INTERVAL_SECONDS),
            id='camera_capture',
            name='Camera Capture',
            max_instances=1,
            coalesce=True
        )
        logger.info(f"Scheduled camera capture job: every {CAMERA_INTERVAL_SECONDS}s")
        
        # Failure monitor job: every 30 seconds
        self.scheduler.add_job(
            self.failure_monitor_job,
            trigger=IntervalTrigger(seconds=30),
            id='failure_monitor',
            name='Failure Monitor',
            max_instances=1,
            coalesce=True
        )
        logger.info("Scheduled failure monitor job: every 30s")
        
        # Queue cleanup job (if queue enabled)
        if self.queue:
            cleanup_interval = self.config.get('queue', {}).get('cleanup_interval', QUEUE_CLEANUP_INTERVAL)
            self.scheduler.add_job(
                self.queue_cleanup_job,
                trigger=IntervalTrigger(seconds=cleanup_interval),
                id='queue_cleanup',
                name='Queue Cleanup',
                max_instances=1,
                coalesce=True
            )
            logger.info(f"Scheduled queue cleanup job: every {cleanup_interval}s")
            
            # Queue vacuum job (reclaim disk space weekly)
            self.scheduler.add_job(
                self.queue.async_vacuum,
                trigger=IntervalTrigger(seconds=QUEUE_VACUUM_INTERVAL),
                id='queue_vacuum',
                name='Queue Vacuum',
                max_instances=1,
                coalesce=True
            )
            logger.info(f"Scheduled queue vacuum job: every {QUEUE_VACUUM_INTERVAL}s ({QUEUE_VACUUM_INTERVAL // 86400} days)")
            
            # Queue statistics monitoring: every 5 minutes
            self.scheduler.add_job(
                self.queue_stats_job,
                trigger=IntervalTrigger(seconds=300),
                id='queue_stats',
                name='Queue Statistics',
                max_instances=1,
                coalesce=True
            )
            logger.info("Scheduled queue stats job: every 300s")
        
        # Start scheduler
        self.scheduler.start()
        logger.info("Scheduler started")
    
    async def cleanup(self):
        """Clean up resources (async)."""
        logger.info("Cleaning up resources...")
        
        # Stop config watcher
        if self.config_watcher:
            logger.info("Stopping config watcher...")
            self.config_watcher.stop()
            logger.info("Config watcher stopped")
        
        # Cancel health monitor task
        if self.health_monitor_task:
            logger.info("Stopping health monitor...")
            self.health_monitor_task.cancel()
            try:
                await self.health_monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("Health monitor stopped")
        
        # Cancel upload processor task
        if self.upload_processor_task:
            logger.info("Stopping upload processor...")
            self.upload_processor_task.cancel()
            try:
                await self.upload_processor_task
            except asyncio.CancelledError:
                pass
            logger.info("Upload processor stopped")
        
        if self.actuators:
            await self.actuators.cleanup()
        
        if self.sensors:
            self.sensors.cleanup()
        
        if self.api_client:
            await self.api_client.cleanup()
        
        # Cleanup persistent camera service
        if self.camera:
            await self.camera.async_cleanup()
        
        # Close queue manager
        if self.queue:
            await self.queue.async_close()
            logger.info("Queue manager closed")
        
        logger.info("Cleanup complete")
    
    async def run_async(self):
        """
        Main async application loop.
        
        Replaces the synchronous while loop with async event loop and scheduler.
        Added continuous upload processor task.
        """
        logger.info("Starting async application loop")
        
        try:
            # Initialize components
            if not await self.initialize_components():
                logger.error("Failed to initialize components, exiting")
                return 1
            
            # Setup scheduler (replaces loop counter)
            await self.setup_scheduler()
            
            # Start upload processor task (continuous)
            if self.queue and self.upload_processor:
                self.upload_processor_task = asyncio.create_task(
                    self.upload_processor.run_continuous(self.shutdown_event)
                )
                logger.info("Upload processor task started")
            
            # Start health monitor task (continuous)
            if self.health_monitor:
                from health_monitor import run_health_monitor
                health_check_interval = 300  # 5 minutes
                self.health_monitor_task = asyncio.create_task(
                    run_health_monitor(
                        self.health_monitor,
                        interval=health_check_interval,
                        shutdown_event=self.shutdown_event
                    )
                )
                logger.info(f"Health monitor task started (interval: {health_check_interval}s)")
            
            # Start config watcher (hot-reload)
            hot_reload_enabled = self.config.get('features', {}).get('hot_reload', True)
            if hot_reload_enabled:
                self.config_watcher = ConfigWatcher(
                    config_path=self.config_manager.config_path,
                    callback=self._on_config_file_changed,  # Wrapper that calls config_manager.reload()
                    debounce_seconds=1.0
                )
                loop = asyncio.get_running_loop()
                self.config_watcher.start(loop)
                logger.info("Config watcher started (hot-reload enabled)")
            else:
                logger.info("Config watcher disabled (hot-reload feature flag is off)")
            
            # Wait for shutdown signal
            logger.info("Application running, waiting for shutdown signal...")
            await self.shutdown_event.wait()
            
            logger.info("Shutdown signal received, stopping...")
            
            # Stop scheduler
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
        """
        Main entry point.
        
        - Load configuration
        - Check if provisioned
        - Enter onboarding mode if needed
        - Run async event loop
        """
        logger.info("=" * 60)
        logger.info("GrowMate Pods - Raspberry Pi Zero W")
        logger.info("Web Interface - Minimal Onboarding")
        logger.info("=" * 60)
        
        try:
            # Load configuration
            self.load_configuration()
            
            # Check if provisioned
            if not self.config_manager.is_provisioned():
                logger.info("Device not provisioned, entering onboarding mode")
                self.enter_onboarding_mode()
                # Reload configuration after onboarding
                self.load_configuration()
            
            # Run async event loop
            return asyncio.run(self.run_async())
            
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            return 1


def main():
    """Entry point."""
    app = GrowMateApp()
    sys.exit(app.run())


if __name__ == '__main__':
    main()
