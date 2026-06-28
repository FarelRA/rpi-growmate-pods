"""
pytest conftest — global fixtures and hardware mock patches.

All hardware-dependent modules (RPi.GPIO, adafruit_*, gpiozero, board, busio,
systemd.journal) are mocked at the sys.modules level so that src/* imports
succeed without real hardware.
"""

import sys
import types
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# sys.modules mocks — injected before any src import
# ---------------------------------------------------------------------------
_HARDWARE_MODULES = [
    "RPi", "RPi.GPIO",
    "board",
    "busio",
    "adafruit_ads1x15", "adafruit_ads1x15.ads1115", "adafruit_ads1x15.analog_in",
    "adafruit_blinka",
    "adafruit_dht",
    "adafruit_circuitpython_dht",
    "gpiozero", "gpiozero.pins", "gpiozero.pins.mock",
    "systemd", "systemd.journal",
]

for _mod_name in _HARDWARE_MODULES:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

# Patch specific class references that src/ imports by name
# Use sys.modules directly so RPi.GPIO resolves to the same mock in sensors.py
_rpi_mod = sys.modules["RPi"]
_rpi_gpio = sys.modules["RPi.GPIO"]
_rpi_mod.GPIO = _rpi_gpio

_rpi_gpio.BCM = 11
_rpi_gpio.IN = 1
_rpi_gpio.OUT = 0
_rpi_gpio.HIGH = 1
_rpi_gpio.LOW = 0
_rpi_gpio.PUD_UP = 22
_rpi_gpio.PUD_DOWN = 21
_rpi_gpio.PUD_OFF = 20
_rpi_gpio.setmode = MagicMock()
_rpi_gpio.setup = MagicMock()
_rpi_gpio.input = MagicMock(return_value=_rpi_gpio.HIGH)
_rpi_gpio.output = MagicMock()
_rpi_gpio.cleanup = MagicMock()

# Keep a local reference for use in conftest's own code
GPIO = _rpi_gpio

import gpiozero
gpiozero.OutputDevice = MagicMock()
gpiozero.OutputDevice.is_active = PropertyMock(return_value=False)

# Use sys.modules directly for submodules to avoid import-machinery
# creating distinct mock objects from the ones sensors.py will resolve.
_ads_mod = sys.modules["adafruit_ads1x15.ads1115"]
_ana_mod = sys.modules["adafruit_ads1x15.analog_in"]
_parent_ada = sys.modules["adafruit_ads1x15"]
_parent_ada.ads1115 = _ads_mod
_parent_ada.analog_in = _ana_mod

_ads_mod.ADS1115 = MagicMock()
_ads_mod.P0 = 0
_ads_mod.P1 = 1
_ads_mod.P2 = 2
_ads_mod.P3 = 3

_ana_mod.AnalogIn = MagicMock()

import adafruit_dht as DHT
DHT.DHT22 = MagicMock()

# Fix mock chaining so AnalogIn.value works
mock_analog_in_instance = MagicMock()
mock_analog_in_instance.value = 32768
_ana_mod.AnalogIn.return_value = mock_analog_in_instance

# Fix gpiozero.OutputDevice mock chain — use side_effect so each
# OutputDevice() call yields a fresh mock.
def _make_output_device(*args, **kwargs):
    dev = MagicMock()
    dev.is_active = False
    return dev
gpiozero.OutputDevice.side_effect = _make_output_device

# Fix DHT22 mock chain
mock_dht22 = MagicMock()
mock_dht22.temperature = 25.0
mock_dht22.humidity = 60.0
DHT.DHT22.return_value = mock_dht22

import board
board.SCL = MagicMock()
board.SDA = MagicMock()
board.D4 = MagicMock()

import busio
busio.I2C = MagicMock()

import systemd.journal as journal
journal.JournalHandler = MagicMock()

# ---------------------------------------------------------------------------
# Add src/ to sys.path so tests can `import config_manager` etc.
# ---------------------------------------------------------------------------
from pathlib import Path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_config(monkeypatch):
    """Return a copy of the full default config dict (V2 schema)."""
    monkeypatch.setenv("DEVICE_ID", "growmate-b827eb123456")
    from config_manager import ConfigManager
    cfg = ConfigManager.get_default_config()
    return cfg


@pytest.fixture
def minimal_config():
    """Minimal valid config for fast test setup."""
    return {
        "version": 9,
        "device": {"id": "growmate-test"},
        "api": {
            "sensor_url": "https://test.growmate.bond/api/v2/sensors",
            "stream_register_url": "https://test.growmate.bond/api/v2/stream/register",
            "timeout_sensor": 30.0,
            "timeout_stream_register": 10.0,
        },
        "network": {
            "provisioned": False,
            "wifi_ssid": "",
            "wifi_password": "",
            "wifi": {"interface": "wlan0", "connect_timeout": 12, "connect_retries": 4},
        },
        "ap_mode": {
            "ssid": "GrowMate-TEST",
            "password": "growmate",
            "channel": 1,
            "ip_address": "192.168.4.1",
            "netmask": "255.255.255.0",
            "dhcp_range_start": "192.168.4.2",
            "dhcp_range_end": "192.168.4.20",
            "interface": "wlan0",
        },
        "onboarding": {"host": "0.0.0.0", "port": 80},
        "intervals": {
            "sensor_reading": 60,
            "failure_monitor": 30,
            "camera_watchdog": 30,
            "queue_cleanup": 3600,
            "queue_vacuum": 604800,
            "queue_stats": 300,
            "health_check": 300,
        },
        "queue": {
            "enabled": True,
            "db_path": "/tmp/test_growmate_queue.db",
            "max_age_hours": 24,
            "max_sensor_entries": 1440,
            "cleanup_interval": 3600,
            "max_retries": 5,
            "vacuum_interval": 604800,
        },
        "upload_processor": {
            "max_concurrent": 3,
            "delay": 0.5,
            "idle_sleep": 2.0,
            "batch_sleep": 0.1,
        },
        "retry": {"max_attempts": 6, "initial_delay": 1.0, "max_delay": 32.0, "jitter": 0.25},
        "circuit_breaker": {"failure_threshold": 5, "recovery_timeout": 60, "success_threshold": 2},
        "sensors": {
            "enable_dht22": True,
            "dht22_pin": 4,
            "adc": {"i2c_bus": 1, "i2c_address": 0x48, "gain": 1, "samples": 8, "sample_delay": 0.01, "max_value": 65535},
            "channels": {"battery_current": 0, "light": 1, "water": 2, "soil": 3},
            "calibration": {"soil": {"min": 0, "max": 65535}, "light": {"min": 0, "max": 65535}, "water": {"min": 0, "max": 65535}},
            "battery_current": {"midpoint_voltage": 2.5, "sensitivity": 0.185},
            "limit_switches": {"tank_gpio": 20, "drawer_gpio": 21, "pull_up_down": "PUD_UP", "debounce_ms": 50, "debounce_samples": 5, "debounce_sample_interval": 0.01},
            "health": {"failure_threshold": 3},
        },
        "actuators": {"pins": {"pump": 10, "fertilizer": 17, "pesticide": 27}, "active_high": True, "initial_value": False, "journal_size": 1000, "journal_trim": 500},
        "camera": {"enabled": True, "port": 8554, "width": 640, "height": 480, "framerate": 15, "bitrate": 1000000, "profile": "baseline", "level": "3.1", "denoise": "cdn_off", "restart_delay": 0.5},
        "failure": {"consecutive_threshold": 5},
        "health_monitor": {"history_size": 100, "camera_crash_threshold": 5},
        "stream_registration": {"max_attempts": 10, "base_delay": 1.0, "max_delay": 60.0},
        "logging": {"level": "INFO", "file": "/tmp/test_growmate.log", "format": "json", "max_bytes": 10485760, "backup_count": 5, "modules": {}},
        "features": {"offline_queue": True, "hot_reload": True, "circuit_breaker": True},
    }


@pytest.fixture
def tmp_config_file(tmp_path, minimal_config):
    """Write minimal_config to a temp YAML file and return the path."""
    import yaml
    cfg_path = tmp_path / "config.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(minimal_config, f, default_flow_style=False)
    return cfg_path


@pytest.fixture
def mock_subprocess(mocker):
    """Mock subprocess.run to return a successful result."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "connected\n"
    mock_result.stderr = ""
    return mocker.patch("subprocess.run", return_value=mock_result)


@pytest.fixture
def mock_subprocess_fail(mocker):
    """Mock subprocess.run to raise CalledProcessError."""
    import subprocess
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "error"
    return mocker.patch("subprocess.run", return_value=mock_result)


@pytest.fixture
def mock_path_open(mocker):
    """Mock Path.open and Path.read_text/Path.write_text for file I/O."""
    mock_path = mocker.patch("pathlib.Path.open", mocker.mock_open(read_data=""))
    mock_read = mocker.patch("pathlib.Path.read_text", return_value="test content")
    mock_write = mocker.patch("pathlib.Path.write_text")
    return {"open": mock_path, "read_text": mock_read, "write_text": mock_write}


@pytest.fixture
def mock_sleep(mocker):
    """Mock time.sleep to speed up debounce tests."""
    return mocker.patch("time.sleep")
