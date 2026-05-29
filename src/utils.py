"""
Utility functions and helpers for GrowMate Pods.

Provides logging setup and common helper functions.

Removed old retry decorator (replaced by retry_handler.py with exponential backoff).
Updated firmware version to 2.4.0 for hot-reload & validation support.
Updated firmware version to 2.5.0 for structured JSON logging with correlation IDs.
Updated firmware version to 2.6.0 for minimal web interface (WiFi credentials only).

Note: The setup_logging() function in this file is deprecated. Use logging_config.py instead.
"""

import logging
from typing import Optional
from systemd import journal


def setup_logging(name: str = "growmate") -> logging.Logger:
    """
    Configure logging to systemd journal.
    
    Args:
        name: Logger name (default: "growmate")
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Add systemd journal handler
    journal_handler = journal.JournalHandler()
    journal_handler.setLevel(logging.INFO)
    
    # Format: timestamp - level - message
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    journal_handler.setFormatter(formatter)
    
    logger.addHandler(journal_handler)
    
    # Also add console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Clamp a value between min and max.
    
    Args:
        value: Value to clamp
        min_val: Minimum value
        max_val: Maximum value
        
    Returns:
        Clamped value
    """
    return max(min_val, min(max_val, value))


def map_range(value: float, in_min: float, in_max: float, 
              out_min: float = 0.0, out_max: float = 100.0) -> float:
    """
    Map a value from one range to another.
    
    Used for sensor calibration: raw ADC value → percentage.
    Handles inverted ranges (e.g., light sensor where high raw = low light).
    
    Args:
        value: Input value
        in_min: Input range minimum
        in_max: Input range maximum
        out_min: Output range minimum (default: 0.0)
        out_max: Output range maximum (default: 100.0)
        
    Returns:
        Mapped value, clamped to output range
        
    Example:
        # Normal sensor (wet = high raw value)
        percent = map_range(2048, 0, 4095, 0, 100)  # → 50%
        
        # Inverted sensor (bright = low raw value)
        percent = map_range(1000, 4095, 0, 0, 100)  # → ~75%
    """
    # Handle inverted ranges
    if in_min > in_max:
        # Inverted input range
        mapped = (in_min - value) * (out_max - out_min) / (in_min - in_max) + out_min
    else:
        # Normal input range
        mapped = (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min
    
    return clamp(mapped, out_min, out_max)


def get_device_id() -> str:
    """
    Generate device ID from MAC address.
    
    Format: "growmate-XXXXXXXXXXXX" (last 12 hex chars of MAC)
    Example: "growmate-b827eb123456"
    
    Returns:
        Device ID string
    """
    try:
        # Read MAC address from eth0 or wlan0
        with open('/sys/class/net/wlan0/address', 'r') as f:
            mac = f.read().strip().replace(':', '')
            return f"growmate-{mac}"
    except FileNotFoundError:
        # Fallback to eth0
        try:
            with open('/sys/class/net/eth0/address', 'r') as f:
                mac = f.read().strip().replace(':', '')
                return f"growmate-{mac}"
        except FileNotFoundError:
            # Last resort: use hostname
            import socket
            return f"growmate-{socket.gethostname()}"


def get_ap_ssid() -> str:
    """
    Generate AP mode SSID from device ID.
    
    Format: "GrowMate-XXXXXX" (last 6 chars of device ID)
    Example: "GrowMate-123456"
    
    Returns:
        AP SSID string
    """
    device_id = get_device_id()
    # Extract last 6 characters after "growmate-"
    suffix = device_id.split('-')[-1][-6:].upper()
    return f"GrowMate-{suffix}"


# Application constants
SENSOR_INTERVAL_SECONDS = 15
CAMERA_INTERVAL_SECONDS = 900  # 15 minutes
FAILURE_THRESHOLD = 5  # Re-enter onboarding after 5 consecutive failures
PUMP_HOUSEKEEPING_INTERVAL_MS = 250

# API endpoints
API_SENSOR_ENDPOINT = "https://avid-mammoth-766.convex.site/api/sensors"
API_CAMERA_ENDPOINT = "https://avid-mammoth-766.convex.site/api/camera"
API_TIMEOUT_SENSOR = 12.0  # seconds
API_TIMEOUT_CAMERA = 45.0  # seconds

# Queue settings (Offline operation)
QUEUE_DATABASE_PATH = "/var/lib/growmate/queue.db"
QUEUE_CLEANUP_INTERVAL = 3600  # seconds (1 hour)
QUEUE_MAX_AGE_HOURS = 24  # Delete entries older than 24 hours
QUEUE_MAX_RETRIES = 5  # Maximum upload retry attempts
QUEUE_VACUUM_INTERVAL = 604800  # seconds (1 week)

# Firmware version (Web Interface - minimal onboarding, WiFi credentials only)
FIRMWARE_VERSION = "2.6.0"
