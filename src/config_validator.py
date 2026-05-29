"""
Configuration validation using Pydantic models.

Provides comprehensive validation for all configuration fields
with helpful error messages and type checking.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator, root_validator
import logging


logger = logging.getLogger("growmate.config_validator")


class DeviceConfig(BaseModel):
    """Device configuration."""
    id: str = Field(..., min_length=1, description="Device ID (auto-generated from MAC)")


class NetworkConfig(BaseModel):
    """Network configuration (non-reloadable)."""
    provisioned: bool = Field(False, description="Whether device is provisioned")
    wifi_ssid: str = Field("", description="WiFi network SSID")
    wifi_password: str = Field("", description="WiFi network password")


class APIConfig(BaseModel):
    """API configuration (partially reloadable)."""
    sensor_url: str = Field(..., min_length=1, description="Sensor data upload endpoint")
    camera_url: str = Field(..., min_length=1, description="Camera image upload endpoint")
    timeout_sensor: float = Field(12.0, ge=1.0, le=60.0, description="Sensor upload timeout (seconds)")
    timeout_camera: float = Field(45.0, ge=5.0, le=120.0, description="Camera upload timeout (seconds)")


class IntervalsConfig(BaseModel):
    """Intervals configuration (RELOADABLE)."""
    sensor_reading: int = Field(15, ge=5, le=300, description="Sensor reading interval (seconds)")
    camera_capture: int = Field(900, ge=60, le=3600, description="Camera capture interval (seconds)")
    
    @validator('camera_capture')
    def camera_must_be_multiple_of_sensor(cls, v, values):
        """Camera interval should be a multiple of sensor interval for efficiency."""
        sensor_interval = values.get('sensor_reading', 15)
        if v < sensor_interval:
            raise ValueError(f"camera_capture ({v}s) must be >= sensor_reading ({sensor_interval}s)")
        return v


class CameraConfig(BaseModel):
    """Camera configuration (RELOADABLE)."""
    width: int = Field(2592, ge=640, le=2592, description="Camera width (pixels)")
    height: int = Field(1944, ge=480, le=1944, description="Camera height (pixels)")
    quality: int = Field(85, ge=50, le=100, description="JPEG quality (50-100)")
    add_exif: bool = Field(True, description="Add EXIF metadata to images")
    
    @root_validator
    def validate_resolution(cls, values):
        """Validate camera resolution doesn't exceed 5MP."""
        width = values.get('width', 2592)
        height = values.get('height', 1944)
        max_pixels = 5_000_000  # 5MP
        
        if width * height > max_pixels:
            raise ValueError(
                f"Camera resolution ({width}x{height} = {width*height} pixels) "
                f"exceeds 5MP limit ({max_pixels} pixels)"
            )
        return values


class QueueConfig(BaseModel):
    """Queue configuration (partially reloadable)."""
    enabled: bool = Field(True, description="Enable offline queue")
    max_age_hours: int = Field(24, ge=1, le=168, description="Delete entries older than this (hours)")
    max_sensor_entries: int = Field(6000, ge=100, le=50000, description="Max sensor queue entries")
    max_image_entries: int = Field(100, ge=10, le=1000, description="Max image queue entries")
    cleanup_interval: int = Field(3600, ge=60, le=86400, description="Cleanup interval (seconds)")
    max_retries: int = Field(5, ge=1, le=20, description="Maximum upload retry attempts")


class RetryConfig(BaseModel):
    """Retry configuration (RELOADABLE)."""
    max_attempts: int = Field(6, ge=1, le=10, description="Maximum retry attempts")
    initial_delay: float = Field(1.0, ge=0.1, le=10.0, description="Initial retry delay (seconds)")
    max_delay: float = Field(32.0, ge=1.0, le=300.0, description="Maximum retry delay (seconds)")
    jitter: float = Field(0.25, ge=0.0, le=0.5, description="Jitter factor (0.0-0.5)")
    
    @validator('max_delay')
    def max_delay_must_be_greater_than_initial(cls, v, values):
        """Max delay must be greater than initial delay."""
        initial_delay = values.get('initial_delay', 1.0)
        if v < initial_delay:
            raise ValueError(f"max_delay ({v}s) must be >= initial_delay ({initial_delay}s)")
        return v


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration (RELOADABLE)."""
    failure_threshold: int = Field(5, ge=1, le=20, description="Open circuit after N failures")
    recovery_timeout: int = Field(60, ge=5, le=600, description="Recovery timeout (seconds)")
    success_threshold: int = Field(2, ge=1, le=10, description="Close circuit after N successes")


class CalibrationConfig(BaseModel):
    """Sensor calibration configuration."""
    soil_moisture: Dict[str, int] = Field(
        default={'min': 0, 'max': 65535},
        description="Soil moisture calibration"
    )
    light: Dict[str, int] = Field(
        default={'min': 0, 'max': 65535},
        description="Light sensor calibration"
    )
    water_level: Dict[str, int] = Field(
        default={'min': 0, 'max': 65535},
        description="Water level calibration"
    )


class SensorsConfig(BaseModel):
    """Sensors configuration."""
    enable_dht22: bool = Field(True, description="Enable DHT22 temperature/humidity sensor")
    adc_samples: int = Field(8, ge=1, le=32, description="Number of ADC samples to average")
    adc_sample_delay: float = Field(0.01, ge=0.001, le=1.0, description="Delay between ADC samples (seconds)")


class LoggingModulesConfig(BaseModel):
    """Per-module log levels (RELOADABLE)."""
    sensors: str = Field("INFO", description="Sensors module log level")
    camera: str = Field("INFO", description="Camera module log level")
    api_client: str = Field("INFO", description="API client module log level")
    queue: str = Field("INFO", description="Queue module log level")
    scheduler: str = Field("INFO", description="Scheduler module log level")
    
    @validator('*')
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()


class LoggingConfig(BaseModel):
    """Logging configuration (RELOADABLE)."""
    level: str = Field("INFO", description="Global log level")
    format: str = Field("json", description="Log format (json or text)")
    file: str = Field("/var/log/growmate/growmate.log", description="Log file path")
    max_bytes: int = Field(10485760, ge=1048576, le=104857600, description="Max log file size (bytes)")
    backup_count: int = Field(5, ge=1, le=20, description="Number of backup log files")
    modules: Optional[LoggingModulesConfig] = Field(None, description="Per-module log levels")
    
    @validator('level')
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()
    
    @validator('format')
    def validate_log_format(cls, v):
        """Validate log format."""
        valid_formats = ['json', 'text']
        if v.lower() not in valid_formats:
            raise ValueError(f"Invalid log format: {v}. Must be one of {valid_formats}")
        return v.lower()


class FeaturesConfig(BaseModel):
    """Feature flags (RELOADABLE)."""
    offline_queue: bool = Field(True, description="Enable offline queue")
    hot_reload: bool = Field(True, description="Enable hot-reload configuration")
    structured_logging: bool = Field(True, description="Enable structured JSON logging")
    circuit_breaker: bool = Field(True, description="Enable circuit breaker")


class GrowMateConfig(BaseModel):
    """Root configuration model."""
    version: int = Field(..., ge=1, description="Configuration version")
    device: DeviceConfig
    network: NetworkConfig
    api: APIConfig
    intervals: IntervalsConfig
    camera: CameraConfig
    queue: QueueConfig
    retry: RetryConfig
    circuit_breaker: CircuitBreakerConfig
    calibration: CalibrationConfig
    sensors: SensorsConfig
    logging: Optional[LoggingConfig] = None
    features: Optional[FeaturesConfig] = None
    
    class Config:
        """Pydantic config."""
        extra = 'forbid'  # Reject unknown fields
        validate_assignment = True  # Validate on assignment


# Reloadable settings (can be changed without restart)
RELOADABLE_SETTINGS = {
    'intervals',           # Sensor and camera intervals
    'camera',              # Camera settings (quality, resolution)
    'retry',               # Retry settings
    'circuit_breaker',     # Circuit breaker settings
    'logging',             # Log levels and format
    'features',            # Feature flags
    'api.timeout_sensor',  # API timeouts (partial)
    'api.timeout_camera',  # API timeouts (partial)
}

# Non-reloadable settings (require restart)
NON_RELOADABLE_SETTINGS = {
    'version',             # Config version
    'device.id',           # Device ID
    'network',             # WiFi credentials
    'api.sensor_url',      # API endpoints (partial)
    'api.camera_url',      # API endpoints (partial)
    'queue.enabled',       # Queue enable/disable (partial)
    'calibration',         # Sensor calibration
    'sensors',             # Sensor configuration
}


def validate_config(config_dict: Dict[str, Any]) -> GrowMateConfig:
    """
    Validate configuration dictionary using Pydantic models.
    
    Args:
        config_dict: Configuration dictionary to validate
        
    Returns:
        Validated GrowMateConfig model
        
    Raises:
        ValidationError: If configuration is invalid
    """
    try:
        validated = GrowMateConfig(**config_dict)
        logger.info("Configuration validation successful")
        return validated
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        raise


def is_reloadable_change(key: str) -> bool:
    """
    Check if a configuration key is reloadable (can be changed without restart).
    
    Args:
        key: Configuration key (dot notation, e.g., "intervals.sensor_reading")
        
    Returns:
        True if reloadable, False if requires restart
    """
    # Check exact match
    if key in RELOADABLE_SETTINGS:
        return True
    
    # Check prefix match (e.g., "intervals.sensor_reading" matches "intervals")
    for reloadable_key in RELOADABLE_SETTINGS:
        if key.startswith(reloadable_key + '.'):
            return True
    
    return False


def get_config_changes(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> Dict[str, tuple]:
    """
    Get differences between two configurations.
    
    Args:
        old_config: Old configuration dictionary
        new_config: New configuration dictionary
        
    Returns:
        Dictionary of changes: {key: (old_value, new_value)}
    """
    changes = {}
    
    def compare_dicts(old: Dict, new: Dict, prefix: str = ''):
        """Recursively compare dictionaries."""
        all_keys = set(old.keys()) | set(new.keys())
        
        for key in all_keys:
            full_key = f"{prefix}.{key}" if prefix else key
            
            old_val = old.get(key)
            new_val = new.get(key)
            
            if old_val != new_val:
                if isinstance(old_val, dict) and isinstance(new_val, dict):
                    # Recurse into nested dicts
                    compare_dicts(old_val, new_val, full_key)
                else:
                    # Value changed
                    changes[full_key] = (old_val, new_val)
    
    compare_dicts(old_config, new_config)
    return changes
