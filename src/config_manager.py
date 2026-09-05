"""
Configuration management for GrowMate Pods (V2).

Handles YAML configuration file read/write, validation, and hot-reload.
Secrets come from environment variables; YAML is for non-sensitive defaults.
Env var override pattern: GROWMATE_<KEY> for any YAML key.
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path
from pydantic import ValidationError


logger = logging.getLogger("growmate.config")


# Configuration file path
CONFIG_DIR = Path("/etc/growmate")
CONFIG_FILE = CONFIG_DIR / "config.yaml"
CONFIG_VERSION = 9  # V2: env var overrides, 60s interval, no camera section


class ConfigManager:
    """
    Manages GrowMate configuration stored in YAML format.
    
    Supports validation and hot-reload.
    """
    
    def __init__(self, config_path: Optional[Path] = None, enable_validation: bool = True):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to config file (default: /etc/growmate/config.yaml)
            enable_validation: Enable Pydantic validation (default: True)
        """
        self.config_path = config_path or CONFIG_FILE
        self.config: Dict[str, Any] = {}
        self.enable_validation = enable_validation
        self.reload_callbacks: List[Callable] = []
        
    @staticmethod
    def _get_env_override(key: str) -> Optional[str]:
        if key == "device.id" and "DEVICE_ID" in os.environ:
            from utils import get_env_device_id
            return get_env_device_id()
        env_map = {
            "api.api_key": "DEVICE_API_KEY",
        }
        if key in env_map:
            value = os.environ.get(env_map[key])
            if value:
                return value

        env_key = "GROWMATE_" + key.upper().replace('.', '_')
        return os.environ.get(env_key)

    def _apply_env_overrides(self, config: Dict[str, Any]) -> None:
        flat = {}

        def _flatten(d: Dict[str, Any], prefix: str = ""):
            for k, v in d.items():
                full = f"{prefix}.{k}" if prefix else k
                flat[full] = v
                if isinstance(v, dict):
                    _flatten(v, full)

        _flatten(config)

        for key, value in flat.items():
            override = self._get_env_override(key)
            if override is not None:
                existing = flat.get(key)
                if isinstance(existing, bool):
                    parsed = override.lower() in ("true", "1", "yes")
                elif isinstance(existing, int):
                    try:
                        parsed = int(override)
                    except ValueError:
                        logger.warning(f"Env override {key}={override} is not a valid int, skipping")
                        continue
                elif isinstance(existing, float):
                    try:
                        parsed = float(override)
                    except ValueError:
                        logger.warning(f"Env override {key}={override} is not a valid float, skipping")
                        continue
                else:
                    parsed = override

                keys = key.split('.')
                target = config
                for k in keys[:-1]:
                    target = target.setdefault(k, {})
                target[keys[-1]] = parsed
                logger.info(f"Config override from env: {key}={parsed}")

    def load(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            config = self.get_default_config()
            self._apply_env_overrides(config)
            self.config = config
            return self.config

        try:
            with open(self.config_path, 'r') as f:
                config_dict = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {self.config_path}")

                if config_dict.get('version') != CONFIG_VERSION:
                    logger.warning(
                        f"Config version mismatch: expected {CONFIG_VERSION}, "
                        f"got {config_dict.get('version')}"
                    )

                self._apply_env_overrides(config_dict)

                if self.enable_validation:
                    self.validate(config_dict)

                self.config = config_dict
                return self.config
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse config file: {e}")
            raise
    
    def save(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Save configuration to YAML file.
        
        Args:
            config: Configuration dictionary (default: use current config)
            
        Raises:
            IOError: If unable to write config file
        """
        if config is not None:
            self.config = config
        
        # Ensure config directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.config_path, 'w') as f:
                yaml.safe_dump(self.config, f, default_flow_style=False, indent=2)
                logger.info(f"Saved configuration to {self.config_path}")
        except IOError as e:
            logger.error(f"Failed to save config file: {e}")
            raise
    
    def is_provisioned(self) -> bool:
        """
        Check if device is provisioned (configured).
        
        provisioned flag must be true and WiFi SSID must exist.
        
        Returns:
            True if device is provisioned, False otherwise
        """
        if not self.config:
            return False
        
        network = self.config.get('network', {})
        provisioned = network.get('provisioned', False)
        wifi_ssid = network.get('wifi_ssid', '').strip()
        
        return provisioned and len(wifi_ssid) > 0
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.
        
        Supports nested keys with dot notation (e.g., "network.wifi_ssid").
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            
            if value is None:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value by key.
        
        Supports nested keys with dot notation (e.g., "network.wifi_ssid").
        
        Args:
            key: Configuration key
            value: Value to set
        """
        keys = key.split('.')
        config = self.config
        
        # Navigate to the parent dictionary
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # Set the value
        config[keys[-1]] = value
    
    def update_from_onboarding(self, wifi_ssid: str, wifi_password: str) -> None:
        """
        Update configuration from onboarding portal.
        
        Args:
            wifi_ssid: WiFi network SSID
            wifi_password: WiFi network password
        """
        self.set('version', CONFIG_VERSION)
        self.set('network.provisioned', True)
        self.set('network.wifi_ssid', wifi_ssid.strip())
        self.set('network.wifi_password', wifi_password)
        
        logger.info(f"Updated configuration with WiFi SSID: {wifi_ssid}")
    
    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        from utils import get_env_device_id, API_SENSOR_ENDPOINT, STREAM_REGISTER_URL
        return {
            'version': CONFIG_VERSION,
            'device': {
                'id': get_env_device_id(),
            },
            'api': {
                'sensor_url': API_SENSOR_ENDPOINT,
                'stream_register_url': STREAM_REGISTER_URL,
                'timeout_sensor': 30.0,
                'timeout_stream_register': 10.0,
            },
            'network': {
                'provisioned': False,
                'wifi_ssid': '',
                'wifi_password': '',
                'wifi': {
                    'interface': 'wlan0',
                    'connect_timeout': 12,
                    'connect_retries': 4,
                },
            },
            'ap_mode': {
                'ssid': 'growmate-a1b2c3',
                'password': 'growmate',
                'channel': 1,
                'ip_address': '192.168.4.1',
                'netmask': '255.255.255.0',
                'dhcp_range_start': '192.168.4.2',
                'dhcp_range_end': '192.168.4.20',
                'interface': 'wlan0',
            },
            'onboarding': {
                'host': '0.0.0.0',
                'port': 80,
            },
            'intervals': {
                'sensor_reading': 60,
                'failure_monitor': 30,
                'camera_watchdog': 30,
                'queue_cleanup': 3600,
                'queue_vacuum': 604800,
                'queue_stats': 300,
                'health_check': 300,
            },
            'queue': {
                'enabled': True,
                'db_path': '/var/lib/growmate/queue.db',
                'max_age_hours': 24,
                'max_sensor_entries': 1440,
                'cleanup_interval': 3600,
                'max_retries': 5,
                'vacuum_interval': 604800,
            },
            'upload_processor': {
                'max_concurrent': 3,
                'delay': 0.5,
                'idle_sleep': 2.0,
                'batch_sleep': 0.1,
            },
            'retry': {
                'max_attempts': 6,
                'initial_delay': 1.0,
                'max_delay': 32.0,
                'jitter': 0.25,
            },
            'circuit_breaker': {
                'failure_threshold': 5,
                'recovery_timeout': 60,
                'success_threshold': 2,
            },
            'sensors': {
                'enable_dht22': True,
                'dht22_pin': 4,
                'adc': {
                    'i2c_bus': 1,
                    'i2c_address': 0x48,
                    'gain': 1,
                    'samples': 8,
                    'sample_delay': 0.01,
                    'max_value': 65535,
                },
                'channels': {
                    'battery_current': 0,
                    'light': 1,
                    'water': 2,
                    'soil': 3,
                },
                'calibration': {
                    'soil': {'min': 0, 'max': 65535},
                    'light': {'min': 0, 'max': 65535},
                    'water': {'min': 0, 'max': 65535},
                },
                'battery_current': {
                    'midpoint_voltage': 2.5,
                    'sensitivity': 0.185,
                },
                'limit_switches': {
                    'tank_gpio': 20,
                    'drawer_gpio': 21,
                    'pull_up_down': 'PUD_UP',
                    'debounce_ms': 50,
                    'debounce_samples': 5,
                    'debounce_sample_interval': 0.01,
                },
                'health': {
                    'failure_threshold': 3,
                },
            },
            'actuators': {
                'pins': {
                    'pump': 10,
                    'fertilizer': 17,
                    'pesticide': 27,
                },
                'active_high': True,
                'initial_value': False,
                'journal_size': 1000,
                'journal_trim': 500,
            },
            'camera': {
                'enabled': True,
                'port': 8554,
                'width': 640,
                'height': 480,
                'framerate': 15,
                'bitrate': 1000000,
                'profile': 'baseline',
                'level': '3.1',
                'denoise': 'cdn_off',
                'restart_delay': 0.5,
                'log_path': '/var/log/growmate/rpicam-vid.log',
            },
            'failure': {
                'consecutive_threshold': 5,
            },
            'health_monitor': {
                'history_size': 100,
                'camera_crash_threshold': 5,
            },
            'stream_registration': {
                'max_attempts': 10,
                'base_delay': 1.0,
                'max_delay': 60.0,
            },
            'logging': {
                'level': 'INFO',
                'file': '/var/log/growmate/growmate.log',
                'format': 'json',
                'max_bytes': 10485760,
                'backup_count': 5,
                'modules': {},
            },
            'features': {
                'offline_queue': True,
                'hot_reload': True,
                'circuit_breaker': True,
            },
        }
    
    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults and save."""
        self.config = self.get_default_config()
        self.save()
        logger.info("Configuration reset to defaults")
    
    def validate(self, config_dict: Optional[Dict[str, Any]] = None) -> bool:
        """
        Validate configuration using Pydantic models.
        
        Uses config_validator module for comprehensive validation.
        
        Args:
            config_dict: Configuration to validate (default: current config)
            
        Returns:
            True if valid
            
        Raises:
            ValidationError: If configuration is invalid
        """
        from config_validator import validate_config
        
        config_to_validate = config_dict if config_dict is not None else self.config
        
        try:
            validate_config(config_to_validate)
            logger.debug("Configuration validation passed")
            return True
        except ValidationError as e:
            logger.error(f"Configuration validation failed: {e}")
            raise
    
    def reload(self) -> Dict[str, tuple]:
        """
        Reload configuration from file (hot-reload).
        
        Validates new config, identifies changes, applies reloadable changes.
        
        Returns:
            Dictionary of changes: {key: (old_value, new_value)}
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If config file is invalid
            ValidationError: If config validation fails
            ValueError: If non-reloadable settings changed
        """
        from config_validator import get_config_changes, is_reloadable_change
        
        logger.info("Reloading configuration...")
        
        # Save current config
        old_config = self.config.copy()
        
        # Load new config from file
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        try:
            with open(self.config_path, 'r') as f:
                new_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse config file during reload: {e}")
            raise
        
        # Apply env var overrides to the new config (they always win)
        self._apply_env_overrides(new_config)

        if self.enable_validation:
            try:
                self.validate(new_config)
            except ValidationError as e:
                logger.error(f"New configuration is invalid, keeping current config: {e}")
                raise

        changes = get_config_changes(old_config, new_config)
        
        if not changes:
            logger.info("No configuration changes detected")
            return {}
        
        # Check if any non-reloadable settings changed
        non_reloadable_changes = {
            key: value for key, value in changes.items()
            if not is_reloadable_change(key)
        }
        
        if non_reloadable_changes:
            logger.warning(
                f"Non-reloadable settings changed (restart required): "
                f"{list(non_reloadable_changes.keys())}"
            )
            # Don't apply changes, keep current config
            raise ValueError(
                f"Non-reloadable settings changed (restart required): "
                f"{list(non_reloadable_changes.keys())}"
            )
        
        # Apply new config
        self.config = new_config
        
        # Log changes
        logger.info(f"Configuration reloaded successfully ({len(changes)} changes)")
        for key, (old_val, new_val) in changes.items():
            logger.info(f"  {key}: {old_val} -> {new_val}")
        
        # Notify callbacks
        self._notify_reload_callbacks(changes)
        
        return changes
    
    def register_reload_callback(self, callback: Callable):
        """
        Register a callback to be called when config is reloaded.
        
        Allows components to react to config changes.
        
        Args:
            callback: Callback function(changes: Dict[str, tuple])
        """
        if callback not in self.reload_callbacks:
            self.reload_callbacks.append(callback)
            logger.debug(f"Registered reload callback: {callback.__name__}")
    
    def unregister_reload_callback(self, callback: Callable):
        """
        Unregister a reload callback.
        
        Args:
            callback: Callback function to remove
        """
        if callback in self.reload_callbacks:
            self.reload_callbacks.remove(callback)
            logger.debug(f"Unregistered reload callback: {callback.__name__}")
    
    def _notify_reload_callbacks(self, changes: Dict[str, tuple]):
        """
        Notify all registered callbacks of config changes.
        
        Args:
            changes: Dictionary of changes {key: (old_value, new_value)}
        """
        for callback in self.reload_callbacks:
            try:
                callback(changes)
            except Exception as e:
                logger.error(f"Error in reload callback {callback.__name__}: {e}", exc_info=True)


# Convenience functions
def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load configuration from file."""
    manager = ConfigManager(config_path)
    return manager.load()


def save_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> None:
    """Save configuration to file."""
    manager = ConfigManager(config_path)
    manager.save(config)


def is_provisioned(config_path: Optional[Path] = None) -> bool:
    """Check if device is provisioned."""
    manager = ConfigManager(config_path)
    manager.load()
    return manager.is_provisioned()
