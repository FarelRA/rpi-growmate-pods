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
        self.camera: Optional[CameraService] = None
        self.actuators: Optional[ActuatorController] = None
        self.api_client: Optional[APIClient] = None
        self.network: Optional[NetworkManager] = None
        
        # State tracking
        self.consecutive_failures = 0
        self.last_sensor_time = 0
        self.last_camera_time = 0
        
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
            
            # Initialize camera
            self.camera = CameraService()
            logger.info("Camera initialized")
            
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
    
    def sensor_cycle(self):
        """
        Execute sensor reading cycle.
        
        - Read all sensors
        - Upload to API
        - Process commands
        - Handle errors
        """
        try:
            # Read sensors
            sensor_data = self.sensors.read_all_sensors()
            
            if not sensor_data:
                logger.warning("No sensor data available")
                self.consecutive_failures += 1
                return
            
            # Get current actuator state
            current_state = self.actuators.get_state()
            
            # Upload to API
            commands = self.api_client.upload_sensor_data(sensor_data, current_state)
            
            # Reset failure counter on success
            self.consecutive_failures = 0
            
            # Process commands
            if commands:
                self.actuators.process_commands(commands)
            
        except Exception as e:
            logger.error(f"Sensor cycle error: {e}")
            self.consecutive_failures += 1
    
    def camera_cycle(self):
        """
        Execute camera capture cycle.
        
        - Capture image
        - Upload to API
        - Handle errors
        """
        try:
            # Capture image
            image_bytes = self.camera.capture_jpeg()
            
            if not image_bytes:
                logger.warning("Failed to capture image")
                return
            
            # Upload to API
            success = self.api_client.upload_camera_image(image_bytes)
            
            if success:
                logger.info("Camera image uploaded successfully")
            else:
                logger.warning("Camera image upload failed")
            
        except Exception as e:
            logger.error(f"Camera cycle error: {e}")
    
    def main_loop(self):
        """
        Main application loop.
        
        - Sensor reading every 15 seconds
        - Camera capture every 15 minutes
        - Command processing
        - Failure tracking
        """
        logger.info("Starting main loop")
        
        self.running = True
        self.last_sensor_time = time.time()
        self.last_camera_time = time.time()
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check if sensor cycle is due
                if current_time - self.last_sensor_time >= SENSOR_INTERVAL_SECONDS:
                    self.sensor_cycle()
                    self.last_sensor_time = current_time
                
                # Check if camera cycle is due
                if current_time - self.last_camera_time >= CAMERA_INTERVAL_SECONDS:
                    self.camera_cycle()
                    self.last_camera_time = current_time
                
                # Check failure threshold
                if self.consecutive_failures >= FAILURE_THRESHOLD:
                    logger.warning(
                        f"Consecutive failures ({self.consecutive_failures}) "
                        f"exceeded threshold ({FAILURE_THRESHOLD})"
                    )
                    logger.info("Re-entering onboarding mode")
                    self.cleanup()
                    self.enter_onboarding_mode()
                    # Reload configuration after onboarding
                    self.load_configuration()
                    self.initialize_components()
                    self.consecutive_failures = 0
                
                # Sleep briefly to avoid busy loop
                time.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(5.0)  # Wait before retrying
    
    def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up resources...")
        
        if self.actuators:
            self.actuators.cleanup()
        
        if self.camera:
            self.camera.cleanup()
        
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
