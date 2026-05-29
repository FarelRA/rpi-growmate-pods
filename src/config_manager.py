"""
Configuration management for GrowMate Pods.

Handles YAML configuration file read/write, validation, and hot-reload.
Configuration is stored at /etc/growmate/config.yaml.

Added Pydantic validation and hot-reload support.
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
CONFIG_VERSION = 8  # Incremented for validation and hot-reload support


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
        
    def load(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file.
        
        Returns:
            Configuration dictionary
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If config file is invalid
            ValidationError: If config validation fails
        """
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return self.get_default_config()
        
        try:
            with open(self.config_path, 'r') as f:
                config_dict = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {self.config_path}")
                
                # Validate version
                if config_dict.get('version') != CONFIG_VERSION:
                    logger.warning(
                        f"Config version mismatch: expected {CONFIG_VERSION}, "
                        f"got {config_dict.get('version')}"
                    )
                
                # Validate configuration
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
        """
        Get default configuration.
        
        Returns:
            Default configuration dictionary
        """
        from utils import get_device_id, API_SENSOR_ENDPOINT
        
        return {
            'version': CONFIG_VERSION,
            'device': {
                'id': get_device_id(),
            },
            'network': {
                'provisioned': False,
                'wifi_ssid': '',
                'wifi_password': '',
            },
            'api': {
                'sensor_url': API_SENSOR_ENDPOINT,
                'camera_url': API_SENSOR_ENDPOINT.replace('/sensors', '/camera'),
            },
            'intervals': {
                'sensor_reading': 15,      # seconds
                'camera_capture': 900,     # seconds (15 minutes)
            },
            'camera': {
                # Full 5MP resolution for Pi Camera v1
                'width': 2592,             # 5MP width
                'height': 1944,            # 5MP height
                'quality': 85,             # JPEG quality (50-100)
                'add_exif': True,          # Add EXIF metadata
            },
            'queue': {
                # Offline queue for 1-day capacity
                'enabled': True,           # Enable offline queue
                'max_age_hours': 24,       # Delete entries older than this
                'max_sensor_entries': 6000,  # ~1 day at 15s intervals
                'max_image_entries': 100,  # ~1 day at 15m intervals
                'cleanup_interval': 3600,  # seconds (1 hour)
                'max_retries': 5,          # Maximum upload retry attempts
            },
            'retry': {
                # Exponential backoff with jitter
                'max_attempts': 6,         # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s
                'initial_delay': 1.0,      # seconds
                'max_delay': 32.0,         # seconds
                'jitter': 0.25,            # ±25% random jitter
            },
            'circuit_breaker': {
                # Circuit breaker pattern
                'failure_threshold': 5,    # Open circuit after N consecutive failures
                'recovery_timeout': 60,    # seconds in OPEN state before HALF_OPEN
                'success_threshold': 2,    # Close circuit after N successes in HALF_OPEN
            },
            'calibration': {
                'soil_moisture': {'min': 0, 'max': 65535},
                'light': {'min': 0, 'max': 65535},
                'water_level': {'min': 0, 'max': 65535},
            },
            'sensors': {
                'enable_dht22': True,
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
        
        # Validate new config
        if self.enable_validation:
            try:
                self.validate(new_config)
            except ValidationError as e:
                logger.error(f"New configuration is invalid, keeping current config: {e}")
                raise
        
        # Get changes
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
