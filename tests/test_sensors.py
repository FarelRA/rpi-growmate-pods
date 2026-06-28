import copy
import time
import pytest
import sensors
from sensors import SensorReader, read_sensors, async_read_sensors


class TestSensorReaderInit:
    def test_default_config(self):
        reader = SensorReader()
        assert reader.enable_dht22 is True
        assert reader._tank_gpio == 20
        assert reader._drawer_gpio == 21
        assert reader.adc_samples == 8
        assert reader.adc_sample_delay == 0.01
        assert reader.adc_max_value == 65535
        assert reader.dht_device is not None
        assert reader.acs712_channel is not None
        assert reader.light_channel is not None
        assert reader.water_channel is not None
        assert reader.soil_channel is not None

    def test_minimal_config(self, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        reader = SensorReader(cfg["sensors"])
        assert reader.enable_dht22 is True
        assert reader._tank_gpio == 20

    def test_custom_config(self, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        scfg = cfg["sensors"]
        scfg["enable_dht22"] = False
        scfg["dht22_pin"] = 17
        scfg["limit_switches"]["tank_gpio"] = 22
        scfg["adc"]["samples"] = 4
        reader = SensorReader(scfg)
        assert reader.enable_dht22 is False
        assert reader.dht_device is None
        assert reader._tank_gpio == 22
        assert reader.adc_samples == 4

    def test_dht22_disabled(self):
        reader = SensorReader({"enable_dht22": False})
        assert reader.enable_dht22 is False
        assert reader.dht_device is None

    def test_adc_init_failure(self, mocker):
        mocker.patch("sensors.busio.I2C", side_effect=Exception("I2C init fail"))
        with pytest.raises(Exception, match="I2C init fail"):
            SensorReader()

    def test_gpio_init_failure(self, mocker):
        mocker.patch("RPi.GPIO.setup", side_effect=Exception("GPIO setup fail"))
        reader = SensorReader()
        assert reader._tank_gpio == 20
        assert reader._drawer_gpio == 21


class TestSensorReaderAdc:
    def test_read_adc_averaged(self, mock_sleep):
        reader = SensorReader()
        result = reader.read_adc_averaged(reader.soil_channel)
        assert result == 32768

    def test_read_adc_averaged_exception(self, mock_sleep, mocker):
        reader = SensorReader()
        class _FailingChannel:
            @property
            def value(self):
                raise Exception("ADC err")
        reader.soil_channel = _FailingChannel()
        result = reader.read_adc_averaged(reader.soil_channel)
        assert result is None


class TestSensorReaderCalibration:
    def test_calibrate_soil_zero(self):
        reader = SensorReader()
        assert reader.calibrate_soil(0) == 100

    def test_calibrate_soil_max(self):
        reader = SensorReader()
        assert reader.calibrate_soil(65535) == 0

    def test_calibrate_soil_midpoint(self):
        reader = SensorReader()
        assert reader.calibrate_soil(32768) == 49

    def test_calibrate_water_zero(self):
        reader = SensorReader()
        assert reader.calibrate_water(0) == 0

    def test_calibrate_water_max(self):
        reader = SensorReader()
        assert reader.calibrate_water(65535) == 100

    def test_calibrate_water_midpoint(self):
        reader = SensorReader()
        assert reader.calibrate_water(32768) == 50

    def test_calibrate_light_zero(self):
        reader = SensorReader()
        assert reader.calibrate_light(0) == 0

    def test_calibrate_light_max(self):
        reader = SensorReader()
        assert reader.calibrate_light(65535) == 100

    def test_calibrate_light_midpoint(self):
        reader = SensorReader()
        assert reader.calibrate_light(32768) == 50


class TestSensorReaderBattery:
    def test_read_battery_current_normal(self, mock_sleep):
        reader = SensorReader()
        result = reader.read_battery_current()
        assert result is not None
        assert isinstance(result, int)

    def test_read_battery_current_raw_none(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", return_value=None)
        result = reader.read_battery_current()
        assert result is None

    def test_read_battery_current_exception(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", side_effect=Exception("unexpected"))
        result = reader.read_battery_current()
        assert result is None


class TestSensorReaderAnalogSensors:
    def test_read_soil_moisture_normal(self, mock_sleep):
        reader = SensorReader()
        result = reader.read_soil_moisture()
        assert result["kind"] == "soil"
        assert result["unit"] == "%"
        assert result["raw"] == 32768

    def test_read_soil_moisture_raw_none(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", return_value=None)
        result = reader.read_soil_moisture()
        assert result is None

    def test_read_soil_moisture_exception(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", side_effect=Exception("err"))
        result = reader.read_soil_moisture()
        assert result is None

    def test_read_light_level_normal(self, mock_sleep):
        reader = SensorReader()
        result = reader.read_light_level()
        assert result == {"kind": "light", "value": 50, "unit": "%", "raw": 32768}

    def test_read_light_level_raw_none(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", return_value=None)
        result = reader.read_light_level()
        assert result is None

    def test_read_light_level_exception(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", side_effect=Exception("err"))
        result = reader.read_light_level()
        assert result is None

    def test_read_water_level_normal(self, mock_sleep):
        reader = SensorReader()
        result = reader.read_water_level()
        assert result == {"kind": "water", "value": 50, "unit": "%", "raw": 32768}

    def test_read_water_level_raw_none(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", return_value=None)
        result = reader.read_water_level()
        assert result is None

    def test_read_water_level_exception(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_adc_averaged", side_effect=Exception("err"))
        result = reader.read_water_level()
        assert result is None


class TestSensorReaderDht22:
    def test_read_dht22_success(self, mock_sleep):
        reader = SensorReader()
        temp, hum = reader.read_dht22()
        assert temp == {"kind": "temperature", "value": 25.0, "unit": "C"}
        assert hum == {"kind": "air", "value": 60.0, "unit": "%"}

    def test_read_dht22_retry_once_success(self, mock_sleep, mocker):
        reader = SensorReader()
        class _RetryDHT:
            def __init__(self):
                self._count = 0
            @property
            def temperature(self):
                self._count += 1
                if self._count <= 1:
                    raise RuntimeError("bad read")
                return 25.0
            @property
            def humidity(self):
                return 60.0
        reader.dht_device = _RetryDHT()
        temp, hum = reader.read_dht22()
        assert temp == {"kind": "temperature", "value": 25.0, "unit": "C"}
        assert hum == {"kind": "air", "value": 60.0, "unit": "%"}

    def test_read_dht22_retry_fail(self, mock_sleep, mocker):
        reader = SensorReader()
        class _FailDHT:
            @property
            def temperature(self):
                raise RuntimeError("bad read")
            @property
            def humidity(self):
                raise RuntimeError("bad read")
        reader.dht_device = _FailDHT()
        temp, hum = reader.read_dht22()
        assert temp is None
        assert hum is None

    def test_read_dht22_disabled(self):
        reader = SensorReader({"enable_dht22": False})
        temp, hum = reader.read_dht22()
        assert temp is None
        assert hum is None


class TestSensorReaderLimitSwitches:
    def test_read_limit_switches_normal(self):
        reader = SensorReader()
        result = reader.read_limit_switches()
        assert result == {"tankSwitchOpen": True, "drawerSwitchOpen": True}

    def test_read_limit_switches_exception(self, mocker):
        reader = SensorReader()
        mocker.patch("RPi.GPIO.input", side_effect=Exception("GPIO err"))
        result = reader.read_limit_switches()
        assert result == {"tankSwitchOpen": None, "drawerSwitchOpen": None}

    def test_read_limit_switches_debounced_majority(self, mock_sleep):
        reader = SensorReader()
        result = reader.read_limit_switches_debounced()
        assert result == {"tankSwitchOpen": True, "drawerSwitchOpen": True}

    def test_read_limit_switches_debounced_empty(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch("RPi.GPIO.input", side_effect=Exception("GPIO err"))
        result = reader.read_limit_switches_debounced()
        assert result == {"tankSwitchOpen": None, "drawerSwitchOpen": None}


class TestSensorReaderHealth:
    def test_update_health_failure_counting(self):
        reader = SensorReader()
        reader._update_health("soil", False)
        assert reader._health["soil"]["consecutive_failures"] == 1
        assert reader._health["soil"]["degraded"] is False

    def test_update_health_degraded_at_threshold(self):
        reader = SensorReader()
        for _ in range(3):
            reader._update_health("soil", False)
        assert reader._health["soil"]["consecutive_failures"] == 3
        assert reader._health["soil"]["degraded"] is True

    def test_update_health_success_resets(self):
        reader = SensorReader()
        reader._update_health("soil", False)
        reader._update_health("soil", False)
        assert reader._health["soil"]["consecutive_failures"] == 2
        reader._update_health("soil", True)
        assert reader._health["soil"]["consecutive_failures"] == 0
        assert reader._health["soil"]["degraded"] is False

    def test_get_health(self):
        reader = SensorReader()
        health = reader.get_health()
        assert "soil" in health
        assert "light" in health
        assert "water" in health
        assert "temperature" in health
        assert "air" in health
        assert "battery" in health
        assert health["soil"]["consecutive_failures"] == 0


class TestSensorReaderCoulombCounter:
    def test_get_coulomb_count_default(self):
        reader = SensorReader()
        assert reader.get_coulomb_count() == 0.0

    def test_reset_coulomb_count(self):
        reader = SensorReader()
        reader._coulomb_counter_mah = 42.5
        reader.reset_coulomb_count()
        assert reader.get_coulomb_count() == 0.0


class TestSensorReaderCurrentState:
    def test_get_current_state_with_actuator_states(self, mock_sleep):
        reader = SensorReader()
        act = {"pumpEnabled": True, "fertilizerEnabled": False, "pesticideEnabled": True}
        state = reader.get_current_state(act)
        assert state["pumpEnabled"] is True
        assert state["fertilizerEnabled"] is False
        assert state["pesticideEnabled"] is True
        assert state["lightEnabled"] is False
        assert "tankSwitchOpen" in state
        assert "drawerSwitchOpen" in state
        assert "batteryCurrent" in state

    def test_get_current_state_without_actuator_states(self, mock_sleep):
        reader = SensorReader()
        state = reader.get_current_state()
        assert state["pumpEnabled"] is False
        assert state["fertilizerEnabled"] is False
        assert state["pesticideEnabled"] is False

    def test_get_current_state_tracks_coulomb(self, mock_sleep):
        reader = SensorReader()
        assert reader.get_coulomb_count() == 0.0
        reader.get_current_state()
        assert reader.get_coulomb_count() != 0.0


class TestSensorReaderReadAllSensors:
    def test_read_all_sensors_dht22_enabled(self, mock_sleep):
        reader = SensorReader()
        result = reader.read_all_sensors()
        kinds = [s["kind"] for s in result]
        assert "soil" in kinds
        assert "light" in kinds
        assert "water" in kinds
        assert "temperature" in kinds
        assert len(result) == 5

    def test_read_all_sensors_dht22_disabled(self, mock_sleep):
        reader = SensorReader({"enable_dht22": False})
        result = reader.read_all_sensors()
        kinds = [s["kind"] for s in result]
        assert "soil" in kinds
        assert "light" in kinds
        assert "water" in kinds
        assert "temperature" not in kinds
        assert "air" not in kinds
        assert len(result) == 3

    def test_read_all_sensors_partial_failures(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_soil_moisture", return_value=None)
        mocker.patch.object(reader, "read_light_level", return_value=None)
        mocker.patch.object(reader, "read_dht22", return_value=(None, None))
        result = reader.read_all_sensors()
        for s in result:
            if s["kind"] in ("soil", "light"):
                assert s["value"] is None
                assert s.get("error") is True
        assert result[0]["kind"] == "soil"
        assert result[0]["error"] is True
        assert result[1]["kind"] == "light"
        assert result[1]["error"] is True


class TestSensorReaderCleanup:
    def test_cleanup(self, mocker):
        reader = SensorReader()
        mock_exit = mocker.patch.object(reader.dht_device, "exit")
        reader.cleanup()
        mock_exit.assert_called_once()

    def test_cleanup_dht22_not_initialized(self, mocker):
        reader = SensorReader({"enable_dht22": False})
        mock_cleanup = mocker.patch("RPi.GPIO.cleanup")
        reader.cleanup()
        mock_cleanup.assert_called_once()


class TestSensorReaderAsync:
    @pytest.mark.asyncio
    async def test_async_read_all_sensors(self, mock_sleep):
        reader = SensorReader()
        result = await reader.async_read_all_sensors()
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_async_get_current_state(self, mock_sleep):
        reader = SensorReader()
        result = await reader.async_get_current_state({"pumpEnabled": True})
        assert result["pumpEnabled"] is True


class TestNestedGet:
    def test_key_present(self):
        from sensors import _nested_get
        assert _nested_get({"a": {"b": 1}}, ["a", "b"]) == 1

    def test_key_missing(self):
        from sensors import _nested_get
        assert _nested_get({"a": {}}, ["a", "b"]) is None

    def test_non_dict_intermediate(self):
        from sensors import _nested_get
        assert _nested_get({"a": 1}, ["a", "b"]) is None

    def test_none_intermediate(self):
        from sensors import _nested_get
        assert _nested_get({"a": None}, ["a", "b"]) is None


class TestSensorReaderDht22Init:
    def test_dht22_init_failure(self, mocker):
        mocker.patch("adafruit_dht.DHT22", side_effect=Exception("DHT init fail"))
        reader = SensorReader()
        assert reader.dht_device is None


class TestSensorReaderDht22UnexpectedError:
    def test_read_dht22_non_runtime_error(self, mock_sleep):
        reader = SensorReader()
        class _FailingDHT:
            @property
            def temperature(self):
                raise ValueError("unexpected")
        reader.dht_device = _FailingDHT()
        temp, hum = reader.read_dht22()
        assert temp is None
        assert hum is None


class TestSensorReaderReadAllSensorsWaterFailure:
    def test_read_all_sensors_water_failure(self, mock_sleep, mocker):
        reader = SensorReader()
        mocker.patch.object(reader, "read_water_level", return_value=None)
        result = reader.read_all_sensors()
        water_entries = [s for s in result if s["kind"] == "water"]
        assert len(water_entries) == 1
        assert water_entries[0]["error"] is True


class TestSensorReaderCleanupExceptions:
    def test_cleanup_dht22_exit_exception(self, mocker):
        reader = SensorReader()
        mocker.patch.object(reader.dht_device, "exit", side_effect=Exception("exit fail"))
        reader.cleanup()

    def test_cleanup_gpio_exception(self, mocker):
        reader = SensorReader()
        mocker.patch("RPi.GPIO.cleanup", side_effect=Exception("gpio fail"))
        reader.cleanup()


class TestSensorReaderStandalone:
    def test_read_sensors(self, mock_sleep, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["sensors"]["enable_dht22"] = False
        result = read_sensors(cfg)
        assert len(result) == 3
        assert all(s["kind"] in ("soil", "light", "water") for s in result)

    @pytest.mark.asyncio
    async def test_async_read_sensors(self, mock_sleep, minimal_config):
        cfg = copy.deepcopy(minimal_config)
        cfg["sensors"]["enable_dht22"] = False
        result = await async_read_sensors(cfg)
        assert len(result) == 3
        assert all(s["kind"] in ("soil", "light", "water") for s in result)
