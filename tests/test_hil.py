"""Hardware-in-the-Loop (HIL) testing framework for GrowMate Pods."""

import copy
import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest


class _HILAnalogIn:
    sim = None

    def __init__(self, ads, channel_pin):
        self._pin = channel_pin

    @property
    def value(self):
        if self.sim._adc_fail.get(self._pin, False):
            raise Exception("ADC read error")
        return self.sim._adc.get(self._pin, self.sim._adc_default)


class _HILOutputDevice:
    sim = None

    def __init__(self, pin, active_high=True, initial_value=False):
        self._pin = pin
        self._active_high = active_high
        self._state = initial_value
        self.sim._relays[pin] = initial_value

    @property
    def is_active(self):
        return self._state if self._active_high else not self._state

    def on(self):
        self._state = True
        self.sim._on_relay_change(self._pin, True)

    def off(self):
        self._state = False
        self.sim._on_relay_change(self._pin, False)

    def close(self):
        pass


class _HILDHT22:
    sim = None

    def __init__(self, gpio):
        pass

    @property
    def temperature(self):
        if self.sim._dht22_fail_mode == "runtime":
            raise RuntimeError("DHT22 read failure")
        if self.sim._dht22_fail_mode == "exception":
            raise Exception("DHT22 unexpected error")
        return self.sim._dht22_temp

    @property
    def humidity(self):
        if self.sim._dht22_fail_mode == "runtime":
            raise RuntimeError("DHT22 read failure")
        if self.sim._dht22_fail_mode == "exception":
            raise Exception("DHT22 unexpected error")
        return self.sim._dht22_hum

    def exit(self):
        pass


class HardwareSimulator:
    def __init__(self):
        self.GPIO_HIGH = 1
        self.GPIO_LOW = 0
        self._adc_default = 32768
        self._adc = {}
        self._adc_fail = {}
        self._dht22_temp = 25.0
        self._dht22_hum = 60.0
        self._dht22_fail_mode = None
        self._limit_switches = {}
        self._relays = {}
        self._relay_history = []
        self._gpio_input_sequences = {}
        self._gpio_input_counters = {}
        self._batt_midpoint = 2.5
        self._batt_sensitivity = 0.185
        self._adc_max_value = 65535

    def install_mocks(self, mocker):
        _HILAnalogIn.sim = self
        _HILOutputDevice.sim = self
        _HILDHT22.sim = self
        mocker.patch("sensors.AnalogIn", _HILAnalogIn)
        mocker.patch("actuators.OutputDevice", _HILOutputDevice)
        mocker.patch("sensors.adafruit_dht.DHT22", _HILDHT22)
        mocker.patch("sensors.GPIO.input", side_effect=self._gpio_input)
        mocker.patch("sensors.GPIO.output", side_effect=self._gpio_output)

    def set_adc_channel(self, channel, raw_value):
        self._adc[channel] = raw_value

    def set_adc_fail(self, channel, fail=True):
        self._adc_fail[channel] = fail

    def set_dht22(self, temp, humidity):
        self._dht22_temp = temp
        self._dht22_hum = humidity

    def set_dht22_fail(self, mode="runtime"):
        self._dht22_fail_mode = mode

    def set_dht22_ok(self):
        self._dht22_fail_mode = None

    def set_limit_switch(self, gpio, state):
        self._limit_switches[gpio] = state

    def set_gpio_input_sequence(self, gpio, values):
        self._gpio_input_sequences[gpio] = list(values)
        self._gpio_input_counters[gpio] = 0

    def set_battery_current(self, current_ma):
        current_A = current_ma / 1000.0
        voltage = current_A * self._batt_sensitivity + self._batt_midpoint
        raw = int(voltage / 4.096 * self._adc_max_value)
        raw = max(0, min(self._adc_max_value, raw))
        self._adc[0] = raw
        return raw

    def get_relay_state(self, gpio):
        return self._relays.get(gpio, False)

    def get_relay_history(self):
        return list(self._relay_history)

    def reset_relay_history(self):
        self._relay_history = []

    def _on_relay_change(self, pin, state):
        self._relays[pin] = state
        self._relay_history.append({"pin": pin, "state": state, "time": 0})

    def _gpio_input(self, gpio):
        if gpio in self._gpio_input_sequences:
            seq = self._gpio_input_sequences[gpio]
            counter = self._gpio_input_counters.get(gpio, 0)
            if counter < len(seq):
                self._gpio_input_counters[gpio] = counter + 1
                return seq[counter]
            if seq:
                return seq[-1]
        return self._limit_switches.get(gpio, self.GPIO_HIGH)

    def _gpio_output(self, gpio, state):
        pass


@pytest.fixture
def hil(mocker):
    sim = HardwareSimulator()
    sim.install_mocks(mocker)
    return sim


def _make_app(config, hil):
    from main import GrowMateApp
    app = GrowMateApp()
    app.config = copy.deepcopy(config)
    from sensors import SensorReader
    from actuators import ActuatorController
    app.sensors = SensorReader(app.config["sensors"])
    app.actuators = ActuatorController(app.config["actuators"])
    app.api_client = MagicMock()
    app.api_client.device_id = app.config.get("device", {}).get("id", "growmate-test")
    app.api_client.upload_sensor_data = AsyncMock(return_value=[])
    app.network = None
    app.queue = None
    app.camera = None
    app.health_monitor = None
    app.consecutive_failures = 0
    return app


def _make_app_with_queue(config, hil):
    app = _make_app(config, hil)
    app.queue = MagicMock()
    app.queue.async_enqueue_sensor_data = AsyncMock(return_value=True)
    app.queue.async_get_queue_stats = AsyncMock(
        return_value={"sensor_queue": {"pending": 0, "total": 0}, "metadata": {}}
    )
    return app


def _run_sensor_cycle(app):
    asyncio.run(app.sensor_reading_job())


def _get_uploaded_sensors(app):
    if app.queue:
        app.queue.async_enqueue_sensor_data.assert_called_once()
        args, _ = app.queue.async_enqueue_sensor_data.call_args
        return args[2] if len(args) > 2 else []
    app.api_client.upload_sensor_data.assert_called_once()
    args, _ = app.api_client.upload_sensor_data.call_args
    return args[0] if args else []


def _get_uploaded_state(app):
    if app.queue:
        app.queue.async_enqueue_sensor_data.assert_called_once()
        args, _ = app.queue.async_enqueue_sensor_data.call_args
        return args[3] if len(args) > 3 else {}
    app.api_client.upload_sensor_data.assert_called_once()
    args, _ = app.api_client.upload_sensor_data.call_args
    return args[1] if len(args) > 1 else {}


def _assert_sensor_uploaded(app, kind, value):
    sensors = _get_uploaded_sensors(app)
    for s in sensors:
        if s.get("kind") == kind:
            assert s.get("value") == value, (
                f"sensor {kind}: expected {value}, got {s.get('value')}"
            )
            return
    raise AssertionError(f"sensor {kind} not found in uploaded data")


def _assert_relay_history(hil, pin, expected_states):
    history = hil.get_relay_history()
    actual = [(h["pin"], h["state"]) for h in history if h["pin"] == pin]
    expected = [(pin, s) for s in expected_states]
    assert actual == expected, f"Relay GPIO{pin}: expected {expected}, got {actual}"


P_ACS712 = 0
P_LIGHT = 1
P_WATER = 2
P_SOIL = 3
TANK_GPIO = 20
DRAWER_GPIO = 21
PUMP_GPIO = 10
FERTILIZER_GPIO = 17
PESTICIDE_GPIO = 27


class TestBasicSensorRead:
    def test_basic_sensor_read(self, hil, mock_sleep, minimal_config):
        hil.set_adc_channel(P_SOIL, 19660)
        hil.set_adc_channel(P_WATER, 52428)
        hil.set_adc_channel(P_LIGHT, 32768)
        hil.set_dht22(25.0, 60.0)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        sensors = _get_uploaded_sensors(app)
        values = {s["kind"]: s["value"] for s in sensors}
        assert values["soil"] == 70
        assert values["water"] == 80
        assert values["light"] == 50
        assert values["temperature"] == 25.0


class TestLimitSwitchAlarm:
    def test_limit_switch_alarm(self, hil, mock_sleep, minimal_config):
        hil.set_limit_switch(TANK_GPIO, hil.GPIO_HIGH)
        hil.set_limit_switch(DRAWER_GPIO, hil.GPIO_LOW)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        state = _get_uploaded_state(app)
        assert state["tankSwitchOpen"] is True
        assert state["drawerSwitchOpen"] is False


class TestCommandExecution:
    def test_command_execution(self, hil, mock_sleep, minimal_config):
        app = _make_app(minimal_config, hil)
        app.api_client.upload_sensor_data = AsyncMock(
            return_value=[{"kind": "pump", "durationMs": 5000}]
        )
        _run_sensor_cycle(app)
        _assert_relay_history(hil, PUMP_GPIO, [True, False])

    def test_multiple_simultaneous_commands(self, hil, mock_sleep, minimal_config):
        app = _make_app(minimal_config, hil)
        app.api_client.upload_sensor_data = AsyncMock(
            return_value=[
                {"kind": "pump", "durationMs": 5000},
                {"kind": "fertilizer", "durationMs": 5000},
            ]
        )
        _run_sensor_cycle(app)
        _assert_relay_history(hil, PUMP_GPIO, [True, False])
        _assert_relay_history(hil, FERTILIZER_GPIO, [True, False])


class TestBatteryCurrent:
    def test_battery_charging(self, hil, mock_sleep, minimal_config):
        hil.set_battery_current(500)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        state = _get_uploaded_state(app)
        assert state["batteryCurrent"] >= 450

    def test_battery_discharging(self, hil, mock_sleep, minimal_config):
        hil.set_battery_current(-200)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        state = _get_uploaded_state(app)
        assert state["batteryCurrent"] <= -150


class TestSensorFailure:
    def test_dht22_failure(self, hil, mock_sleep, minimal_config):
        hil.set_dht22_fail("runtime")
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        sensors = _get_uploaded_sensors(app)
        for s in sensors:
            if s["kind"] in ("temperature", "air"):
                assert s["value"] is None
                assert s.get("error") is True

    def test_adc_channel_failure(self, hil, mock_sleep, minimal_config):
        hil.set_adc_fail(P_SOIL)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        sensors = _get_uploaded_sensors(app)
        for s in sensors:
            if s["kind"] == "soil":
                assert s["value"] is None
                assert s.get("error") is True


class TestSensorDebouncing:
    def test_limit_switch_debouncing(self, hil, mock_sleep, minimal_config):
        hil.set_limit_switch(TANK_GPIO, hil.GPIO_HIGH)
        app = _make_app_with_queue(minimal_config, hil)
        asyncio.run(app.sensors.async_read_all_sensors())
        state = asyncio.run(app.sensors.async_get_current_state({}))
        assert state["tankSwitchOpen"] is True
        hil.set_gpio_input_sequence(
            TANK_GPIO,
            [hil.GPIO_HIGH, hil.GPIO_HIGH, hil.GPIO_HIGH, hil.GPIO_LOW, hil.GPIO_LOW],
        )
        state = asyncio.run(app.sensors.async_get_current_state({}))
        assert state["tankSwitchOpen"] is True
        hil.set_gpio_input_sequence(
            TANK_GPIO,
            [hil.GPIO_LOW] * 5,
        )
        state = asyncio.run(app.sensors.async_get_current_state({}))
        assert state["tankSwitchOpen"] is False


class TestCalibrationMapping:
    def test_calibration_soil_inversion(self, hil, mock_sleep, minimal_config):
        from sensors import SensorReader
        reader = SensorReader(minimal_config["sensors"])
        assert reader.calibrate_soil(0) == 100
        assert reader.calibrate_soil(65535) == 0
        assert reader.calibrate_soil(32768) == 49

    def test_calibration_water_proportional(self, hil, mock_sleep, minimal_config):
        from sensors import SensorReader
        reader = SensorReader(minimal_config["sensors"])
        assert reader.calibrate_water(0) == 0
        assert reader.calibrate_water(65535) == 100
        assert reader.calibrate_water(32768) == 50


class TestFullActuationCycle:
    def test_full_actuation_cycle(self, hil, mock_sleep, minimal_config):
        hil.set_adc_channel(P_SOIL, 19660)
        hil.set_adc_channel(P_WATER, 52428)
        hil.set_adc_channel(P_LIGHT, 32768)
        hil.set_dht22(25.0, 60.0)
        app = _make_app(minimal_config, hil)
        app.api_client.upload_sensor_data = AsyncMock(
            return_value=[{"kind": "pump", "durationMs": 3000}]
        )
        _run_sensor_cycle(app)
        _assert_sensor_uploaded(app, "soil", 70)
        _assert_sensor_uploaded(app, "water", 80)
        _assert_relay_history(hil, PUMP_GPIO, [True, False])
        commands_arg = app.api_client.upload_sensor_data.call_args[0][1]
        assert "batteryCurrent" in commands_arg


class TestSensorFailureRecovery:
    def test_sensor_failure_then_recovery(self, hil, mock_sleep, minimal_config):
        hil.set_dht22_fail("runtime")
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        assert app.sensors._health["temperature"]["consecutive_failures"] >= 1
        _run_sensor_cycle(app)
        _run_sensor_cycle(app)
        assert app.sensors._health["temperature"]["degraded"] is True
        hil.set_dht22_ok()
        _run_sensor_cycle(app)
        assert app.sensors._health["temperature"]["consecutive_failures"] == 0
        assert app.sensors._health["temperature"]["degraded"] is False


class TestMultipleSensorTypes:
    def test_all_sensor_types_in_payload(self, hil, mock_sleep, minimal_config):
        hil.set_adc_channel(P_SOIL, 19660)
        hil.set_adc_channel(P_WATER, 52428)
        hil.set_adc_channel(P_LIGHT, 32768)
        hil.set_dht22(25.0, 60.0)
        hil.set_battery_current(500)
        hil.set_limit_switch(TANK_GPIO, hil.GPIO_HIGH)
        hil.set_limit_switch(DRAWER_GPIO, hil.GPIO_LOW)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        sensors = _get_uploaded_sensors(app)
        kinds = {s["kind"] for s in sensors}
        expected = {"soil", "water", "light", "temperature", "air"}
        assert kinds == expected, f"Expected {expected}, got {kinds}"
        state = _get_uploaded_state(app)
        state_fields = {"pumpEnabled", "lightEnabled", "fertilizerEnabled",
                        "pesticideEnabled", "tankSwitchOpen", "drawerSwitchOpen",
                        "batteryCurrent"}
        assert state_fields.issubset(set(state.keys()))


class TestCurrentStateBuilding:
    def test_current_state_all_fields(self, hil, mock_sleep, minimal_config):
        hil.set_limit_switch(TANK_GPIO, hil.GPIO_HIGH)
        hil.set_limit_switch(DRAWER_GPIO, hil.GPIO_HIGH)
        hil.set_battery_current(300)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        state = _get_uploaded_state(app)
        assert "pumpEnabled" in state
        assert "lightEnabled" in state
        assert "fertilizerEnabled" in state
        assert "pesticideEnabled" in state
        assert "tankSwitchOpen" in state
        assert "drawerSwitchOpen" in state
        assert "batteryCurrent" in state
        assert state["tankSwitchOpen"] is True
        assert state["drawerSwitchOpen"] is True
        assert state["batteryCurrent"] >= 250


class TestCombinedRead:
    def test_simultaneous_sensor_limit_switch_current_state(self, hil, mock_sleep, minimal_config):
        hil.set_adc_channel(P_SOIL, 65535)
        hil.set_adc_channel(P_WATER, 0)
        hil.set_adc_channel(P_LIGHT, 0)
        hil.set_dht22(35.0, 80.0)
        hil.set_battery_current(-100)
        hil.set_limit_switch(TANK_GPIO, hil.GPIO_HIGH)
        hil.set_limit_switch(DRAWER_GPIO, hil.GPIO_HIGH)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        sensors = _get_uploaded_sensors(app)
        values = {s["kind"]: s["value"] for s in sensors}
        assert values["soil"] == 0
        assert values["water"] == 0
        assert values["light"] == 0
        assert values["temperature"] == 35.0
        state = _get_uploaded_state(app)
        assert state["tankSwitchOpen"] is True
        assert state["drawerSwitchOpen"] is True
        assert state["batteryCurrent"] <= -50


class TestExtendedUptime:
    def test_extended_uptime(self, hil, mock_sleep, minimal_config):
        hil.set_battery_current(600)
        app = _make_app_with_queue(minimal_config, hil)
        _run_sensor_cycle(app)
        assert app.consecutive_failures == 0
        assert app.sensors.get_coulomb_count() > 0
        coulomb_after_first = app.sensors.get_coulomb_count()
        _run_sensor_cycle(app)
        assert app.sensors.get_coulomb_count() > coulomb_after_first
        hil.set_dht22_fail("runtime")
        _run_sensor_cycle(app)
        assert app.sensors._health["temperature"]["consecutive_failures"] >= 1
        assert app.sensors._health["air"]["consecutive_failures"] >= 1
        hil.set_dht22_ok()
        _run_sensor_cycle(app)
        assert app.sensors._health["temperature"]["consecutive_failures"] == 0
        assert app.sensors._health["air"]["consecutive_failures"] == 0
