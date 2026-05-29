"""
Configuration management for GrowMate Pods.

Handles YAML configuration file read/write, validation, and defaults.
Configuration is stored at /etc/growmate/config.yaml.
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from pathlib import Path


logger = logging.getLogger("growmate.config")


# Configuration file path
CONFIG_DIR = Path("/etc/growmate")
CONFIG_FILE = CONFIG_DIR / "config.yaml"
CONFIG_VERSION = 4


class ConfigManager:
    """Manages GrowMate configuration stored in YAML format."""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to config file (default: /etc/growmate/config.yaml)
        """
        self.config_path = config_path or CONFIG_FILE
        self.config: Dict[str, Any] = {}
        
    def load(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file.
        
        Returns:
            Configuration dictionary
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If config file is invalid
        """
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return self.get_default_config()
        
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {self.config_path}")
                
                # Validate version
                if self.config.get('version') != CONFIG_VERSION:
                    logger.warning(
                        f"Config version mismatch: expected {CONFIG_VERSION}, "
                        f"got {self.config.get('version')}"
                    )
                
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
        
        Based on ESP32 logic: provisioned flag must be true and WiFi SSID must exist.
        
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
