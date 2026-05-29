"""
API client for GrowMate Pods.

Handles HTTPS communication with cloud backend:
- Upload sensor data (JSON)
- Upload camera images (JPEG)
- Receive and parse commands from server
"""

import logging
import requests
from typing import Dict, List, Optional, Tuple
from utils import retry, FIRMWARE_VERSION, API_TIMEOUT_SENSOR, API_TIMEOUT_CAMERA


logger = logging.getLogger("growmate.api")


class APIClient:
    """Handles API communication with GrowMate cloud backend."""
    
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
        
        logger.info(f"API client initialized for device: {self.device_id}")
    
    @retry(max_attempts=2, delay_seconds=1.5)
    def upload_sensor_data(self, sensors: List[Dict], current_state: Dict) -> Optional[List[Dict]]:
        """
        Upload sensor data to API and receive commands.
        
        Request format (from ESP32 analysis):
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
        
        # Build payload
        payload = {
            'deviceId': self.device_id,
            'firmwareVersion': FIRMWARE_VERSION,
            'sensors': sensors,
            'currentState': current_state
        }
        
        try:
            logger.info(f"Uploading sensor data: {len(sensors)} sensors")
            
            response = requests.post(
                self.sensor_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=API_TIMEOUT_SENSOR
            )
            
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            commands = data.get('commands', [])
            
            logger.info(f"Sensor upload successful, received {len(commands)} commands")
            return commands
            
        except requests.exceptions.Timeout:
            logger.error("Sensor upload timeout")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Sensor upload failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during sensor upload: {e}")
            raise
    
    @retry(max_attempts=2, delay_seconds=1.5)
    def upload_camera_image(self, image_bytes: bytes) -> bool:
        """
        Upload camera image to API.
        
        Request format (from ESP32 analysis):
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
        
        try:
            logger.info(f"Uploading camera image: {len(image_bytes)} bytes")
            
            response = requests.post(
                self.camera_url,
                data=image_bytes,
                headers={
                    'Content-Type': 'image/jpeg',
                    'X-Device-Id': self.device_id
                },
                timeout=API_TIMEOUT_CAMERA
            )
            
            response.raise_for_status()
            
            logger.info("Camera upload successful")
            return True
            
        except requests.exceptions.Timeout:
            logger.error("Camera upload timeout")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Camera upload failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during camera upload: {e}")
            raise


# Convenience functions
def upload_sensors(config: Dict, sensors: List[Dict], current_state: Dict) -> Optional[List[Dict]]:
    """
    Upload sensor data and return commands.
    
    Args:
        config: Configuration dictionary
        sensors: List of sensor data
        current_state: Current actuator state
        
    Returns:
        List of commands or None on failure
    """
    client = APIClient(config)
    return client.upload_sensor_data(sensors, current_state)


def upload_image(config: Dict, image_bytes: bytes) -> bool:
    """
    Upload camera image.
    
    Args:
        config: Configuration dictionary
        image_bytes: JPEG image bytes
        
    Returns:
        True if successful, False otherwise
    """
    client = APIClient(config)
    return client.upload_camera_image(image_bytes)
