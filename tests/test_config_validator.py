import pytest
from pydantic import ValidationError
from config_validator import (
    validate_config, is_reloadable_change, get_config_changes,
    RELOADABLE_SETTINGS, NON_RELOADABLE_SETTINGS,
)


class TestDeviceConfig:
    def test_valid_id(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.device.id == "growmate-test"

    def test_invalid_id_characters(self, minimal_config):
        minimal_config["device"]["id"] = "bad id!"
        with pytest.raises(ValidationError, match="invalid characters"):
            validate_config(minimal_config)

    def test_empty_id(self, minimal_config):
        minimal_config["device"]["id"] = ""
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestAPIConfig:
    def test_valid_api(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.api.sensor_url == "https://test.growmate.bond/api/v2/sensors"

    def test_empty_sensor_url(self, minimal_config):
        minimal_config["api"]["sensor_url"] = ""
        with pytest.raises(ValidationError):
            validate_config(minimal_config)

    def test_timeout_out_of_range(self, minimal_config):
        minimal_config["api"]["timeout_sensor"] = 200
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestNetworkConfig:
    def test_defaults(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.network.wifi.connect_timeout == 12
        assert validated.network.wifi.connect_retries == 4

    def test_connect_timeout_bound(self, minimal_config):
        minimal_config["network"]["wifi"]["connect_timeout"] = 0
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestAPModeConfig:
    def test_defaults(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.ap_mode.password == "growmate"
        assert validated.ap_mode.channel == 1

    def test_channel_bound(self, minimal_config):
        minimal_config["ap_mode"]["channel"] = 15
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestIntervalsConfig:
    def test_defaults(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.intervals.sensor_reading == 60

    def test_sensor_reading_out_of_range(self, minimal_config):
        minimal_config["intervals"]["sensor_reading"] = 5
        with pytest.raises(ValidationError):
            validate_config(minimal_config)

    def test_sensor_reading_max(self, minimal_config):
        minimal_config["intervals"]["sensor_reading"] = 300
        validated = validate_config(minimal_config)
        assert validated.intervals.sensor_reading == 300


class TestRetryConfig:
    def test_defaults(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.retry.max_attempts == 6

    def test_max_delay_gte_initial(self, minimal_config):
        minimal_config["retry"]["initial_delay"] = 10.0
        minimal_config["retry"]["max_delay"] = 5.0
        with pytest.raises(ValidationError, match="must be >= initial_delay"):
            validate_config(minimal_config)

    def test_jitter_bound(self, minimal_config):
        minimal_config["retry"]["jitter"] = 0.6
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestSensorsConfig:
    def test_valid(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.sensors.enable_dht22 is True
        assert validated.sensors.dht22_pin == 4

    def test_dht22_pin_out_of_range(self, minimal_config):
        minimal_config["sensors"]["dht22_pin"] = 1
        with pytest.raises(ValidationError):
            validate_config(minimal_config)

    def test_adc_gain_bound(self, minimal_config):
        minimal_config["sensors"]["adc"]["gain"] = 0
        with pytest.raises(ValidationError):
            validate_config(minimal_config)

    def test_i2c_address_valid(self, minimal_config):
        minimal_config["sensors"]["adc"]["i2c_address"] = 0x4B
        validated = validate_config(minimal_config)
        assert validated.sensors.adc.i2c_address == 0x4B

    def test_limit_switches_pull_up_down_valid(self, minimal_config):
        minimal_config["sensors"]["limit_switches"]["pull_up_down"] = "PUD_DOWN"
        validated = validate_config(minimal_config)
        assert validated.sensors.limit_switches.pull_up_down == "PUD_DOWN"

    def test_limit_switches_pull_up_down_invalid(self, minimal_config):
        minimal_config["sensors"]["limit_switches"]["pull_up_down"] = "INVALID"
        with pytest.raises(ValidationError, match="Invalid pull_up_down"):
            validate_config(minimal_config)


class TestActuatorConfig:
    def test_defaults(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.actuators.pins.pump == 10
        assert validated.actuators.active_high is True

    def test_pin_out_of_range(self, minimal_config):
        minimal_config["actuators"]["pins"]["pump"] = 1
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestCameraConfig:
    def test_defaults(self, minimal_config):
        validated = validate_config(minimal_config)
        assert validated.camera.width == 640
        assert validated.camera.framerate == 15

    def test_port_out_of_range(self, minimal_config):
        minimal_config["camera"]["port"] = 80
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestLoggingConfig:
    def test_invalid_level(self, minimal_config):
        minimal_config["logging"]["level"] = "TRACE"
        with pytest.raises(ValidationError, match="Invalid log level"):
            validate_config(minimal_config)

    def test_invalid_format(self, minimal_config):
        minimal_config["logging"]["format"] = "xml"
        with pytest.raises(ValidationError, match="Invalid log format"):
            validate_config(minimal_config)

    def test_valid_levels(self, minimal_config):
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            minimal_config["logging"]["level"] = level
            validated = validate_config(minimal_config)
            assert validated.logging.level == level

    def test_backup_count_bound(self, minimal_config):
        minimal_config["logging"]["backup_count"] = 200
        with pytest.raises(ValidationError):
            validate_config(minimal_config)


class TestValidateConfig:
    def test_valid_full_config(self, default_config):
        validated = validate_config(default_config)
        assert validated.version == 9
        assert validated.device.id == "growmate-test-device"

    def test_extra_keys_forbidden(self, minimal_config):
        minimal_config["extra_field"] = "not allowed"
        with pytest.raises(ValidationError, match="extra"):
            validate_config(minimal_config)

    def test_missing_version(self, minimal_config):
        del minimal_config["version"]
        with pytest.raises(ValidationError):
            validate_config(minimal_config)

    def test_missing_required_section(self, minimal_config):
        del minimal_config["device"]
        with pytest.raises(ValidationError):
            validate_config(minimal_config)

    def test_optional_sections_omitted(self, minimal_config):
        del minimal_config["camera"]
        del minimal_config["ap_mode"]
        validated = validate_config(minimal_config)
        assert validated.camera is None
        assert validated.ap_mode is None


class TestIsReloadableChange:
    def test_reloadable_section(self):
        assert is_reloadable_change("intervals") is True

    def test_reloadable_nested_key(self):
        assert is_reloadable_change("intervals.sensor_reading") is True
        assert is_reloadable_change("retry.max_attempts") is True
        assert is_reloadable_change("features.offline_queue") is True

    def test_non_reloadable_section(self):
        assert is_reloadable_change("network") is False
        assert is_reloadable_change("sensors") is False
        assert is_reloadable_change("actuators") is False

    def test_non_reloadable_nested(self):
        assert is_reloadable_change("network.wifi_ssid") is False
        assert is_reloadable_change("sensors.dht22_pin") is False
        assert is_reloadable_change("actuators.pins.pump") is False

    def test_unknown_key(self):
        assert is_reloadable_change("nonexistent") is False


class TestGetConfigChanges:
    def test_no_changes(self):
        cfg = {"a": 1, "b": 2}
        assert get_config_changes(cfg, cfg) == {}

    def test_changed_value(self):
        old = {"a": 1}
        new = {"a": 2}
        assert get_config_changes(old, new) == {"a": (1, 2)}

    def test_added_key(self):
        old = {"a": 1}
        new = {"a": 1, "b": 2}
        assert get_config_changes(old, new) == {"b": (None, 2)}

    def test_removed_key(self):
        old = {"a": 1, "b": 2}
        new = {"a": 1}
        assert get_config_changes(old, new) == {"b": (2, None)}

    def test_nested_changed(self):
        old = {"sensors": {"dht22_pin": 4}}
        new = {"sensors": {"dht22_pin": 17}}
        assert get_config_changes(old, new) == {"sensors.dht22_pin": (4, 17)}

    def test_nested_added(self):
        old = {"sensors": {}}
        new = {"sensors": {"dht22_pin": 4}}
        assert get_config_changes(old, new) == {"sensors.dht22_pin": (None, 4)}

    def test_nested_removed(self):
        old = {"sensors": {"dht22_pin": 4}}
        new = {"sensors": {}}
        assert get_config_changes(old, new) == {"sensors.dht22_pin": (4, None)}

    def test_complex_nested(self):
        old = {"a": {"b": {"c": 1, "d": 2}}, "e": 3}
        new = {"a": {"b": {"c": 10, "d": 2}}, "e": 3}
        assert get_config_changes(old, new) == {"a.b.c": (1, 10)}


class TestReloadableSets:
    def test_reloadable_settings_defined(self):
        assert "intervals" in RELOADABLE_SETTINGS
        assert "retry" in RELOADABLE_SETTINGS
        assert "circuit_breaker" in RELOADABLE_SETTINGS
        assert "logging" in RELOADABLE_SETTINGS
        assert "features" in RELOADABLE_SETTINGS

    def test_non_reloadable_settings_defined(self):
        assert "version" in NON_RELOADABLE_SETTINGS
        assert "device.id" in NON_RELOADABLE_SETTINGS
        assert "network" in NON_RELOADABLE_SETTINGS
        assert "sensors" in NON_RELOADABLE_SETTINGS
        assert "actuators" in NON_RELOADABLE_SETTINGS
        assert "camera" in NON_RELOADABLE_SETTINGS
        assert "ap_mode" in NON_RELOADABLE_SETTINGS

    def test_no_overlap(self):
        for key in RELOADABLE_SETTINGS:
            assert key not in NON_RELOADABLE_SETTINGS
