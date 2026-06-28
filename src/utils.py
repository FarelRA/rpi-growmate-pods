"""
Utility functions and helpers for GrowMate Pods.

Provides logging setup and common helper functions.
"""

import os
import logging
from typing import Optional
from systemd import journal


def setup_logging(name: str = "growmate") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    journal_handler = journal.JournalHandler()
    journal_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    journal_handler.setFormatter(formatter)

    logger.addHandler(journal_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def map_range(value: float, in_min: float, in_max: float,
              out_min: float = 0.0, out_max: float = 100.0) -> float:
    if in_min > in_max:
        mapped = (in_min - value) * (out_max - out_min) / (in_min - in_max) + out_min
    else:
        mapped = (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

    return clamp(mapped, out_min, out_max)


def get_device_id() -> str:
    try:
        with open('/sys/class/net/wlan0/address', 'r') as f:
            mac = f.read().strip().replace(':', '')
            return f"growmate-{mac}"
    except FileNotFoundError:
        try:
            with open('/sys/class/net/eth0/address', 'r') as f:
                mac = f.read().strip().replace(':', '')
                return f"growmate-{mac}"
        except FileNotFoundError:
            import socket
            return f"growmate-{socket.gethostname()}"


def get_env_device_id() -> str:
    return os.environ.get("DEVICE_ID") or get_device_id()


def get_env_api_key() -> str:
    return os.environ.get("DEVICE_API_KEY", "")


def get_ap_ssid() -> str:
    device_id = get_device_id()
    suffix = device_id.split('-')[-1][-6:].upper()
    return f"GrowMate-{suffix}"


# Application constants
FAILURE_THRESHOLD = 5
SENSOR_INTERVAL_SECONDS = 60

# API endpoints
API_SENSOR_ENDPOINT = "https://growmate.bond/api/v2/sensors"
API_TIMEOUT_SENSOR = 30.0  # seconds

# V2-specific endpoints
STREAM_REGISTER_URL = "https://growmate.bond/api/v2/stream/register"
API_TIMEOUT_STREAM_REGISTER = 10.0  # seconds

# Queue settings (Offline operation)
QUEUE_DATABASE_PATH = "/var/lib/growmate/queue.db"
QUEUE_CLEANUP_INTERVAL = 3600  # seconds (1 hour)
QUEUE_MAX_AGE_HOURS = 24  # Delete entries older than 24 hours
QUEUE_MAX_RETRIES = 5  # Maximum upload retry attempts
QUEUE_VACUUM_INTERVAL = 604800  # seconds (1 week)

# Firmware version
FIRMWARE_VERSION = "2.0.0"
