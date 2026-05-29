"""
API client for GrowMate Pods.

Handles HTTPS communication with cloud backend:
- Upload sensor data (JSON)
- Upload camera images (JPEG)
- Receive and parse commands from server

Converted to async with aiohttp for better performance and concurrency.
Added circuit breaker and exponential backoff for robust error handling.
Added correlation IDs to request headers for tracing operations.
"""

import asyncio
import logging
import aiohttp
from typing import Dict, List, Optional
from utils import FIRMWARE_VERSION, API_TIMEOUT_SENSOR, API_TIMEOUT_CAMERA
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from retry_handler import (
    RetryHandler,
    exponential_backoff_retry,
    categorize_error,
    ErrorCategory,
    PermanentError,
    RateLimitError
)
from logging_config import get_correlation_id


logger = logging.getLogger("growmate.api")


class APIClient:
    """Handles async API communication with GrowMate cloud backend."""
    
    def __init__(self, config: Dict):
        """
        Initialize API client.
        
        Args:
            config: Configuration dictionary with API URLs
        """
        self.config = config
        self.device_id = config.get('device', {}).get('id', 'unknown')
        self.sensor_url = config.get('api', {}).get('sensor_url')
        self.camera_url = config.get('api', {}).get('camera_url')
        
        # Persistent session for connection pooling (RPI optimization)
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Circuit breakers (one per endpoint)
        cb_config = config.get('circuit_breaker', {})
        self.sensor_circuit_breaker = CircuitBreaker(
            name="sensor_api",
            failure_threshold=cb_config.get('failure_threshold', 5),
            recovery_timeout=cb_config.get('recovery_timeout', 60.0),
            success_threshold=cb_config.get('success_threshold', 2)
        )
        self.camera_circuit_breaker = CircuitBreaker(
            name="camera_api",
            failure_threshold=cb_config.get('failure_threshold', 5),
            recovery_timeout=cb_config.get('recovery_timeout', 60.0),
            success_threshold=cb_config.get('success_threshold', 2)
        )
        
        # Retry handler with exponential backoff
        retry_config = config.get('retry', {})
        self.retry_handler = RetryHandler(
            max_attempts=retry_config.get('max_attempts', 6),
            initial_delay=retry_config.get('initial_delay', 1.0),
            max_delay=retry_config.get('max_delay', 32.0),
            jitter=retry_config.get('jitter', 0.25)
        )
        
        logger.info(f"API client initialized for device: {self.device_id}")
    
    def update_retry_config(self, retry_config: Dict):
        """
        Update retry handler configuration (Hot-reload support).
        
        Args:
            retry_config: New retry configuration dictionary
        """
        self.retry_handler.update_config(
            max_attempts=retry_config.get('max_attempts'),
            initial_delay=retry_config.get('initial_delay'),
            max_delay=retry_config.get('max_delay'),
            jitter=retry_config.get('jitter')
        )
    
    def update_circuit_breaker_config(self, cb_config: Dict):
        """
        Update circuit breaker configuration (Hot-reload support).
        
        Args:
            cb_config: New circuit breaker configuration dictionary
        """
        self.sensor_circuit_breaker.update_config(
            failure_threshold=cb_config.get('failure_threshold'),
            recovery_timeout=cb_config.get('recovery_timeout'),
            success_threshold=cb_config.get('success_threshold')
        )
        self.camera_circuit_breaker.update_config(
            failure_threshold=cb_config.get('failure_threshold'),
            recovery_timeout=cb_config.get('recovery_timeout'),
            success_threshold=cb_config.get('success_threshold')
        )
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()
    
    async def initialize(self):
        """Initialize HTTP session with connection pooling."""
        if self.session is None:
            # Create session with connection pooling
            timeout = aiohttp.ClientTimeout(total=60)
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )
            logger.info("HTTP session initialized with connection pooling")
    
    async def cleanup(self):
        """Clean up HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("HTTP session closed")
    
    async def upload_sensor_data(self, sensors: List[Dict], current_state: Dict) -> Optional[List[Dict]]:
        """
        Upload sensor data to API and receive commands.
        
        Uses circuit breaker and exponential backoff for robust error handling.
        
        Request format:
        {
          "deviceId": "IAET01",
          "firmwareVersion": "2.0.0",
          "sensors": [
            {"kind": "soil", "value": 45, "unit": "%", "raw": 1843},
            ...
          ],
          "currentState": {
            "pumpEnabled": false,
            "lightEnabled": true
          }
        }
        
        Response format:
        {
          "commands": [
            {"kind": "pump", "durationMs": 5000},
            {"kind": "light", "enabled": true}
          ]
        }
        
        Args:
            sensors: List of sensor data dictionaries
            current_state: Current actuator state
            
        Returns:
            List of commands from server, or None on failure
        """
        if not self.sensor_url:
            logger.error("Sensor API URL not configured")
            return None
        
        # Ensure session is initialized
        if not self.session:
            await self.initialize()
        
        # Build payload
        payload = {
            'deviceId': self.device_id,
            'firmwareVersion': FIRMWARE_VERSION,
            'sensors': sensors,
            'currentState': current_state
        }
        
        # Define upload function
        async def _upload():
            logger.debug(f"Uploading sensor data: {len(sensors)} sensors")
            
            # Add correlation ID to headers for tracing
            headers = {
                'Content-Type': 'application/json',
                'X-Correlation-Id': get_correlation_id() or 'none'
            }
            
            async with self.session.post(
                self.sensor_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT_SENSOR)
            ) as response:
                # Check for rate limit
                if response.status == 429:
                    raise RateLimitError(f"Rate limit exceeded (429)")
                
                # Check for permanent errors (4xx except 429)
                if 400 <= response.status < 500:
                    raise PermanentError(f"Client error: {response.status}")
                
                # Raise for other errors (5xx, etc.)
                response.raise_for_status()
                
                # Parse response
                data = await response.json()
                commands = data.get('commands', [])
                
                logger.info(f"Sensor upload successful, received {len(commands)} commands")
                return commands
        
        # Execute with circuit breaker and retry handler
        try:
            # Wrap with circuit breaker
            async def _upload_with_circuit_breaker():
                return await self.sensor_circuit_breaker.call(_upload)
            
            # Execute with retry handler
            commands = await self.retry_handler.execute(_upload_with_circuit_breaker)
            return commands
            
        except CircuitBreakerOpenError as e:
            logger.warning(f"Sensor upload rejected: circuit breaker open")
            return None
        except PermanentError as e:
            logger.error(f"Sensor upload failed: permanent error: {e}")
            return None
        except Exception as e:
            logger.error(f"Sensor upload failed after all retries: {e}")
            return None
    
    async def upload_camera_image(self, image_bytes: bytes) -> bool:
        """
        Upload camera image to API.
        
        Uses circuit breaker and exponential backoff for robust error handling.
        
        Request format:
        - Content-Type: image/jpeg
        - X-Device-Id: {device_id}
        - Body: raw JPEG bytes
        
        Args:
            image_bytes: JPEG image bytes
            
        Returns:
            True if successful, False otherwise
        """
        if not self.camera_url:
            logger.error("Camera API URL not configured")
            return False
        
        # Ensure session is initialized
        if not self.session:
            await self.initialize()
        
        # Define upload function
        async def _upload():
            logger.debug(f"Uploading camera image: {len(image_bytes)} bytes")
            
            # Add correlation ID to headers for tracing
            headers = {
                'Content-Type': 'image/jpeg',
                'X-Device-Id': self.device_id,
                'X-Correlation-Id': get_correlation_id() or 'none'
            }
            
            async with self.session.post(
                self.camera_url,
                data=image_bytes,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT_CAMERA)
            ) as response:
                # Check for rate limit
                if response.status == 429:
                    raise RateLimitError(f"Rate limit exceeded (429)")
                
                # Check for permanent errors (4xx except 429)
                if 400 <= response.status < 500:
                    raise PermanentError(f"Client error: {response.status}")
                
                # Raise for other errors (5xx, etc.)
                response.raise_for_status()
                
                logger.info("Camera upload successful")
                return True
        
        # Execute with circuit breaker and retry handler
        try:
            # Wrap with circuit breaker
            async def _upload_with_circuit_breaker():
                return await self.camera_circuit_breaker.call(_upload)
            
            # Execute with retry handler
            success = await self.retry_handler.execute(_upload_with_circuit_breaker)
            return success
            
        except CircuitBreakerOpenError as e:
            logger.warning(f"Camera upload rejected: circuit breaker open")
            return False
        except PermanentError as e:
            logger.error(f"Camera upload failed: permanent error: {e}")
            return False
        except Exception as e:
            logger.error(f"Camera upload failed after all retries: {e}")
            return False
    
    def get_circuit_breaker_stats(self) -> Dict:
        """
        Get circuit breaker statistics.
        
        Returns:
            Dictionary with circuit breaker stats for both endpoints
        """
        return {
            'sensor_api': self.sensor_circuit_breaker.get_stats(),
            'camera_api': self.camera_circuit_breaker.get_stats()
        }
    
    def get_retry_stats(self) -> Dict:
        """
        Get retry handler statistics.
        
        Returns:
            Dictionary with retry stats
        """
        return self.retry_handler.get_stats()
    
    def reset_circuit_breakers(self):
        """Reset all circuit breakers to closed state."""
        self.sensor_circuit_breaker.reset()
        self.camera_circuit_breaker.reset()
        logger.info("All circuit breakers reset")


# Convenience functions (async versions)
async def upload_sensors(config: Dict, sensors: List[Dict], current_state: Dict) -> Optional[List[Dict]]:
    """
    Upload sensor data and return commands.
    
    Args:
        config: Configuration dictionary
        sensors: List of sensor data
        current_state: Current actuator state
        
    Returns:
        List of commands or None on failure
    """
    async with APIClient(config) as client:
        return await client.upload_sensor_data(sensors, current_state)


async def upload_image(config: Dict, image_bytes: bytes) -> bool:
    """
    Upload camera image.
    
    Args:
        config: Configuration dictionary
        image_bytes: JPEG image bytes
        
    Returns:
        True if successful, False otherwise
    """
    async with APIClient(config) as client:
        return await client.upload_camera_image(image_bytes)
