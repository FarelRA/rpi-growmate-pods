import logging
import os
import pytest
from utils import (
    clamp, map_range, get_device_id, get_env_device_id,
    get_env_api_key, get_ap_ssid, setup_logging,
    FIRMWARE_VERSION, FAILURE_THRESHOLD, SENSOR_INTERVAL_SECONDS,
)


class TestClamp:
    def test_within_range(self):
        assert clamp(50, 0, 100) == 50

    def test_below_min(self):
        assert clamp(-10, 0, 100) == 0

    def test_above_max(self):
        assert clamp(150, 0, 100) == 100

    def test_equal_to_min(self):
        assert clamp(0, 0, 100) == 0

    def test_equal_to_max(self):
        assert clamp(100, 0, 100) == 100

    def test_float_values(self):
        assert clamp(0.5, 0.0, 1.0) == 0.5

    def test_inverted_min_max(self):
        assert clamp(50, 100, 0) == 100


class TestMapRange:
    def test_normal_mapping(self):
        assert map_range(32768, 0, 65535) == pytest.approx(50.0, abs=0.1)

    def test_min_value(self):
        assert map_range(0, 0, 65535) == 0.0

    def test_max_value(self):
        assert map_range(65535, 0, 65535) == 100.0

    def test_inverted_input_range(self):
        result = map_range(0, 65535, 0)
        assert result == 100.0

    def test_custom_output_range(self):
        result = map_range(32768, 0, 65535, 0.0, 5.0)
        assert result == pytest.approx(2.5, abs=0.1)

    def test_clamps_below_zero(self):
        assert map_range(-100, 0, 65535) == 0.0

    def test_clamps_above_100(self):
        assert map_range(70000, 0, 65535) == 100.0


class TestGetDeviceId:
    def test_from_wlan_mac(self, mocker):
        mocker.patch("builtins.open", mocker.mock_open(read_data="b8:27:eb:12:34:56\n"))
        mocker.patch("pathlib.Path.exists", return_value=True)
        result = get_device_id()
        assert result == "growmate-b827eb123456"

    def test_from_eth0(self, mocker):
        def side_effect(path, *args, **kwargs):
            if "wlan0" in str(path):
                raise FileNotFoundError
            return mocker.mock_open(read_data="aa:bb:cc:dd:ee:ff\n")(path)
        mocker.patch("builtins.open", side_effect=side_effect)
        result = get_device_id()
        assert result == "growmate-aabbccddeeff"

    def test_fallback_to_hostname(self, mocker):
        mocker.patch("builtins.open", side_effect=FileNotFoundError)
        mocker.patch("socket.gethostname", return_value="raspberrypi")
        result = get_device_id()
        assert result == "growmate-raspberrypi"


class TestGetEnvDeviceId:
    def test_from_env_var(self):
        os.environ["DEVICE_ID"] = "custom-id"
        assert get_env_device_id() == "custom-id"
        del os.environ["DEVICE_ID"]

    def test_fallback(self, mocker):
        mocker.patch("utils.get_device_id", return_value="growmate-test")
        assert get_env_device_id() == "growmate-test"


class TestGetEnvApiKey:
    def test_from_env(self):
        os.environ["DEVICE_API_KEY"] = "secret-key"
        assert get_env_api_key() == "secret-key"
        del os.environ["DEVICE_API_KEY"]

    def test_empty_default(self):
        assert get_env_api_key() == ""


class TestGetApSsid:
    def test_generates_valid_ssid(self, mocker):
        mocker.patch("utils.get_device_id", return_value="growmate-b827eb123456")
        ssid = get_ap_ssid()
        assert ssid.startswith("GrowMate-")
        assert len(ssid) > 8
        assert ssid == "GrowMate-123456"


class TestConstants:
    def test_firmware_version(self):
        assert FIRMWARE_VERSION == "2.0.0"

    def test_failure_threshold(self):
        assert FAILURE_THRESHOLD == 5

    def test_sensor_interval(self):
        assert SENSOR_INTERVAL_SECONDS == 60


class TestSetupLogging:
    def test_returns_logger(self):
        logger = setup_logging("test-setup-logging-1")
        assert logger.name == "test-setup-logging-1"
        assert logger.level == logging.INFO
        assert len(logger.handlers) > 0

    def test_formatter_applied(self):
        logger = setup_logging("test-setup-logging-2")
        for handler in logger.handlers:
            assert handler.formatter is not None

    def test_default_logger_name(self):
        logger = setup_logging()
        assert logger.name == "growmate"
