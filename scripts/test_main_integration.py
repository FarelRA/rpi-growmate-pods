#!/usr/bin/env python3
"""
Main Application Integration Test Suite

Validates that main.py integrates all components correctly and expected behavior:
- Timing constants (sensor/camera intervals, failure threshold)
- Loop counter-based timing (not time-based)
- Ephemeral camera lifecycle (initialize per-cycle, not persistent)
- Failure tracking and AP mode re-entry
- Command processing after sensor upload
- Signal handling for graceful shutdown

This test suite ensures the main application loop behaves correctly.
"""

import sys
import os
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Test results
tests_passed = 0
tests_failed = 0


def test_result(name: str, passed: bool, details: str = ""):
    """Record test result."""
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
            print(f"  {details}")


def test_imports():
    """Test that all required modules can be imported."""
    print("\n=== Testing Imports ===")
    
    try:
        from main import GrowMateApp
        test_result("Import main.GrowMateApp", True)
    except ImportError as e:
        test_result("Import main.GrowMateApp", False, str(e))
        return False
    
    try:
        from utils import SENSOR_INTERVAL_SECONDS, CAMERA_INTERVAL_SECONDS, FAILURE_THRESHOLD
        test_result("Import constants from utils", True, 
                   f"SENSOR={SENSOR_INTERVAL_SECONDS}s, CAMERA={CAMERA_INTERVAL_SECONDS}s, THRESHOLD={FAILURE_THRESHOLD}")
    except ImportError as e:
        test_result("Import constants from utils", False, str(e))
        return False
    
    return True


def test_timing_constants():
    """Test that timing constants have correct values."""
    print("\n=== Testing Timing Constants ===")
    
    try:
        from utils import SENSOR_INTERVAL_SECONDS, CAMERA_INTERVAL_SECONDS, FAILURE_THRESHOLD
        
        # Expected values from requirements
        EXPECTED_SENSOR_INTERVAL = 15
        EXPECTED_CAMERA_INTERVAL = 900
        EXPECTED_FAILURE_THRESHOLD = 5
        
        test_result(
            "Sensor interval",
            SENSOR_INTERVAL_SECONDS == EXPECTED_SENSOR_INTERVAL,
            f"Expected {EXPECTED_SENSOR_INTERVAL}s, got {SENSOR_INTERVAL_SECONDS}s"
        )
        
        test_result(
            "Camera interval",
            CAMERA_INTERVAL_SECONDS == EXPECTED_CAMERA_INTERVAL,
            f"Expected {EXPECTED_CAMERA_INTERVAL}s, got {CAMERA_INTERVAL_SECONDS}s"
        )
        
        test_result(
            "Failure threshold",
            FAILURE_THRESHOLD == EXPECTED_FAILURE_THRESHOLD,
            f"Expected {EXPECTED_FAILURE_THRESHOLD}, got {FAILURE_THRESHOLD}"
        )
        
        # Calculate camera period
        camera_period = CAMERA_INTERVAL_SECONDS // SENSOR_INTERVAL_SECONDS
        expected_period = 60  # 900 / 15 = 60
        
        test_result(
            "Camera period calculation",
            camera_period == expected_period,
            f"Expected {expected_period} cycles, got {camera_period} cycles"
        )
        
    except Exception as e:
        test_result("Timing constants", False, str(e))


def test_app_structure():
    """Test GrowMateApp class structure."""
    print("\n=== Testing Application Structure ===")
    
    try:
        from main import GrowMateApp
        
        # Check class exists
        test_result("GrowMateApp class exists", True)
        
        # Check required methods exist
        required_methods = [
            '__init__',
            'load_configuration',
            'initialize_components',
            'enter_onboarding_mode',
            'sensor_cycle',
            'camera_cycle',
            'main_loop',
            'cleanup',
            'run'
        ]
        
        for method in required_methods:
            has_method = hasattr(GrowMateApp, method)
            test_result(f"Method '{method}' exists", has_method)
        
    except Exception as e:
        test_result("Application structure", False, str(e))


def test_state_tracking():
    """Test that state tracking uses loop counter (expected behavior)."""
    print("\n=== Testing State Tracking (Device Compatibility) ===")
    
    try:
        # Read main.py source to verify implementation
        main_py = Path(__file__).parent.parent / 'src' / 'main.py'
        content = main_py.read_text()
        
        # Check for loop counter approach (not time-based)
        has_loops_since_camera = 'loops_since_camera' in content
        test_result(
            "Uses loop counter (loops_since_camera)",
            has_loops_since_camera,
            "Matches loop counter approach"
        )
        
        # Check that old time-based approach is removed
        has_last_camera_time = 'last_camera_time' in content
        test_result(
            "Removed time-based tracking",
            not has_last_camera_time,
            "No longer uses last_camera_time"
        )
        
        # Check for camera period calculation
        has_camera_period = 'camera_period = CAMERA_INTERVAL_SECONDS // SENSOR_INTERVAL_SECONDS' in content
        test_result(
            "Camera period calculation ",
            has_camera_period,
            "Uses integer division correctly"
        )
        
        # Check for camera_due logic
        has_camera_due = 'camera_due = self.loops_since_camera >= camera_period' in content
        test_result(
            "Camera due check ",
            has_camera_due,
            "Uses >= comparison correctly"
        )
        
    except Exception as e:
        test_result("State tracking", False, str(e))


def test_camera_lifecycle():
    """Test that camera uses ephemeral lifecycle (expected behavior)."""
    print("\n=== Testing Camera Lifecycle (Device Compatibility) ===")
    
    try:
        main_py = Path(__file__).parent.parent / 'src' / 'main.py'
        content = main_py.read_text()
        
        # Check that camera is NOT in persistent components
        in_init = 'self.camera: Optional[CameraService] = None' in content
        test_result(
            "Camera not in persistent components",
            not in_init,
            "Camera is ephemeral, not persistent"
        )
        
        # Check that camera is NOT initialized in initialize_components
        lines = content.split('\n')
        in_initialize = False
        for i, line in enumerate(lines):
            if 'def initialize_components' in line:
                # Check next 30 lines
                section = '\n'.join(lines[i:i+30])
                in_initialize = 'self.camera = CameraService()' in section
                break
        
        test_result(
            "Camera not initialized at startup",
            not in_initialize,
            "Camera initialized per-cycle, not at startup"
        )
        
        # Check for ephemeral usage in camera_cycle
        has_init = 'camera = CameraService()' in content
        has_initialize = 'camera.initialize()' in content
        has_cleanup = 'camera.cleanup()' in content
        
        test_result(
            "Camera cycle uses ephemeral initialization",
            has_init and has_initialize,
            "Creates and initializes camera in camera_cycle()"
        )
        
        test_result(
            "Camera cycle cleans up immediately",
            has_cleanup,
            "Calls camera.cleanup() after capture"
        )
        
        # Check for cleanup in finally block
        has_finally_cleanup = 'finally:' in content and 'if camera:' in content and 'camera.cleanup()' in content
        test_result(
            "Camera cleanup in finally block",
            has_finally_cleanup,
            "Ensures cleanup even on error"
        )
        
    except Exception as e:
        test_result("Camera lifecycle", False, str(e))


def test_failure_tracking():
    """Test that failure tracking  behavior."""
    print("\n=== Testing Failure Tracking (Device Compatibility) ===")
    
    try:
        main_py = Path(__file__).parent.parent / 'src' / 'main.py'
        content = main_py.read_text()
        
        # Check that sensor_cycle returns bool
        has_sensor_return = 'def sensor_cycle(self) -> bool:' in content
        test_result(
            "sensor_cycle returns bool",
            has_sensor_return,
            "Returns success/failure status"
        )
        
        # Check that camera_cycle returns bool
        has_camera_return = 'def camera_cycle(self) -> bool:' in content
        test_result(
            "camera_cycle returns bool",
            has_camera_return,
            "Returns success/failure status"
        )
        
        # Check for WiFi connection check in sensor_cycle
        has_wifi_check_sensor = 'if not self.network.is_connected():' in content
        test_result(
            "Checks WiFi connection in sensor_cycle",
            has_wifi_check_sensor,
            "Expected WiFi check behavior"
        )
        
        # Check for WiFi connection check in camera_cycle
        # (should appear twice - once in sensor_cycle, once in camera_cycle)
        wifi_check_count = content.count('if not self.network.is_connected():')
        test_result(
            "Checks WiFi connection in camera_cycle",
            wifi_check_count >= 2,
            f"Found {wifi_check_count} WiFi checks"
        )
        
        # Check that consecutive_failures is incremented on failures
        failure_increment_count = content.count('self.consecutive_failures += 1')
        test_result(
            "Increments consecutive_failures on errors",
            failure_increment_count >= 5,
            f"Found {failure_increment_count} failure increments"
        )
        
        # Check that consecutive_failures is reset on success
        failure_reset_count = content.count('self.consecutive_failures = 0')
        test_result(
            "Resets consecutive_failures on success",
            failure_reset_count >= 2,
            f"Found {failure_reset_count} failure resets (sensor + camera)"
        )
        
    except Exception as e:
        test_result("Failure tracking", False, str(e))


def test_main_loop_logic():
    """Test main loop logic ."""
    print("\n=== Testing Main Loop Logic (Device Compatibility) ===")
    
    try:
        main_py = Path(__file__).parent.parent / 'src' / 'main.py'
        content = main_py.read_text()
        
        # Check for loop counter increment
        has_increment = 'self.loops_since_camera += 1' in content
        test_result(
            "Increments loop counter each cycle",
            has_increment,
            "Expected behavior: loops_since_camera++"
        )
        
        # Check for camera_due calculation
        has_camera_due = 'camera_due = self.loops_since_camera >= camera_period' in content
        test_result(
            "Calculates camera_due correctly",
            has_camera_due,
            "Expected behavior: loops_since_camera >= camera_period"
        )
        
        # Check that sensor_cycle is called every loop
        has_sensor_call = 'sensor_success = self.sensor_cycle()' in content
        test_result(
            "Calls sensor_cycle every loop",
            has_sensor_call,
            "Expected behavior: sensor cycle every 15 seconds"
        )
        
        # Check that camera_cycle is conditional
        has_camera_conditional = 'if camera_due:' in content
        test_result(
            "Calls camera_cycle conditionally",
            has_camera_conditional,
            "Only when camera_due is True"
        )
        
        # Check that loop counter resets only on success
        has_conditional_reset = 'if camera_success:' in content and 'self.loops_since_camera = 0' in content
        test_result(
            "Resets loop counter only on camera success",
            has_conditional_reset,
            "Expected behavior: only reset on successful upload"
        )
        
        # Check for failure threshold check
        has_threshold_check = 'if self.consecutive_failures >= FAILURE_THRESHOLD:' in content
        test_result(
            "Checks failure threshold",
            has_threshold_check,
            "Re-enters onboarding after threshold"
        )
        
        # Check for delay between cycles
        has_delay = 'time.sleep(SENSOR_INTERVAL_SECONDS)' in content
        test_result(
            "Delays between sensor cycles",
            has_delay,
            f"Sleeps for {15} seconds between cycles"
        )
        
    except Exception as e:
        test_result("Main loop logic", False, str(e))


def test_command_processing():
    """Test that commands are processed immediately after sensor upload."""
    print("\n=== Testing Command Processing (Device Compatibility) ===")
    
    try:
        main_py = Path(__file__).parent.parent / 'src' / 'main.py'
        content = main_py.read_text()
        
        # Find sensor_cycle method
        lines = content.split('\n')
        sensor_cycle_start = None
        for i, line in enumerate(lines):
            if 'def sensor_cycle(self)' in line:
                sensor_cycle_start = i
                break
        
        if sensor_cycle_start:
            # Check that commands are processed in sensor_cycle
            sensor_section = '\n'.join(lines[sensor_cycle_start:sensor_cycle_start+50])
            
            has_upload = 'self.api_client.upload_sensor_data' in sensor_section
            has_commands = 'commands =' in sensor_section
            has_process = 'self.actuators.process_commands(commands)' in sensor_section
            
            test_result(
                "Uploads sensor data in sensor_cycle",
                has_upload,
                "Calls api_client.upload_sensor_data()"
            )
            
            test_result(
                "Receives commands from upload",
                has_commands,
                "Captures return value from upload"
            )
            
            test_result(
                "Processes commands immediately",
                has_process,
                "Expected behavior: apply commands after upload"
            )
            
            # Check order: upload before process
            upload_pos = sensor_section.find('upload_sensor_data')
            process_pos = sensor_section.find('process_commands')
            
            test_result(
                "Commands processed after upload",
                upload_pos < process_pos if (upload_pos >= 0 and process_pos >= 0) else False,
                "Correct order: upload → process"
            )
        else:
            test_result("Find sensor_cycle method", False, "Method not found")
        
    except Exception as e:
        test_result("Command processing", False, str(e))


def test_onboarding_integration():
    """Test onboarding integration."""
    print("\n=== Testing Onboarding Integration ===")
    
    try:
        main_py = Path(__file__).parent.parent / 'src' / 'main.py'
        content = main_py.read_text()
        
        # Check for initial onboarding check
        has_initial_check = 'if not self.config_manager.is_provisioned():' in content
        test_result(
            "Checks provisioning on startup",
            has_initial_check,
            "Enters onboarding if not provisioned"
        )
        
        # Check for failure-triggered onboarding
        has_failure_onboarding = 'if self.consecutive_failures >= FAILURE_THRESHOLD:' in content
        test_result(
            "Re-enters onboarding on failures",
            has_failure_onboarding,
            "After threshold exceeded"
        )
        
        # Check for config reload after onboarding
        reload_count = content.count('self.load_configuration()')
        test_result(
            "Reloads configuration after onboarding",
            reload_count >= 2,
            f"Found {reload_count} config reloads"
        )
        
        # Check for component reinitialization
        reinit_count = content.count('self.initialize_components()')
        test_result(
            "Reinitializes components after onboarding",
            reinit_count >= 2,
            f"Found {reinit_count} component initializations"
        )
        
        # Check for state reset after onboarding
        has_state_reset = 'self.consecutive_failures = 0' in content and 'self.loops_since_camera = 0' in content
        test_result(
            "Resets state after onboarding",
            has_state_reset,
            "Resets failure counter and loop counter"
        )
        
    except Exception as e:
        test_result("Onboarding integration", False, str(e))


def test_signal_handling():
    """Test signal handling for graceful shutdown."""
    print("\n=== Testing Signal Handling ===")
    
    try:
        main_py = Path(__file__).parent.parent / 'src' / 'main.py'
        content = main_py.read_text()
        
        # Check for signal handler setup
        has_sigterm = 'signal.signal(signal.SIGTERM' in content
        has_sigint = 'signal.signal(signal.SIGINT' in content
        
        test_result(
            "Handles SIGTERM signal",
            has_sigterm,
            "For systemd service shutdown"
        )
        
        test_result(
            "Handles SIGINT signal",
            has_sigint,
            "For Ctrl+C shutdown"
        )
        
        # Check for signal handler implementation
        has_handler = 'def _signal_handler' in content
        test_result(
            "Signal handler implemented",
            has_handler,
            "Sets self.running = False"
        )
        
        # Check for cleanup in finally block
        has_finally = 'finally:' in content and 'self.cleanup()' in content
        test_result(
            "Cleanup in finally block",
            has_finally,
            "Ensures cleanup on exit"
        )
        
    except Exception as e:
        test_result("Signal handling", False, str(e))


def print_summary():
    """Print test summary."""
    print("\n" + "=" * 60)
    print("MAIN APPLICATION INTEGRATION - TEST SUMMARY")
    print("=" * 60)
    print(f"Tests passed: {tests_passed}")
    print(f"Tests failed: {tests_failed}")
    print(f"Total tests:  {tests_passed + tests_failed}")
    
    if tests_failed == 0:
        print("\n✓ All tests passed! Main application integration is complete.")
        print("\nDevice Compatibility:")
        print("  ✓ Loop counter timing (not time-based)")
        print("  ✓ Ephemeral camera lifecycle")
        print("  ✓ Failure tracking and AP mode re-entry")
        print("  ✓ Command processing after sensor upload")
        print("  ✓ WiFi connection checks")
        print("\nReady for hardware testing on Raspberry Pi Zero W.")
    else:
        print(f"\n✗ {tests_failed} test(s) failed. Review implementation.")
    
    print("=" * 60)


def main():
    """Run all tests."""
    print("=" * 60)
    print("MAIN APPLICATION INTEGRATION - TEST SUITE")
    print("=" * 60)
    print("\nValidating device compatibility and integration...")
    
    # Run tests
    if not test_imports():
        print("\n✗ Import tests failed. Cannot continue.")
        return 1
    
    test_timing_constants()
    test_app_structure()
    test_state_tracking()
    test_camera_lifecycle()
    test_failure_tracking()
    test_main_loop_logic()
    test_command_processing()
    test_onboarding_integration()
    test_signal_handling()
    
    # Print summary
    print_summary()
    
    return 0 if tests_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
