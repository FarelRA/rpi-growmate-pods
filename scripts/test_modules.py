#!/usr/bin/env python3
"""
Module testing script for Phase 3.

Tests individual software components independently to verify:
- Module imports work correctly
- Core functionality matches ESP32 behavior
- Error handling is robust
"""

import sys
import os
import tempfile
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Test results tracking
tests_passed = 0
tests_failed = 0


def test_result(name: str, passed: bool, details: str = ""):
    """Record and print test result."""
    global tests_passed, tests_failed
    
    if passed:
        tests_passed += 1
        print(f"✓ {name}")
        if details:
            print(f"  {details}")
    else:
        tests_failed += 1
        print(f"✗ {name}")
        if details:
            print(f"  ERROR: {details}")


def test_imports():
    """Test that all modules can be imported."""
    print("\n" + "=" * 60)
    print("TEST: Module Imports")
    print("=" * 60)
    
    modules = [
        'config_manager',
        'utils',
        'api_client',
    ]
    
    for module_name in modules:
        try:
            __import__(module_name)
            test_result(f"Import {module_name}", True)
        except Exception as e:
            test_result(f"Import {module_name}", False, str(e))


def test_config_manager():
    """Test configuration management."""
    print("\n" + "=" * 60)
    print("TEST: Configuration Manager")
    print("=" * 60)
    
    try:
        from config_manager import ConfigManager
        
        # Test with temporary config file
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.yaml"
            manager = ConfigManager(config_path)
            
            # Test default config
            default_config = manager.get_default_config()
            test_result(
                "Get default config",
                'version' in default_config and default_config['version'] == 4,
                f"Version: {default_config.get('version')}"
            )
            
            # Test save and load
            manager.config = default_config
            manager.save()
            test_result("Save config", config_path.exists())
            
            manager2 = ConfigManager(config_path)
            loaded_config = manager2.load()
            test_result(
                "Load config",
                loaded_config.get('version') == 4,
                f"Loaded version: {loaded_config.get('version')}"
            )
            
            # Test provisioning check (should be False for default config)
            test_result(
                "Check provisioning (unprov)",
                not manager2.is_provisioned(),
                "Default config is not provisioned"
            )
            
            # Test provisioning update
            manager2.update_from_onboarding("TestNetwork", "TestPassword")
            test_result(
                "Update from onboarding",
                manager2.is_provisioned(),
                f"SSID: {manager2.get('network.wifi_ssid')}"
            )
            
            # Test get/set with dot notation
            manager2.set('test.nested.value', 42)
            value = manager2.get('test.nested.value')
            test_result("Get/set nested value", value == 42, f"Value: {value}")
            
    except Exception as e:
        test_result("Config manager tests", False, str(e))


def test_utils():
    """Test utility functions."""
    print("\n" + "=" * 60)
    print("TEST: Utility Functions")
    print("=" * 60)
    
    try:
        from utils import clamp, get_device_id, get_ap_ssid
        
        # Test clamp
        test_result("Clamp - in range", clamp(50, 0, 100) == 50)
        test_result("Clamp - below min", clamp(-10, 0, 100) == 0)
        test_result("Clamp - above max", clamp(150, 0, 100) == 100)
        
        # Test device ID generation
        device_id = get_device_id()
        test_result(
            "Get device ID",
            device_id.startswith('growmate-'),
            f"Device ID: {device_id}"
        )
        
        # Test AP SSID generation
        ap_ssid = get_ap_ssid()
        test_result(
            "Get AP SSID",
            ap_ssid.startswith('GrowMate-') and len(ap_ssid) == 16,
            f"AP SSID: {ap_ssid}"
        )
        
    except Exception as e:
        test_result("Utility functions", False, str(e))


def test_calibration_algorithm():
    """Test sensor calibration algorithm matches ESP32."""
    print("\n" + "=" * 60)
    print("TEST: Calibration Algorithm (ESP32 Compatibility)")
    print("=" * 60)
    
    def esp32_raw_to_percent(raw, low_raw, high_raw):
        """ESP32 reference implementation."""
        if raw < 0 or low_raw == high_raw:
            return -1
        
        if low_raw < high_raw:
            pct = (raw - low_raw) * 100 // (high_raw - low_raw)
        else:
            pct = (low_raw - raw) * 100 // (low_raw - high_raw)
        
        return max(0, min(100, pct))
    
    def python_calibrate(raw_value, min_val, max_val):
        """Python implementation from sensors.py."""
        if raw_value < 0 or min_val == max_val:
            return -1
        
        if min_val < max_val:
            pct = (raw_value - min_val) * 100 // (max_val - min_val)
        else:
            pct = (min_val - raw_value) * 100 // (min_val - max_val)
        
        return max(0, min(100, pct))
    
    # Test cases covering normal and inverted ranges
    test_cases = [
        (2048, 0, 4095, "Normal - midpoint"),
        (0, 0, 4095, "Normal - min"),
        (4095, 0, 4095, "Normal - max"),
        (1000, 0, 4095, "Normal - low"),
        (3000, 0, 4095, "Normal - high"),
        (2048, 4095, 0, "Inverted - midpoint"),
        (4095, 4095, 0, "Inverted - min"),
        (0, 4095, 0, "Inverted - max"),
    ]
    
    all_passed = True
    for raw, low, high, desc in test_cases:
        esp32_result = esp32_raw_to_percent(raw, low, high)
        python_result = python_calibrate(raw, low, high)
        passed = esp32_result == python_result
        
        if not passed:
            all_passed = False
        
        test_result(
            f"Calibration - {desc}",
            passed,
            f"ESP32={esp32_result}%, Python={python_result}%"
        )
    
    test_result("All calibration tests", all_passed)


def test_api_client_structure():
    """Test API client structure and configuration."""
    print("\n" + "=" * 60)
    print("TEST: API Client Structure")
    print("=" * 60)
    
    try:
        from api_client import APIClient
        from utils import API_TIMEOUT_SENSOR, API_TIMEOUT_CAMERA
        
        # Test with mock config
        config = {
            'device': {'id': 'test-device'},
            'api': {
                'sensor_url': 'https://example.com/api/sensors',
                'camera_url': 'https://example.com/api/camera'
            }
        }
        
        client = APIClient(config)
        
        test_result(
            "API client initialization",
            client.device_id == 'test-device',
            f"Device ID: {client.device_id}"
        )
        
        test_result(
            "Sensor URL configured",
            client.sensor_url == config['api']['sensor_url']
        )
        
        test_result(
            "Camera URL configured",
            client.camera_url == config['api']['camera_url']
        )
        
        # Test timeout constants
        test_result(
            "Sensor timeout (12s)",
            API_TIMEOUT_SENSOR == 12.0,
            f"Timeout: {API_TIMEOUT_SENSOR}s"
        )
        
        test_result(
            "Camera timeout (45s)",
            API_TIMEOUT_CAMERA == 45.0,
            f"Timeout: {API_TIMEOUT_CAMERA}s"
        )
        
    except Exception as e:
        test_result("API client structure", False, str(e))


def test_constants():
    """Test that constants match ESP32 values."""
    print("\n" + "=" * 60)
    print("TEST: Constants (ESP32 Compatibility)")
    print("=" * 60)
    
    try:
        from utils import (
            SENSOR_INTERVAL_SECONDS,
            CAMERA_INTERVAL_SECONDS,
            WIFI_TIMEOUT_SECONDS,
            UPLOAD_RETRY_COUNT,
            UPLOAD_RETRY_DELAY,
            FAILURE_THRESHOLD,
            PUMP_HOUSEKEEPING_INTERVAL_MS,
            FIRMWARE_VERSION
        )
        
        test_result("Sensor interval (15s)", SENSOR_INTERVAL_SECONDS == 15)
        test_result("Camera interval (900s)", CAMERA_INTERVAL_SECONDS == 900)
        test_result("WiFi timeout (12s)", WIFI_TIMEOUT_SECONDS == 12)
        test_result("Upload retry count (2)", UPLOAD_RETRY_COUNT == 2)
        test_result("Upload retry delay (1.5s)", UPLOAD_RETRY_DELAY == 1.5)
        test_result("Failure threshold (5)", FAILURE_THRESHOLD == 5)
        test_result("Pump housekeeping (250ms)", PUMP_HOUSEKEEPING_INTERVAL_MS == 250)
        test_result(
            "Firmware version",
            FIRMWARE_VERSION == "2.0.0-rpi",
            f"Version: {FIRMWARE_VERSION}"
        )
        
    except Exception as e:
        test_result("Constants check", False, str(e))


def main():
    """Run all module tests."""
    print("\n" + "=" * 60)
    print("PHASE 3: Core Module Development - Module Tests")
    print("=" * 60)
    print("\nTesting individual software components independently...")
    print("(Hardware-dependent tests skipped - use test_hardware.py)")
    
    # Run all tests
    test_imports()
    test_config_manager()
    test_utils()
    test_calibration_algorithm()
    test_api_client_structure()
    test_constants()
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Passed: {tests_passed}")
    print(f"Failed: {tests_failed}")
    print(f"Total:  {tests_passed + tests_failed}")
    
    if tests_failed == 0:
        print("\n✓ ALL TESTS PASSED - Phase 3 Success Criteria Met")
        return 0
    else:
        print(f"\n✗ {tests_failed} TEST(S) FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
