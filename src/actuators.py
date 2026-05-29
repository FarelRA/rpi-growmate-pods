"""
Actuator control module for GrowMate Pods.

Controls GPIO relays for:
- Water pump (timed duration control)
- Grow light (on/off control)
"""

import time
import logging
import threading
from typing import Optional
from gpiozero import OutputDevice


logger = logging.getLogger("growmate.actuators")


# GPIO pin assignments (from PLAN.md)
PUMP_GPIO = 17
LIGHT_GPIO = 27

# Pump housekeeping interval (from ESP32: 250ms)
PUMP_CHECK_INTERVAL = 0.25  # seconds


class ActuatorController:
    """Controls pump and light actuators via GPIO relays."""
    
    def __init__(self):
        """Initialize actuator controller."""
        # Initialize GPIO outputs (active_high=True for relay control)
        self.pump = OutputDevice(PUMP_GPIO, active_high=True, initial_value=False)
        self.light = OutputDevice(LIGHT_GPIO, active_high=True, initial_value=False)
        
        # Pump state tracking
        self.pump_enabled = False
        self.pump_deadline: Optional[float] = None
        self.pump_lock = threading.Lock()
        
        # Housekeeping thread for pump timeout
        self.housekeeping_thread: Optional[threading.Thread] = None
        self.housekeeping_running = False
        
        logger.info("Actuator controller initialized")
    
    def start_housekeeping(self):
        """Start housekeeping thread for pump timeout management."""
        if self.housekeeping_running:
            return
        
        self.housekeeping_running = True
        self.housekeeping_thread = threading.Thread(
            target=self._housekeeping_loop,
            daemon=True
        )
        self.housekeeping_thread.start()
        logger.info("Actuator housekeeping thread started")
    
    def stop_housekeeping(self):
        """Stop housekeeping thread."""
        self.housekeeping_running = False
        if self.housekeeping_thread:
            self.housekeeping_thread.join(timeout=1.0)
        logger.info("Actuator housekeeping thread stopped")
    
    def _housekeeping_loop(self):
        """
        Housekeeping loop to check pump timeout.
        
        Runs every 250ms (matches ESP32 behavior).
        """
        while self.housekeeping_running:
            try:
                with self.pump_lock:
                    if self.pump_enabled and self.pump_deadline:
                        current_time = time.time()
                        if current_time >= self.pump_deadline:
                            # Timeout reached, turn off pump
                            self.pump.off()
                            self.pump_enabled = False
                            self.pump_deadline = None
                            logger.info("Pump automatically turned off (timeout)")
                
                time.sleep(PUMP_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Housekeeping error: {e}")
    
    def activate_pump(self, duration_ms: int) -> bool:
        """
        Activate water pump for specified duration.
        
        Args:
            duration_ms: Duration in milliseconds
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.pump_lock:
                # Turn on pump
                self.pump.on()
                self.pump_enabled = True
                
                # Set deadline (current time + duration)
                duration_seconds = duration_ms / 1000.0
                self.pump_deadline = time.time() + duration_seconds
                
                logger.info(f"Pump activated for {duration_ms}ms")
                return True
                
        except Exception as e:
            logger.error(f"Failed to activate pump: {e}")
            return False
    
    def deactivate_pump(self) -> bool:
        """
        Manually deactivate water pump.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.pump_lock:
                self.pump.off()
                self.pump_enabled = False
                self.pump_deadline = None
                
                logger.info("Pump manually deactivated")
                return True
                
        except Exception as e:
            logger.error(f"Failed to deactivate pump: {e}")
            return False
    
    def set_light(self, enabled: bool) -> bool:
        """
        Set grow light state.
        
        Args:
            enabled: True to turn on, False to turn off
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if enabled:
                self.light.on()
                logger.info("Grow light turned ON")
            else:
                self.light.off()
                logger.info("Grow light turned OFF")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set light state: {e}")
            return False
    
    def get_state(self) -> dict:
        """
        Get current actuator state.
        
        Returns:
            Dictionary with pump and light states
        """
        with self.pump_lock:
            return {
                'pumpEnabled': self.pump_enabled,
                'lightEnabled': self.light.is_active
            }
    
    def process_commands(self, commands: list) -> None:
        """
        Process commands from API server.
        
        Command format (from ESP32 analysis):
        - {"kind": "pump", "durationMs": 5000}
        - {"kind": "light", "enabled": true}
        
        Args:
            commands: List of command dictionaries
        """
        if not commands:
            return
        
        for cmd in commands:
            kind = cmd.get('kind')
            
            if kind == 'pump':
                duration_ms = cmd.get('durationMs', 0)
                if duration_ms > 0:
                    self.activate_pump(duration_ms)
                else:
                    logger.warning(f"Invalid pump duration: {duration_ms}")
            
            elif kind == 'light':
                enabled = cmd.get('enabled', False)
                self.set_light(enabled)
            
            else:
                logger.warning(f"Unknown command kind: {kind}")
    
    def cleanup(self):
        """Clean up actuator resources."""
        self.stop_housekeeping()
        
        # Turn off all actuators
        try:
            self.pump.off()
            self.light.off()
            self.pump.close()
            self.light.close()
            logger.info("Actuator cleanup complete")
        except Exception as e:
            logger.warning(f"Actuator cleanup error: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        self.start_housekeeping()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()
