"""
Actuator control module for GrowMate Pods.

Controls GPIO relays for:
- Water pump (timed duration control)
- Grow light (on/off control)

Converted from threading to asyncio for better integration with async architecture.
"""

import time
import logging
import asyncio
from typing import Optional
from gpiozero import OutputDevice


logger = logging.getLogger("growmate.actuators")


# GPIO pin assignments (from PLAN.md)
PUMP_GPIO = 17
LIGHT_GPIO = 27

# Pump housekeeping interval
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
        self.pump_lock = asyncio.Lock()  # Changed from threading.Lock to asyncio.Lock
        
        # Housekeeping task for pump timeout (changed from thread to asyncio task)
        self.housekeeping_task: Optional[asyncio.Task] = None
        self.housekeeping_running = False
        
        logger.info("Actuator controller initialized")
    
    def start_housekeeping(self):
        """Start housekeeping task for pump timeout management (async version)."""
        if self.housekeeping_running:
            return
        
        self.housekeeping_running = True
        # Create async task (will be started by event loop)
        try:
            loop = asyncio.get_running_loop()
            self.housekeeping_task = loop.create_task(self._housekeeping_loop())
            logger.info("Actuator housekeeping task started")
        except RuntimeError:
            # No event loop running yet, task will be created later
            logger.warning("No event loop running, housekeeping task will be created later")
    
    async def async_start_housekeeping(self):
        """Start housekeeping task for pump timeout management (async version)."""
        if self.housekeeping_running:
            return
        
        self.housekeeping_running = True
        self.housekeeping_task = asyncio.create_task(self._housekeeping_loop())
        logger.info("Actuator housekeeping task started")
    
    async def stop_housekeeping(self):
        """Stop housekeeping task (async version)."""
        self.housekeeping_running = False
        if self.housekeeping_task:
            self.housekeeping_task.cancel()
            try:
                await self.housekeeping_task
            except asyncio.CancelledError:
                pass
        logger.info("Actuator housekeeping task stopped")
    
    async def _housekeeping_loop(self):
        """
        Housekeeping loop to check pump timeout (async version).
        
        Runs every 250ms.
        """
        while self.housekeeping_running:
            try:
                async with self.pump_lock:
                    if self.pump_enabled and self.pump_deadline:
                        current_time = time.time()
                        if current_time >= self.pump_deadline:
                            # Timeout reached, turn off pump
                            self.pump.off()
                            self.pump_enabled = False
                            self.pump_deadline = None
                            logger.info("Pump automatically turned off (timeout)")
                
                await asyncio.sleep(PUMP_CHECK_INTERVAL)
                
            except asyncio.CancelledError:
                logger.info("Housekeeping task cancelled")
                break
            except Exception as e:
                logger.error(f"Housekeeping error: {e}")
    
    async def activate_pump(self, duration_ms: int) -> bool:
        """
        Activate water pump for specified duration (async version).
        
        Args:
            duration_ms: Duration in milliseconds
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with self.pump_lock:
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
    
    async def deactivate_pump(self) -> bool:
        """
        Manually deactivate water pump (async version).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            async with self.pump_lock:
                self.pump.off()
                self.pump_enabled = False
                self.pump_deadline = None
                
                logger.info("Pump manually deactivated")
                return True
                
        except Exception as e:
            logger.error(f"Failed to deactivate pump: {e}")
            return False
    
    async def set_light(self, enabled: bool) -> bool:
        """
        Set grow light state (async version).
        
        Args:
            enabled: True to turn on, False to turn off
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # GPIO operations are fast, but wrap in to_thread for consistency
            await asyncio.to_thread(self._set_light_sync, enabled)
            return True
            
        except Exception as e:
            logger.error(f"Failed to set light state: {e}")
            return False
    
    def _set_light_sync(self, enabled: bool):
        """Synchronous helper for set_light."""
        if enabled:
            self.light.on()
            logger.info("Grow light turned ON")
        else:
            self.light.off()
            logger.info("Grow light turned OFF")
    
    async def get_state(self) -> dict:
        """
        Get current actuator state (async version).
        
        Returns:
            Dictionary with pump and light states
        """
        async with self.pump_lock:
            return {
                'pumpEnabled': self.pump_enabled,
                'lightEnabled': self.light.is_active
            }
    
    async def process_commands(self, commands: list) -> None:
        """
        Process commands from API server (async version).
        
        Command format:
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
                    await self.activate_pump(duration_ms)
                else:
                    logger.warning(f"Invalid pump duration: {duration_ms}")
            
            elif kind == 'light':
                enabled = cmd.get('enabled', False)
                await self.set_light(enabled)
            
            else:
                logger.warning(f"Unknown command kind: {kind}")
    
    async def cleanup(self):
        """Clean up actuator resources (async version)."""
        await self.stop_housekeeping()
        
        # Turn off all actuators
        try:
            self.pump.off()
            self.light.off()
            self.pump.close()
            self.light.close()
            logger.info("Actuator cleanup complete")
        except Exception as e:
            logger.warning(f"Actuator cleanup error: {e}")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.async_start_housekeeping()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()
