#!/usr/bin/env python3
"""
GrowMate Pods - Main Application

Raspberry Pi Zero W plant monitoring system with sensors, camera, and cloud API.
"""

import sys
import time
import signal
import logging
from typing import Optional
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config_manager import ConfigManager
from sensors import SensorReader
from camera_service import CameraService
from actuators import ActuatorController
from api_client import APIClient
from network_manager import NetworkManager
from onboarding_portal import run_onboarding_server
from utils import (
    setup_logging,
    SENSOR_INTERVAL_SECONDS,
    CAMERA_INTERVAL_SECONDS,
    FAILURE_THRESHOLD
)


logger = setup_logging("growmate")


class GrowMateApp:
    """Main GrowMate application."""
    
    def __init__(self):
        """Initialize application."""
        self.running = False
        self.config_manager = ConfigManager()
        self.config = {}
        
        # Components
        self.sensors: Optional[SensorReader] = None
        self.actuators: Optional[ActuatorController] = None
        self.api_client: Optional[APIClient] = None
        self.network: Optional[NetworkManager] = None
        
        # State tracking
        self.consecutive_failures = 0
        self.loops_since_camera = 0  # Match ESP32 loop counter approach
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def load_configuration(self) -> bool:
        """
        Load configuration from file.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.config = self.config_manager.load()
            logger.info("Configuration loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            # Use default config
            self.config = self.config_manager.get_default_config()
            return False
    
    def initialize_components(self) -> bool:
        """
        Initialize all hardware and software components.
        
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
            self.actuators.start_housekeeping()
            logger.info("Actuators initialized")
            
            # Initialize API client
            self.api_client = APIClient(self.config)
            logger.info("API client initialized")
            
            # Initialize network manager
            self.network = NetworkManager(self.config)
            logger.info("Network manager initialized")
            
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
        """
        logger.info("Entering onboarding mode")
        
        try:
            # Start AP mode
            if not self.network.start_ap_mode():
                logger.error("Failed to start AP mode")
                return
            
            # Run onboarding web server (blocking)
            run_onboarding_server(self.config)
            
        except Exception as e:
            logger.error(f"Onboarding mode error: {e}")
        finally:
            # Stop AP mode
            self.network.stop_ap_mode()
    
    def sensor_cycle(self) -> bool:
        """
        Execute sensor reading cycle.
        
        Matches ESP32 behavior:
        - Read all sensors
        - Check WiFi connection
        - Upload to API
        - Process commands
        - Handle errors
        
        Returns:
            True if successful, False on failure
        """
        try:
            # Read sensors
            sensor_data = self.sensors.read_all_sensors()
            
            if not sensor_data:
                logger.warning("No sensor data available")
                self.consecutive_failures += 1
                return False
            
            # Check WiFi connection (ESP32 connects at start of each cycle)
            if not self.network.is_connected():
                logger.error("WiFi not connected")
                self.consecutive_failures += 1
                return False
            
            # Get current actuator state
            current_state = self.actuators.get_state()
            
            # Upload to API
            commands = self.api_client.upload_sensor_data(sensor_data, current_state)
            
            # Reset failure counter on success
            self.consecutive_failures = 0
            
            # Process commands (ESP32 applies commands immediately after upload)
            if commands:
                self.actuators.process_commands(commands)
            
            return True
            
        except Exception as e:
            logger.error(f"Sensor cycle error: {e}")
            self.consecutive_failures += 1
            return False
    
    def camera_cycle(self) -> bool:
        """
        Execute camera capture cycle.
        
        Matches ESP32 behavior:
        - Initialize camera (ephemeral)
        - Capture image
        - Deinitialize camera
        - Check WiFi connection
        - Upload to API
        - Handle errors
        
        Returns:
            True if successful, False on failure
        """
        camera = None
        try:
            # Initialize camera (ESP32: camera_service_init)
            camera = CameraService()
            if not camera.initialize():
                logger.error("Failed to initialize camera")
                self.consecutive_failures += 1
                return False
            
            # Capture image (ESP32: camera_service_capture)
            image_bytes = camera.capture_jpeg()
            
            # Deinitialize camera immediately (ESP32: camera_service_deinit)
            camera.cleanup()
            camera = None
            
            if not image_bytes:
                logger.warning("Failed to capture image")
                self.consecutive_failures += 1
                return False
            
            # Check WiFi connection
            if not self.network.is_connected():
                logger.error("WiFi not connected")
                self.consecutive_failures += 1
                return False
            
            # Upload to API
            success = self.api_client.upload_camera_image(image_bytes)
            
            if success:
                logger.info("Camera image uploaded successfully")
                # Reset failure counter on success (ESP32 behavior)
                self.consecutive_failures = 0
                return True
            else:
                logger.warning("Camera image upload failed")
                self.consecutive_failures += 1
                return False
            
        except Exception as e:
            logger.error(f"Camera cycle error: {e}")
            self.consecutive_failures += 1
            return False
        finally:
            # Ensure camera is cleaned up even on error
            if camera:
                camera.cleanup()
    
    def main_loop(self):
        """
        Main application loop.
        
        Matches ESP32 behavior:
        - Sensor reading every 15 seconds
        - Camera capture every 60 sensor cycles (15 minutes)
        - Command processing after sensor upload
        - Failure tracking with AP mode fallback
        """
        logger.info("Starting main loop")
        
        self.running = True
        self.loops_since_camera = 0
        self.consecutive_failures = 0
        
        # Calculate camera period (ESP32: APP_CAMERA_INTERVAL_SEC / APP_SENSOR_INTERVAL_SEC)
        camera_period = CAMERA_INTERVAL_SECONDS // SENSOR_INTERVAL_SECONDS
        if camera_period == 0:
            camera_period = 1
        
        logger.info(f"Camera will capture every {camera_period} sensor cycles")
        
        while self.running:
            try:
                # Increment camera loop counter (ESP32: loops_since_camera++)
                self.loops_since_camera += 1
                
                # Check if camera cycle is due (ESP32: loops_since_camera >= camera_period)
                camera_due = self.loops_since_camera >= camera_period
                
                # Execute sensor cycle (every loop = every 15 seconds)
                sensor_success = self.sensor_cycle()
                
                # Execute camera cycle if due
                if camera_due:
                    camera_success = self.camera_cycle()
                    # Only reset counter on successful upload (ESP32 behavior)
                    if camera_success:
                        self.loops_since_camera = 0
                
                # Check failure threshold (ESP32: >= APP_ONBOARDING_FAILURE_THRESHOLD)
                if self.consecutive_failures >= FAILURE_THRESHOLD:
                    logger.warning(
                        f"Repeated network failures detected ({self.consecutive_failures}), "
                        f"reopening onboarding portal"
                    )
                    self.cleanup()
                    self.enter_onboarding_mode()
                    # Reload configuration after onboarding
                    self.load_configuration()
                    self.initialize_components()
                    self.consecutive_failures = 0
                    self.loops_since_camera = 0
                
                # Delay until next sensor cycle (ESP32: delay_with_housekeeping)
                # ESP32 breaks delay into 250ms chunks and calls actuators_tick()
                # Our actuators.start_housekeeping() already handles this in background
                time.sleep(SENSOR_INTERVAL_SECONDS)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                self.consecutive_failures += 1
                time.sleep(5.0)  # Wait before retrying
    
    def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up resources...")
        
        if self.actuators:
            self.actuators.cleanup()
        
        if self.sensors:
            self.sensors.cleanup()
        
        logger.info("Cleanup complete")
    
    def run(self):
        """
        Main entry point.
        
        - Load configuration
        - Check if provisioned
        - Enter onboarding mode if needed
        - Initialize components
        - Run main loop
        """
        logger.info("=" * 60)
        logger.info("GrowMate Pods - Raspberry Pi Zero W")
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
            
            # Initialize components
            if not self.initialize_components():
                logger.error("Failed to initialize components, exiting")
                return 1
            
            # Run main loop
            self.main_loop()
            
            return 0
            
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            return 1
        
        finally:
            self.cleanup()


def main():
    """Entry point."""
    app = GrowMateApp()
    sys.exit(app.run())


if __name__ == '__main__':
    main()
