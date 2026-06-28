import re
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, validator
import logging


logger = logging.getLogger("growmate.config_validator")


class DeviceConfig(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)

    @validator('id')
    def validate_device_id(cls, v):
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError(
                f"Device ID '{v}' contains invalid characters. "
                f"Use only letters, digits, hyphens, and underscores."
            )
        return v


class NetworkWifiConfig(BaseModel):
    interface: str = Field("wlan0")
    connect_timeout: int = Field(12, ge=1, le=60)
    connect_retries: int = Field(4, ge=1, le=20)


class NetworkConfig(BaseModel):
    provisioned: bool = Field(False)
    wifi_ssid: str = Field("")
    wifi_password: str = Field("")
    wifi: NetworkWifiConfig = Field(default_factory=NetworkWifiConfig)


class APModeConfig(BaseModel):
    ssid: Optional[str] = Field(None, max_length=32)
    password: str = Field("growmate", min_length=1)
    channel: int = Field(1, ge=0, le=14)
    ip_address: str = Field("192.168.4.1")
    netmask: str = Field("255.255.255.0")
    dhcp_range_start: str = Field("192.168.4.2")
    dhcp_range_end: str = Field("192.168.4.20")
    interface: str = Field("wlan0")


class OnboardingConfig(BaseModel):
    host: str = Field("0.0.0.0")
    port: int = Field(80, ge=1, le=65535)


class APIConfig(BaseModel):
    sensor_url: str = Field(..., min_length=1)
    stream_register_url: str = Field("https://growmate.bond/api/v2/stream/register")
    timeout_sensor: float = Field(30.0, ge=1.0, le=60.0)
    timeout_stream_register: float = Field(10.0, ge=1.0, le=60.0)
    api_key: Optional[str] = Field(None)


class IntervalsConfig(BaseModel):
    sensor_reading: int = Field(60, ge=10, le=300)
    failure_monitor: int = Field(30, ge=5, le=300)
    camera_watchdog: int = Field(30, ge=5, le=300)
    queue_cleanup: int = Field(3600, ge=60, le=86400)
    queue_vacuum: int = Field(604800, ge=3600, le=2592000)
    queue_stats: int = Field(300, ge=30, le=3600)
    health_check: int = Field(300, ge=10, le=3600)


class QueueConfig(BaseModel):
    enabled: bool = Field(True)
    db_path: str = Field("/var/lib/growmate/queue.db")
    max_age_hours: int = Field(24, ge=1, le=168)
    max_sensor_entries: int = Field(1440, ge=100, le=50000)
    cleanup_interval: int = Field(3600, ge=60, le=86400)
    max_retries: int = Field(5, ge=1, le=20)
    vacuum_interval: int = Field(604800, ge=3600, le=2592000)


class UploadProcessorConfig(BaseModel):
    max_concurrent: int = Field(3, ge=1, le=10)
    delay: float = Field(0.5, ge=0.1, le=5.0)
    idle_sleep: float = Field(2.0, ge=0.5, le=30.0)
    batch_sleep: float = Field(0.1, ge=0.05, le=5.0)


class RetryConfig(BaseModel):
    max_attempts: int = Field(6, ge=1, le=10)
    initial_delay: float = Field(1.0, ge=0.1, le=10.0)
    max_delay: float = Field(32.0, ge=1.0, le=300.0)
    jitter: float = Field(0.25, ge=0.0, le=0.5)

    @validator('max_delay')
    def max_delay_must_be_greater_than_initial(cls, v, values):
        initial_delay = values.get('initial_delay', 1.0)
        if v < initial_delay:
            raise ValueError(f"max_delay ({v}s) must be >= initial_delay ({initial_delay}s)")
        return v


class CircuitBreakerConfig(BaseModel):
    failure_threshold: int = Field(5, ge=1, le=20)
    recovery_timeout: float = Field(60, ge=5, le=600)
    success_threshold: int = Field(2, ge=1, le=10)


class ADCSettings(BaseModel):
    i2c_bus: int = Field(1, ge=0, le=1)
    i2c_address: int = Field(0x48)
    gain: int = Field(1, ge=1, le=16)
    samples: int = Field(8, ge=1, le=64)
    sample_delay: float = Field(0.01, ge=0.001, le=1.0)
    max_value: int = Field(65535, ge=1024, le=65535)


class ADCChannels(BaseModel):
    battery_current: int = Field(0, ge=0, le=3)
    light: int = Field(1, ge=0, le=3)
    water: int = Field(2, ge=0, le=3)
    soil: int = Field(3, ge=0, le=3)


class CalibrationRange(BaseModel):
    min: int = Field(0)
    max: int = Field(65535, ge=1)


class SensorCalibration(BaseModel):
    soil: CalibrationRange = Field(default_factory=CalibrationRange)
    light: CalibrationRange = Field(default_factory=CalibrationRange)
    water: CalibrationRange = Field(default_factory=CalibrationRange)


class BatteryCurrentConfig(BaseModel):
    midpoint_voltage: float = Field(2.5, ge=0.0, le=5.0)
    sensitivity: float = Field(0.185, ge=0.01, le=1.0)


class LimitSwitchConfig(BaseModel):
    tank_gpio: int = Field(20, ge=2, le=27)
    drawer_gpio: int = Field(21, ge=2, le=27)
    pull_up_down: str = Field("PUD_UP")
    debounce_ms: int = Field(50, ge=1, le=500)
    debounce_samples: int = Field(5, ge=3, le=21)
    debounce_sample_interval: float = Field(0.01, ge=0.001, le=0.5)

    @validator('pull_up_down')
    def validate_pull_mode(cls, v):
        if v.upper() not in ('PUD_UP', 'PUD_DOWN', 'PUD_OFF'):
            raise ValueError(f"Invalid pull_up_down '{v}'. Use PUD_UP, PUD_DOWN, or PUD_OFF.")
        return v.upper()


class SensorHealthConfig(BaseModel):
    failure_threshold: int = Field(3, ge=1, le=20)


class SensorPins(BaseModel):
    pump: int = Field(10, ge=2, le=27)
    fertilizer: int = Field(17, ge=2, le=27)
    pesticide: int = Field(27, ge=2, le=27)


class ActuatorConfig(BaseModel):
    pins: SensorPins = Field(default_factory=SensorPins)
    active_high: bool = Field(True)
    initial_value: bool = Field(False)
    journal_size: int = Field(1000, ge=100, le=10000)
    journal_trim: int = Field(500, ge=50, le=5000)


class CameraConfig(BaseModel):
    enabled: bool = Field(True)
    port: int = Field(8554, ge=1024, le=65535)
    width: int = Field(640, ge=160, le=3280)
    height: int = Field(480, ge=120, le=2464)
    framerate: int = Field(15, ge=1, le=60)
    bitrate: int = Field(1000000, ge=100000, le=25000000)
    profile: str = Field("baseline")
    level: str = Field("3.1")
    denoise: str = Field("cdn_off")
    restart_delay: float = Field(0.5, ge=0.1, le=10.0)


class FailureConfig(BaseModel):
    consecutive_threshold: int = Field(5, ge=2, le=20)


class HealthMonitorConfig(BaseModel):
    history_size: int = Field(100, ge=10, le=1000)
    camera_crash_threshold: int = Field(5, ge=1, le=100)


class StreamRegistrationConfig(BaseModel):
    max_attempts: int = Field(10, ge=1, le=100)
    base_delay: float = Field(1.0, ge=0.1, le=60.0)
    max_delay: float = Field(60.0, ge=1.0, le=300.0)


class SensorsConfig(BaseModel):
    enable_dht22: bool = Field(True)
    dht22_pin: int = Field(4, ge=2, le=27)
    adc: ADCSettings = Field(default_factory=ADCSettings)
    channels: ADCChannels = Field(default_factory=ADCChannels)
    calibration: SensorCalibration = Field(default_factory=SensorCalibration)
    battery_current: BatteryCurrentConfig = Field(default_factory=BatteryCurrentConfig)
    limit_switches: LimitSwitchConfig = Field(default_factory=LimitSwitchConfig)
    health: SensorHealthConfig = Field(default_factory=SensorHealthConfig)


class LoggingConfig(BaseModel):
    level: str = Field("INFO")

    @validator('level')
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()

    file: str = Field("/var/log/growmate/growmate.log")
    format: str = Field("json")

    @validator('format')
    def validate_format(cls, v):
        if v.lower() not in ('json', 'text'):
            raise ValueError(f"Invalid log format: {v}. Use 'json' or 'text'.")
        return v.lower()

    max_bytes: int = Field(10485760, ge=65536, le=1073741824)
    backup_count: int = Field(5, ge=0, le=100)
    modules: Dict[str, str] = Field(default_factory=dict)


class FeaturesConfig(BaseModel):
    offline_queue: bool = Field(True)
    hot_reload: bool = Field(True)
    circuit_breaker: bool = Field(True)


class GrowMateConfig(BaseModel):
    version: int = Field(..., ge=1, description="Config schema version")
    device: DeviceConfig
    api: APIConfig
    network: NetworkConfig
    ap_mode: Optional[APModeConfig] = None
    onboarding: Optional[OnboardingConfig] = None
    intervals: IntervalsConfig = Field(default_factory=IntervalsConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    upload_processor: Optional[UploadProcessorConfig] = None
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    sensors: SensorsConfig = Field(default_factory=SensorsConfig)
    actuators: Optional[ActuatorConfig] = None
    camera: Optional[CameraConfig] = None
    failure: Optional[FailureConfig] = None
    health_monitor: Optional[HealthMonitorConfig] = None
    stream_registration: Optional[StreamRegistrationConfig] = None
    logging: Optional[LoggingConfig] = None
    features: Optional[FeaturesConfig] = None

    class Config:
        extra = 'forbid'
        validate_assignment = True


RELOADABLE_SETTINGS = {
    'intervals',
    'retry',
    'circuit_breaker',
    'logging',
    'features',
    'upload_processor',
    'failure',
    'health_monitor',
    'stream_registration',
}


NON_RELOADABLE_SETTINGS = {
    'version',
    'device.id',
    'network',
    'api.sensor_url',
    'api.stream_register_url',
    'api.timeout_sensor',
    'api.timeout_stream_register',
    'queue',
    'sensors',
    'actuators',
    'camera',
    'ap_mode',
    'onboarding',
}


def validate_config(config_dict: Dict[str, Any]) -> GrowMateConfig:
    try:
        validated = GrowMateConfig(**config_dict)
        logger.info("Configuration validation successful")
        return validated
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        raise


def is_reloadable_change(key: str) -> bool:
    if key in RELOADABLE_SETTINGS:
        return True
    for reloadable_key in RELOADABLE_SETTINGS:
        if key.startswith(reloadable_key + '.'):
            return True
    return False


def get_config_changes(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> Dict[str, tuple]:
    changes = {}

    def compare_dicts(old: Dict, new: Dict, prefix: str = ''):
        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            full_key = f"{prefix}.{key}" if prefix else key
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                if isinstance(old_val, dict) and isinstance(new_val, dict):
                    compare_dicts(old_val, new_val, full_key)
                else:
                    changes[full_key] = (old_val, new_val)

    compare_dicts(old_config, new_config)
    return changes
