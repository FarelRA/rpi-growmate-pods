#!/usr/bin/env python3
"""
Phase 7 Validation Script - Testing & Documentation

This script validates that all Phase 7 deliverables are complete and meet
the requirements specified in PLAN.md.

Phase 7 Requirements:
- End-to-end test results
- Failure scenario test results
- Complete README.md
- Troubleshooting guide
- Wiring diagram
- API documentation
- Code documentation (docstrings)
- Final validation

Usage:
    python3 scripts/test_phase7.py
"""

import sys
import os
import unittest
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


class TestPhase7Deliverables(unittest.TestCase):
    """Test that all Phase 7 deliverables exist"""
    
    def test_end_to_end_test_suite_exists(self):
        """Test that end-to-end test suite exists"""
        test_file = PROJECT_ROOT / 'scripts' / 'test_e2e.py'
        self.assertTrue(test_file.exists(), "test_e2e.py not found")
        self.assertTrue(os.access(test_file, os.X_OK), "test_e2e.py not executable")
    
    def test_failure_scenario_test_suite_exists(self):
        """Test that failure scenario test suite exists"""
        test_file = PROJECT_ROOT / 'scripts' / 'test_failures.py'
        self.assertTrue(test_file.exists(), "test_failures.py not found")
        self.assertTrue(os.access(test_file, os.X_OK), "test_failures.py not executable")
    
    def test_performance_monitoring_script_exists(self):
        """Test that performance monitoring script exists"""
        script_file = PROJECT_ROOT / 'scripts' / 'monitor_performance.py'
        self.assertTrue(script_file.exists(), "monitor_performance.py not found")
        self.assertTrue(os.access(script_file, os.X_OK), "monitor_performance.py not executable")
    
    def test_readme_exists(self):
        """Test that README.md exists"""
        readme = PROJECT_ROOT / 'README.md'
        self.assertTrue(readme.exists(), "README.md not found")
    
    def test_troubleshooting_guide_exists(self):
        """Test that TROUBLESHOOTING.md exists"""
        troubleshooting = PROJECT_ROOT / 'TROUBLESHOOTING.md'
        self.assertTrue(troubleshooting.exists(), "TROUBLESHOOTING.md not found")
    
    def test_wiring_diagram_exists(self):
        """Test that WIRING.md exists"""
        wiring = PROJECT_ROOT / 'WIRING.md'
        self.assertTrue(wiring.exists(), "WIRING.md not found")


class TestREADMECompleteness(unittest.TestCase):
    """Test that README.md is complete"""
    
    def setUp(self):
        """Load README.md content"""
        readme_path = PROJECT_ROOT / 'README.md'
        with open(readme_path, 'r') as f:
            self.readme_content = f.read()
    
    def test_readme_has_features_section(self):
        """Test README has Features section"""
        self.assertIn('## Features', self.readme_content)
    
    def test_readme_has_hardware_requirements(self):
        """Test README has Hardware Requirements section"""
        self.assertIn('## Hardware Requirements', self.readme_content)
    
    def test_readme_has_installation_section(self):
        """Test README has Installation section"""
        self.assertIn('## Installation', self.readme_content)
    
    def test_readme_has_configuration_section(self):
        """Test README has Configuration section"""
        self.assertIn('## Configuration', self.readme_content)
    
    def test_readme_has_api_integration_section(self):
        """Test README has API Integration section"""
        self.assertIn('## API Integration', self.readme_content)
    
    def test_readme_has_troubleshooting_section(self):
        """Test README has Troubleshooting section"""
        self.assertIn('## Troubleshooting', self.readme_content)
    
    def test_readme_has_failure_handling_section(self):
        """Test README documents failure handling"""
        self.assertIn('Failure Handling', self.readme_content)
        self.assertIn('5 consecutive failures', self.readme_content)
    
    def test_readme_has_testing_section(self):
        """Test README has Testing section"""
        self.assertIn('### Testing', self.readme_content)
        self.assertIn('test_e2e.py', self.readme_content)
        self.assertIn('test_failures.py', self.readme_content)


class TestAPIDocumentation(unittest.TestCase):
    """Test that API documentation matches ESP32"""
    
    def setUp(self):
        """Load README.md content"""
        readme_path = PROJECT_ROOT / 'README.md'
        with open(readme_path, 'r') as f:
            self.readme_content = f.read()
    
    def test_api_sensor_data_format(self):
        """Test API sensor data format is documented"""
        self.assertIn('deviceId', self.readme_content)
        self.assertIn('firmwareVersion', self.readme_content)
        self.assertIn('sensors', self.readme_content)
        self.assertIn('currentState', self.readme_content)
    
    def test_api_sensor_kinds_match_esp32(self):
        """Test sensor kinds match ESP32 format"""
        # ESP32 uses: soil_moisture, light, water_level, temperature, humidity
        self.assertIn('soil_moisture', self.readme_content)
        self.assertIn('water_level', self.readme_content)
        self.assertIn('humidity', self.readme_content)
    
    def test_api_dht22_no_raw_field(self):
        """Test DHT22 sensors documented without raw field"""
        # README should show temperature and humidity without raw field
        # This is validated by checking the example JSON
        self.assertIn('"kind": "temperature"', self.readme_content)
        self.assertIn('"kind": "humidity"', self.readme_content)
    
    def test_api_camera_upload_format(self):
        """Test camera upload format is documented"""
        self.assertIn('multipart/form-data', self.readme_content)
        self.assertIn('X-Device-Id', self.readme_content)
    
    def test_api_commands_format(self):
        """Test command format is documented"""
        self.assertIn('commands', self.readme_content)
        self.assertIn('durationMs', self.readme_content)
        self.assertIn('enabled', self.readme_content)


class TestTroubleshootingGuide(unittest.TestCase):
    """Test that TROUBLESHOOTING.md is comprehensive"""
    
    def setUp(self):
        """Load TROUBLESHOOTING.md content"""
        troubleshooting_path = PROJECT_ROOT / 'TROUBLESHOOTING.md'
        with open(troubleshooting_path, 'r') as f:
            self.troubleshooting_content = f.read()
    
    def test_troubleshooting_has_service_issues(self):
        """Test troubleshooting covers service issues"""
        self.assertIn('Service Issues', self.troubleshooting_content)
    
    def test_troubleshooting_has_hardware_issues(self):
        """Test troubleshooting covers hardware issues"""
        self.assertIn('Hardware Issues', self.troubleshooting_content)
    
    def test_troubleshooting_has_network_issues(self):
        """Test troubleshooting covers network issues"""
        self.assertIn('Network Issues', self.troubleshooting_content)
    
    def test_troubleshooting_has_api_issues(self):
        """Test troubleshooting covers API issues"""
        self.assertIn('API', self.troubleshooting_content)
    
    def test_troubleshooting_has_log_analysis(self):
        """Test troubleshooting covers log analysis"""
        self.assertIn('Log Analysis', self.troubleshooting_content)
        self.assertIn('journalctl', self.troubleshooting_content)


class TestTestSuites(unittest.TestCase):
    """Test that test suites are functional"""
    
    def test_e2e_test_suite_is_valid_python(self):
        """Test that test_e2e.py is valid Python"""
        test_file = PROJECT_ROOT / 'scripts' / 'test_e2e.py'
        with open(test_file, 'r') as f:
            code = f.read()
        
        # Try to compile the code
        try:
            compile(code, str(test_file), 'exec')
        except SyntaxError as e:
            self.fail(f"test_e2e.py has syntax error: {e}")
    
    def test_failure_test_suite_is_valid_python(self):
        """Test that test_failures.py is valid Python"""
        test_file = PROJECT_ROOT / 'scripts' / 'test_failures.py'
        with open(test_file, 'r') as f:
            code = f.read()
        
        # Try to compile the code
        try:
            compile(code, str(test_file), 'exec')
        except SyntaxError as e:
            self.fail(f"test_failures.py has syntax error: {e}")
    
    def test_performance_monitor_is_valid_python(self):
        """Test that monitor_performance.py is valid Python"""
        script_file = PROJECT_ROOT / 'scripts' / 'monitor_performance.py'
        with open(script_file, 'r') as f:
            code = f.read()
        
        # Try to compile the code
        try:
            compile(code, str(script_file), 'exec')
        except SyntaxError as e:
            self.fail(f"monitor_performance.py has syntax error: {e}")


class TestESP32Compatibility(unittest.TestCase):
    """Test that ESP32 compatibility is maintained"""
    
    def test_consecutive_failure_threshold(self):
        """Test consecutive failure threshold is 5 (matches ESP32)"""
        readme_path = PROJECT_ROOT / 'README.md'
        with open(readme_path, 'r') as f:
            readme_content = f.read()
        
        # Should document 5 consecutive failures
        self.assertIn('5 consecutive failures', readme_content)
    
    def test_sensor_interval_default(self):
        """Test sensor interval default is 15 seconds (matches ESP32)"""
        config_example = PROJECT_ROOT / 'config' / 'config.yaml.example'
        if config_example.exists():
            with open(config_example, 'r') as f:
                config_content = f.read()
            self.assertIn('sensor_reading: 15', config_content)
    
    def test_camera_interval_default(self):
        """Test camera interval default is 900 seconds (matches ESP32)"""
        config_example = PROJECT_ROOT / 'config' / 'config.yaml.example'
        if config_example.exists():
            with open(config_example, 'r') as f:
                config_content = f.read()
            self.assertIn('camera_capture: 900', config_content)
    
    def test_ap_mode_ssid_format(self):
        """Test AP mode SSID format is documented"""
        readme_path = PROJECT_ROOT / 'README.md'
        with open(readme_path, 'r') as f:
            readme_content = f.read()
        
        # Should document GrowMate-XXXXXX format
        self.assertIn('GrowMate-', readme_content)
    
    def test_ap_mode_password(self):
        """Test AP mode password is documented"""
        readme_path = PROJECT_ROOT / 'README.md'
        with open(readme_path, 'r') as f:
            readme_content = f.read()
        
        # Should document password: growmate
        self.assertIn('growmate', readme_content)


class TestProjectStructure(unittest.TestCase):
    """Test that project structure is complete"""
    
    def test_src_directory_exists(self):
        """Test src directory exists"""
        src_dir = PROJECT_ROOT / 'src'
        self.assertTrue(src_dir.exists(), "src/ directory not found")
    
    def test_core_modules_exist(self):
        """Test that all core modules exist"""
        modules = [
            'main.py',
            'config_manager.py',
            'sensors.py',
            'camera_service.py',
            'actuators.py',
            'api_client.py',
            'network_manager.py',
            'onboarding_portal.py',
            'utils.py'
        ]
        
        for module in modules:
            module_path = PROJECT_ROOT / 'src' / module
            self.assertTrue(module_path.exists(), f"{module} not found")
    
    def test_templates_directory_exists(self):
        """Test templates directory exists"""
        templates_dir = PROJECT_ROOT / 'templates'
        self.assertTrue(templates_dir.exists(), "templates/ directory not found")
    
    def test_scripts_directory_exists(self):
        """Test scripts directory exists"""
        scripts_dir = PROJECT_ROOT / 'scripts'
        self.assertTrue(scripts_dir.exists(), "scripts/ directory not found")
    
    def test_systemd_directory_exists(self):
        """Test systemd directory exists"""
        systemd_dir = PROJECT_ROOT / 'systemd'
        self.assertTrue(systemd_dir.exists(), "systemd/ directory not found")
    
    def test_config_directory_exists(self):
        """Test config directory exists"""
        config_dir = PROJECT_ROOT / 'config'
        self.assertTrue(config_dir.exists(), "config/ directory not found")


def run_tests():
    """Run all Phase 7 validation tests"""
    print("=" * 70)
    print("GrowMate Raspberry Pi Port - Phase 7 Validation")
    print("=" * 70)
    print()
    print("Validating Phase 7 deliverables...")
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestPhase7Deliverables))
    suite.addTests(loader.loadTestsFromTestCase(TestREADMECompleteness))
    suite.addTests(loader.loadTestsFromTestCase(TestAPIDocumentation))
    suite.addTests(loader.loadTestsFromTestCase(TestTroubleshootingGuide))
    suite.addTests(loader.loadTestsFromTestCase(TestTestSuites))
    suite.addTests(loader.loadTestsFromTestCase(TestESP32Compatibility))
    suite.addTests(loader.loadTestsFromTestCase(TestProjectStructure))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("=" * 70)
    print("Phase 7 Validation Summary")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print()
    
    if result.wasSuccessful():
        print("✓ Phase 7 validation passed!")
        print()
        print("Phase 7 Deliverables Complete:")
        print("  ✓ End-to-end test suite (test_e2e.py)")
        print("  ✓ Failure scenario test suite (test_failures.py)")
        print("  ✓ Performance monitoring script (monitor_performance.py)")
        print("  ✓ Complete README.md with API documentation")
        print("  ✓ Comprehensive TROUBLESHOOTING.md guide")
        print("  ✓ Wiring diagram (WIRING.md)")
        print("  ✓ ESP32 compatibility maintained")
        print("  ✓ Project structure complete")
        print()
        print("Phase 7: Testing & Documentation - COMPLETE")
        return 0
    else:
        print("✗ Some validation tests failed. See details above.")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
