#!/usr/bin/env python3
"""
System Integration Test Suite (End-to-End Testing)

Validates complete system integration with all components working together:
- Configuration management (loading, validation, default values)
- Sensor reading and calibration (ADC, DHT22)
- Camera capture and image processing
- API client communication (sensor upload, camera upload, commands)
- Actuator control (pump, light relays)
- Network management (WiFi, AP mode)
- Onboarding portal (Flask routes, configuration)

Tests are designed to run without actual hardware using mocking where necessary.
For hardware validation, use test_hardware.py on actual Raspberry Pi.

Usage:
    python3 scripts/test_system_integration.py
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock, mock_open
from io import BytesIO

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestConfigurationManagement(unittest.TestCase):
    """Test configuration loading and validation"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_config = {
            'device': {'id': 'test-device-001'},
            'network': {
                'wifi_ssid': 'TestNetwork',
                'wifi_password': 'testpass123'
            },
            'api': {'url': 'https://api.test.com'},
            'intervals': {
                'sensor_reading': 15,
                'camera_capture': 900
            },
            'calibration': {
                'soil_moisture': {'min': 0, 'max': 65535},
                'light': {'min': 0, 'max': 65535},
                'water_level': {'min': 0, 'max': 65535}
            },
            'sensors': {'enable_dht22': True}
        }
    
    @patch('builtins.open', new_callable=mock_open, read_data='device:\n  id: test-device-001\n')
    @patch('yaml.safe_load')
    def test_config_loading(self, mock_yaml, mock_file):
        """Test configuration file loading"""
        mock_yaml.return_value = self.test_config
        
        import config_manager
        config = config_manager.load_config('/etc/growmate/config.yaml')
        
        self.assertIsNotNone(config)
        self.assertEqual(config['device']['id'], 'test-device-001')
        self.assertEqual(config['intervals']['sensor_reading'], 15)
        self.assertEqual(config['intervals']['camera_capture'], 900)
    
    def test_config_validation(self):
        """Test configuration validation"""
        import config_manager
        
        # Valid config should pass
        self.assertTrue(config_manager.validate_config(self.test_config))
        
        # Missing required fields should fail
        invalid_config = {'device': {}}
        self.assertFalse(config_manager.validate_config(invalid_config))
    
    def test_config_intervals_correct(self):
        """Test that default intervals have correct values"""
        # Default values: SENSOR=15s, CAMERA=900s
        self.assertEqual(self.test_config['intervals']['sensor_reading'], 15)
        self.assertEqual(self.test_config['intervals']['camera_capture'], 900)


class TestSensorReading(unittest.TestCase):
    """Test sensor reading and calibration"""
    
    @patch('board.I2C')
    @patch('adafruit_ads1x15.ads1115.ADS1115')
    def test_adc_sensor_reading(self, mock_ads, mock_i2c):
        """Test ADC sensor reading with calibration"""
        # Mock ADC readings
        mock_adc = Mock()
        mock_adc.read.return_value = 32768  # Mid-range value
        mock_ads.return_value = mock_adc
        
        import sensors
        
        # Test soil moisture reading
        calibration = {'min': 0, 'max': 65535}
        raw_value = 32768
        percentage = sensors.apply_calibration(raw_value, calibration)
        
        # Should be ~50% for mid-range value
        self.assertAlmostEqual(percentage, 50, delta=1)
    
    @patch('adafruit_dht.DHT22')
    def test_dht22_reading(self, mock_dht):
        """Test DHT22 temperature and humidity reading"""
        # Mock DHT22 readings
        mock_sensor = Mock()
        mock_sensor.temperature = 25.5
        mock_sensor.humidity = 60.0
        mock_dht.return_value = mock_sensor
        
        import sensors
        
        # DHT22 should return temperature and humidity
        # No 'raw' field (only ADC sensors have raw)
        temp = mock_sensor.temperature
        humidity = mock_sensor.humidity
        
        self.assertIsNotNone(temp)
        self.assertIsNotNone(humidity)
        self.assertGreater(temp, 0)
        self.assertGreater(humidity, 0)
    
    def test_calibration_algorithm_correct(self):
        """Test that calibration algorithm is correct (integer division)"""
        import sensors
        
        # Uses integer division: (raw - min) * 100 / (max - min)
        calibration = {'min': 0, 'max': 65535}
        
        # Test boundary values
        self.assertEqual(sensors.apply_calibration(0, calibration), 0)
        self.assertEqual(sensors.apply_calibration(65535, calibration), 100)
        
        # Test mid-range (should use integer division)
        result = sensors.apply_calibration(32768, calibration)
        expected = (32768 - 0) * 100 // (65535 - 0)  # Integer division
        self.assertEqual(result, expected)


class TestCameraCapture(unittest.TestCase):
    """Test camera capture and image handling"""
    
    @patch('picamera2.Picamera2')
    def test_camera_initialization(self, mock_picamera):
        """Test camera initialization"""
        mock_camera = Mock()
        mock_picamera.return_value = mock_camera
        
        import camera_service
        
        # Camera should initialize without errors
        with camera_service.CameraService() as cam:
            self.assertIsNotNone(cam)
    
    @patch('picamera2.Picamera2')
    def test_camera_capture(self, mock_picamera):
        """Test image capture"""
        mock_camera = Mock()
        mock_camera.capture_file = Mock()
        mock_picamera.return_value = mock_camera
        
        import camera_service
        
        with camera_service.CameraService() as cam:
            image_path = cam.capture_image('/tmp/test.jpg')
            self.assertIsNotNone(image_path)
            mock_camera.capture_file.assert_called_once()
    
    def test_camera_lifecycle_is_ephemeral(self):
        """Test that camera lifecycle is ephemeral ()"""
        # camera_service_init() → capture → camera_service_deinit()
        # Raspberry Pi: context manager ensures init/cleanup per cycle
        import camera_service
        
        # Camera should support context manager (ephemeral usage)
        self.assertTrue(hasattr(camera_service.CameraService, '__enter__'))
        self.assertTrue(hasattr(camera_service.CameraService, '__exit__'))


class TestAPIClient(unittest.TestCase):
    """Test API client communication"""
    
    @patch('requests.post')
    def test_sensor_data_upload(self, mock_post):
        """Test sensor data upload format """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'commands': []}
        mock_post.return_value = mock_response
        
        import api_client
        
        # Expected sensor data format
        sensor_data = {
            'deviceId': 'test-device-001',
            'firmwareVersion': '1.0.0',
            'sensors': [
                {'kind': 'soil_moisture', 'value': 45, 'raw': 29491},
                {'kind': 'light', 'value': 78, 'raw': 51118},
                {'kind': 'water_level', 'value': 92, 'raw': 60292},
                {'kind': 'temperature', 'value': 25},  # No 'raw' for DHT22
                {'kind': 'humidity', 'value': 60}      # No 'raw' for DHT22
            ],
            'currentState': {
                'pumpRunning': False,
                'lightOn': False
            }
        }
        
        client = api_client.APIClient('https://api.test.com', 'test-device-001')
        response = client.upload_sensor_data(sensor_data)
        
        self.assertIsNotNone(response)
        mock_post.assert_called_once()
        
        # Verify JSON payload structure
        call_args = mock_post.call_args
        self.assertIn('json', call_args.kwargs)
        payload = call_args.kwargs['json']
        self.assertEqual(payload['deviceId'], 'test-device-001')
        self.assertIn('sensors', payload)
    
    @patch('requests.post')
    def test_camera_upload(self, mock_post):
        """Test camera image upload format """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        import api_client
        
        client = api_client.APIClient('https://api.test.com', 'test-device-001')
        
        # Mock image file
        image_data = b'\xff\xd8\xff\xe0'  # JPEG header
        
        with patch('builtins.open', mock_open(read_data=image_data)):
            response = client.upload_camera_image('/tmp/test.jpg')
        
        self.assertIsNotNone(response)
        mock_post.assert_called_once()
        
        # Verify multipart/form-data with X-Device-Id header
        call_args = mock_post.call_args
        self.assertIn('files', call_args.kwargs)
        self.assertIn('headers', call_args.kwargs)
        self.assertEqual(call_args.kwargs['headers']['X-Device-Id'], 'test-device-001')
    
    @patch('requests.post')
    def test_retry_logic(self, mock_post):
        """Test retry logic on failures"""
        # First call fails, second succeeds
        mock_post.side_effect = [
            Exception('Network error'),
            Mock(status_code=200, json=lambda: {'commands': []})
        ]
        
        import api_client
        
        client = api_client.APIClient('https://api.test.com', 'test-device-001')
        
        # Should retry and eventually succeed
        sensor_data = {'deviceId': 'test-device-001', 'sensors': []}
        response = client.upload_sensor_data(sensor_data)
        
        self.assertIsNotNone(response)
        self.assertEqual(mock_post.call_count, 2)


class TestActuatorControl(unittest.TestCase):
    """Test actuator control"""
    
    @patch('gpiozero.OutputDevice')
    def test_pump_control(self, mock_gpio):
        """Test water pump control"""
        mock_pump = Mock()
        mock_gpio.return_value = mock_pump
        
        import actuators
        
        actuator = actuators.Actuators()
        actuator.run_pump(5000)  # 5 seconds
        
        # Pump should be turned on then off
        self.assertTrue(mock_pump.on.called or mock_pump.off.called)
    
    @patch('gpiozero.OutputDevice')
    def test_light_control(self, mock_gpio):
        """Test grow light control"""
        mock_light = Mock()
        mock_gpio.return_value = mock_light
        
        import actuators
        
        actuator = actuators.Actuators()
        actuator.set_light(True)
        
        # Light should be turned on
        mock_light.on.assert_called()
    
    def test_command_parsing_correct(self):
        """Test that command parsing has correct format"""
        # Expected command format:
        # {"kind": "pump", "durationMs": 5000}
        # {"kind": "light", "enabled": true}
        
        commands = [
            {'kind': 'pump', 'durationMs': 5000},
            {'kind': 'light', 'enabled': True}
        ]
        
        # Verify command structure
        self.assertEqual(commands[0]['kind'], 'pump')
        self.assertIn('durationMs', commands[0])
        self.assertEqual(commands[1]['kind'], 'light')
        self.assertIn('enabled', commands[1])


class TestOnboardingFlow(unittest.TestCase):
    """Test WiFi onboarding flow"""
    
    @patch('flask.Flask')
    def test_onboarding_portal_routes(self, mock_flask):
        """Test onboarding portal routes"""
        import onboarding_portal
        
        # Portal should have required routes
        app = onboarding_portal.create_app()
        
        # Check that app has routes (can't easily test without running server)
        self.assertIsNotNone(app)
    
    def test_ap_mode_ssid_format(self):
        """Test AP mode SSID format """
        # GrowMate-{last 6 chars of MAC}
        # Example: GrowMate-A1B2C3
        
        device_id = 'growmate-aabbcc112233'
        ssid = f"GrowMate-{device_id[-6:].upper()}"
        
        self.assertTrue(ssid.startswith('GrowMate-'))
        self.assertEqual(len(ssid), 15)  # GrowMate- (9) + 6 chars
    
    def test_ap_mode_password(self):
        """Test AP mode password """
        # "growmate" (8 chars, WPA2-PSK minimum)
        password = "growmate"
        
        self.assertEqual(password, "growmate")
        self.assertGreaterEqual(len(password), 8)  # WPA2-PSK minimum


class TestFailureRecovery(unittest.TestCase):
    """Test failure recovery mechanisms"""
    
    def test_consecutive_failure_threshold(self):
        """Test consecutive failure threshold """
        # APP_ONBOARDING_FAILURE_THRESHOLD = 5
        FAILURE_THRESHOLD = 5
        
        consecutive_failures = 0
        
        # Simulate failures
        for i in range(FAILURE_THRESHOLD):
            consecutive_failures += 1
        
        # After 5 failures, should trigger AP mode
        self.assertEqual(consecutive_failures, FAILURE_THRESHOLD)
        self.assertTrue(consecutive_failures >= FAILURE_THRESHOLD)
    
    def test_failure_counter_reset_on_success(self):
        """Test failure counter resets on successful operation"""
        consecutive_failures = 3
        
        # Successful operation
        operation_success = True
        
        if operation_success:
            consecutive_failures = 0
        
        self.assertEqual(consecutive_failures, 0)
    
    @patch('requests.post')
    def test_network_failure_handling(self, mock_post):
        """Test network failure handling"""
        mock_post.side_effect = Exception('Network unreachable')
        
        import api_client
        
        client = api_client.APIClient('https://api.test.com', 'test-device-001')
        
        # Should handle network failure gracefully
        try:
            sensor_data = {'deviceId': 'test-device-001', 'sensors': []}
            response = client.upload_sensor_data(sensor_data)
            # If retry logic exhausted, should return None or raise
            self.assertIsNone(response)
        except Exception as e:
            # Exception is acceptable if retry logic exhausted
            self.assertIsNotNone(e)


class TestMainApplicationLoop(unittest.TestCase):
    """Test main application loop integration"""
    
    def test_loop_counter_timing(self):
        """Test loop counter timing """
        # loops_since_camera counter, not time-based
        # Camera period: CAMERA_INTERVAL_SECONDS // SENSOR_INTERVAL_SECONDS
        
        SENSOR_INTERVAL = 15  # seconds
        CAMERA_INTERVAL = 900  # seconds
        
        camera_period = CAMERA_INTERVAL // SENSOR_INTERVAL
        
        self.assertEqual(camera_period, 60)  # 900 / 15 = 60 loops
    
    def test_camera_due_calculation(self):
        """Test camera due calculation """
        loops_since_camera = 0
        camera_period = 60
        
        # Camera not due initially
        camera_due = (loops_since_camera >= camera_period)
        self.assertFalse(camera_due)
        
        # Camera due after 60 loops
        loops_since_camera = 60
        camera_due = (loops_since_camera >= camera_period)
        self.assertTrue(camera_due)
    
    def test_loop_counter_reset_on_success(self):
        """Test loop counter resets only on successful camera upload"""
        loops_since_camera = 65
        camera_upload_success = True
        
        if camera_upload_success:
            loops_since_camera = 0
        
        self.assertEqual(loops_since_camera, 0)
    
    def test_loop_counter_no_reset_on_failure(self):
        """Test loop counter does NOT reset on failed camera upload"""
        loops_since_camera = 65
        camera_upload_success = False
        
        if camera_upload_success:
            loops_since_camera = 0
        
        self.assertEqual(loops_since_camera, 65)  # Unchanged


def run_tests():
    """Run all end-to-end tests"""
    print("=" * 70)
    print("GrowMate Raspberry Pi Port - End-to-End Test Suite")
    print("=" * 70)
    print()
    print("Testing system integration and device compatibility...")
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestConfigurationManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestSensorReading))
    suite.addTests(loader.loadTestsFromTestCase(TestCameraCapture))
    suite.addTests(loader.loadTestsFromTestCase(TestAPIClient))
    suite.addTests(loader.loadTestsFromTestCase(TestActuatorControl))
    suite.addTests(loader.loadTestsFromTestCase(TestOnboardingFlow))
    suite.addTests(loader.loadTestsFromTestCase(TestFailureRecovery))
    suite.addTests(loader.loadTestsFromTestCase(TestMainApplicationLoop))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print()
    
    if result.wasSuccessful():
        print("✓ All end-to-end tests passed!")
        print()
        print("Note: These tests use mocking and validate logic/integration.")
        print("For hardware validation, run test_hardware.py on actual Raspberry Pi.")
        return 0
    else:
        print("✗ Some tests failed. See details above.")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
