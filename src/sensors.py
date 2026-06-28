import time
import logging
import asyncio
from typing import Dict, List, Optional, Tuple
import board
import busio
from adafruit_ads1x15.ads1x15 import Pin
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import adafruit_dht
import RPi.GPIO as GPIO


logger = logging.getLogger("growmate.sensors")


PULL_MODES = {
    "PUD_UP": GPIO.PUD_UP,
    "PUD_DOWN": GPIO.PUD_DOWN,
    "PUD_OFF": GPIO.PUD_OFF,
}


DEFAULTS = {
    "enable_dht22": True,
    "dht22_pin": 4,
    "adc": {
        "i2c_bus": 1,
        "i2c_address": 0x48,
        "gain": 1,
        "samples": 8,
        "sample_delay": 0.01,
        "max_value": 65535,
    },
    "channels": {
        "battery_current": 0,
        "light": 1,
        "water": 2,
        "soil": 3,
    },
    "calibration": {
        "soil": {"min": 0, "max": 65535},
        "light": {"min": 0, "max": 65535},
        "water": {"min": 0, "max": 65535},
    },
    "battery_current": {
        "midpoint_voltage": 2.5,
        "sensitivity": 0.185,
    },
    "limit_switches": {
        "tank_gpio": 20,
        "drawer_gpio": 21,
        "pull_up_down": "PUD_UP",
        "debounce_ms": 50,
        "debounce_samples": 5,
        "debounce_sample_interval": 0.01,
    },
    "health": {
        "failure_threshold": 3,
    },
}


def _nested_get(cfg: dict, keys: list, default=None):
    curr = cfg
    for k in keys:
        if isinstance(curr, dict):
            curr = curr.get(k)
        else:
            return default
        if curr is None:
            return default
    return curr


class SensorReader:

    def __init__(self, sensors_cfg: Optional[dict] = None):
        cfg = sensors_cfg or {}

        self.enable_dht22 = cfg.get("enable_dht22", DEFAULTS["enable_dht22"])
        dht22_pin = cfg.get("dht22_pin", DEFAULTS["dht22_pin"])

        adc_cfg = cfg.get("adc", DEFAULTS["adc"])
        adc_samples = adc_cfg.get("samples", DEFAULTS["adc"]["samples"])
        adc_sample_delay = adc_cfg.get("sample_delay", DEFAULTS["adc"]["sample_delay"])
        adc_max_value = adc_cfg.get("max_value", DEFAULTS["adc"]["max_value"])
        adc_gain = adc_cfg.get("gain", DEFAULTS["adc"]["gain"])

        ch = cfg.get("channels", DEFAULTS["channels"])
        acs712_ch = ch.get("battery_current", DEFAULTS["channels"]["battery_current"])
        light_ch = ch.get("light", DEFAULTS["channels"]["light"])
        water_ch = ch.get("water", DEFAULTS["channels"]["water"])
        soil_ch = ch.get("soil", DEFAULTS["channels"]["soil"])

        cal = cfg.get("calibration", DEFAULTS["calibration"])
        self._soil_cal = cal.get("soil", DEFAULTS["calibration"]["soil"])
        self._light_cal = cal.get("light", DEFAULTS["calibration"]["light"])
        self._water_cal = cal.get("water", DEFAULTS["calibration"]["water"])

        batt_cfg = cfg.get("battery_current", DEFAULTS["battery_current"])
        self._batt_midpoint = batt_cfg.get("midpoint_voltage", DEFAULTS["battery_current"]["midpoint_voltage"])
        self._batt_sensitivity = batt_cfg.get("sensitivity", DEFAULTS["battery_current"]["sensitivity"])

        ls_cfg = cfg.get("limit_switches", DEFAULTS["limit_switches"])
        self._tank_gpio = ls_cfg.get("tank_gpio", DEFAULTS["limit_switches"]["tank_gpio"])
        self._drawer_gpio = ls_cfg.get("drawer_gpio", DEFAULTS["limit_switches"]["drawer_gpio"])
        self._ls_pull = PULL_MODES.get(
            ls_cfg.get("pull_up_down", DEFAULTS["limit_switches"]["pull_up_down"]).upper(),
            GPIO.PUD_UP,
        )
        self._debounce_ms = ls_cfg.get("debounce_ms", DEFAULTS["limit_switches"]["debounce_ms"])
        self._debounce_samples = ls_cfg.get("debounce_samples", DEFAULTS["limit_switches"]["debounce_samples"])
        self._debounce_interval = ls_cfg.get("debounce_sample_interval", DEFAULTS["limit_switches"]["debounce_sample_interval"])

        health_cfg = cfg.get("health", DEFAULTS["health"])
        self._health_failure_threshold = health_cfg.get("failure_threshold", DEFAULTS["health"]["failure_threshold"])

        self.adc_samples = adc_samples
        self.adc_sample_delay = adc_sample_delay
        self.adc_max_value = adc_max_value

        self._coulomb_counter_mah = 0.0

        self._health = {
            "soil": {"consecutive_failures": 0, "degraded": False},
            "light": {"consecutive_failures": 0, "degraded": False},
            "water": {"consecutive_failures": 0, "degraded": False},
            "temperature": {"consecutive_failures": 0, "degraded": False},
            "air": {"consecutive_failures": 0, "degraded": False},
            "battery": {"consecutive_failures": 0, "degraded": False},
        }

        ch_map = {acs712_ch: Pin.A0, light_ch: Pin.A1, water_ch: Pin.A2, soil_ch: Pin.A3}

        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self.ads = ADS.ADS1115(self.i2c, address=adc_cfg.get("i2c_address", DEFAULTS["adc"]["i2c_address"]))
            self.ads.gain = adc_gain

            self.acs712_channel = AnalogIn(self.ads, ch_map[acs712_ch])
            self.light_channel = AnalogIn(self.ads, ch_map[light_ch])
            self.water_channel = AnalogIn(self.ads, ch_map[water_ch])
            self.soil_channel = AnalogIn(self.ads, ch_map[soil_ch])

            logger.info(f"ADS1115 initialized (ch{acs712_ch}=ACS712, ch{light_ch}=light, ch{water_ch}=water, ch{soil_ch}=soil)")
        except Exception as e:
            logger.error(f"Failed to initialize ADS1115: {e}")
            raise

        self.dht_device = None
        if self.enable_dht22:
            dht_gpio = getattr(board, f"D{dht22_pin}", board.D4)
            try:
                self.dht_device = adafruit_dht.DHT22(dht_gpio)
                logger.info(f"DHT22 initialized on GPIO{dht22_pin}")
            except Exception as e:
                logger.warning(f"Failed to initialize DHT22: {e}")
                self.dht_device = None

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._tank_gpio, GPIO.IN, pull_up_down=self._ls_pull)
            GPIO.setup(self._drawer_gpio, GPIO.IN, pull_up_down=self._ls_pull)
            logger.info(f"Limit switches initialized (GPIO{self._tank_gpio}=tank, GPIO{self._drawer_gpio}=drawer)")
        except Exception as e:
            logger.warning(f"Failed to setup limit switch GPIOs: {e}")

    def _update_health(self, sensor_name: str, success: bool):
        health = self._health[sensor_name]
        if success:
            health["consecutive_failures"] = 0
            health["degraded"] = False
        else:
            health["consecutive_failures"] += 1
            if health["consecutive_failures"] >= self._health_failure_threshold:
                health["degraded"] = True
                logger.warning(
                    f"Sensor {sensor_name} degraded "
                    f"({health['consecutive_failures']} consecutive failures)"
                )

    def get_health(self) -> Dict:
        return {k: dict(v) for k, v in self._health.items()}

    def get_coulomb_count(self) -> float:
        return self._coulomb_counter_mah

    def reset_coulomb_count(self):
        self._coulomb_counter_mah = 0.0

    def read_adc_averaged(self, channel: AnalogIn) -> Optional[int]:
        samples = []
        for _ in range(self.adc_samples):
            try:
                samples.append(channel.value)
                time.sleep(self.adc_sample_delay)
            except Exception:
                continue
        if not samples:
            return None
        return int(sum(samples) / len(samples))

    def calibrate_soil(self, raw: int) -> int:
        mv = raw / self.adc_max_value * 4096
        return max(0, min(100, int(100 - (mv / 4096 * 100))))

    def calibrate_water(self, raw: int) -> int:
        mv = raw / self.adc_max_value * 4096
        return max(0, min(100, int(mv / 4096 * 100)))

    def calibrate_light(self, raw: int) -> int:
        mv = raw / self.adc_max_value * 4096
        return max(0, min(100, int(mv / 4096 * 100)))

    def read_battery_current(self) -> Optional[int]:
        try:
            raw = self.read_adc_averaged(self.acs712_channel)
            if raw is None:
                self._update_health("battery", False)
                return None
            voltage = raw / self.adc_max_value * 4.096
            current_ma = int((voltage - self._batt_midpoint) / self._batt_sensitivity * 1000)
            self._update_health("battery", True)
            return current_ma
        except Exception as e:
            logger.error(f"Failed to read battery current: {e}")
            self._update_health("battery", False)
            return None

    def read_soil_moisture(self) -> Optional[Dict]:
        try:
            raw = self.read_adc_averaged(self.soil_channel)
            if raw is None:
                self._update_health("soil", False)
                return None
            value = self.calibrate_soil(raw)
            self._update_health("soil", True)
            return {"kind": "soil", "value": value, "unit": "%", "raw": raw}
        except Exception as e:
            logger.error(f"Failed to read soil moisture: {e}")
            self._update_health("soil", False)
            return None

    def read_light_level(self) -> Optional[Dict]:
        try:
            raw = self.read_adc_averaged(self.light_channel)
            if raw is None:
                self._update_health("light", False)
                return None
            value = self.calibrate_light(raw)
            self._update_health("light", True)
            return {"kind": "light", "value": value, "unit": "%", "raw": raw}
        except Exception as e:
            logger.error(f"Failed to read light level: {e}")
            self._update_health("light", False)
            return None

    def read_water_level(self) -> Optional[Dict]:
        try:
            raw = self.read_adc_averaged(self.water_channel)
            if raw is None:
                self._update_health("water", False)
                return None
            value = self.calibrate_water(raw)
            self._update_health("water", True)
            return {"kind": "water", "value": value, "unit": "%", "raw": raw}
        except Exception as e:
            logger.error(f"Failed to read water level: {e}")
            self._update_health("water", False)
            return None

    def read_dht22(self) -> Tuple[Optional[Dict], Optional[Dict]]:
        if not self.dht_device:
            return None, None

        for attempt in range(2):
            try:
                delay = 0.12 if attempt == 0 else 0.18
                time.sleep(delay)

                temperature = self.dht_device.temperature
                humidity = self.dht_device.humidity

                if temperature is not None and humidity is not None:
                    temp_data = {"kind": "temperature", "value": round(temperature, 1), "unit": "C"}
                    humidity_data = {"kind": "air", "value": round(humidity, 1), "unit": "%"}
                    return temp_data, humidity_data
            except RuntimeError as e:
                logger.warning(f"DHT22 read error (attempt {attempt + 1}): {e}")
                continue
            except Exception as e:
                logger.error(f"DHT22 unexpected error: {e}")
                break

        return None, None

    def read_limit_switches(self) -> Dict:
        try:
            tank_open = GPIO.input(self._tank_gpio) == GPIO.HIGH
            drawer_open = GPIO.input(self._drawer_gpio) == GPIO.HIGH
            return {"tankSwitchOpen": tank_open, "drawerSwitchOpen": drawer_open}
        except Exception as e:
            logger.error(f"Failed to read limit switches: {e}")
            return {"tankSwitchOpen": None, "drawerSwitchOpen": None}

    def read_limit_switches_debounced(self) -> Dict:
        time.sleep(self._debounce_ms / 1000.0)

        tank_readings = []
        drawer_readings = []

        for _ in range(self._debounce_samples):
            try:
                tank_readings.append(GPIO.input(self._tank_gpio))
                drawer_readings.append(GPIO.input(self._drawer_gpio))
                time.sleep(self._debounce_interval)
            except Exception:
                continue

        if not tank_readings or not drawer_readings:
            return {"tankSwitchOpen": None, "drawerSwitchOpen": None}

        tank_open = sum(tank_readings) > len(tank_readings) // 2
        drawer_open = sum(drawer_readings) > len(drawer_readings) // 2

        return {
            "tankSwitchOpen": tank_open == GPIO.HIGH,
            "drawerSwitchOpen": drawer_open == GPIO.HIGH,
        }

    def get_current_state(self, actuator_states: Optional[Dict] = None) -> Dict:
        battery_current = self.read_battery_current()
        if battery_current is not None:
            self._coulomb_counter_mah += battery_current / 60.0

        limit_switches = self.read_limit_switches_debounced()

        if actuator_states:
            pump_enabled = actuator_states.get("pumpEnabled", False)
            fertilizer_enabled = actuator_states.get("fertilizerEnabled", False)
            pesticide_enabled = actuator_states.get("pesticideEnabled", False)
        else:
            pump_enabled = False
            fertilizer_enabled = False
            pesticide_enabled = False

        return {
            "pumpEnabled": pump_enabled,
            "lightEnabled": False,
            "fertilizerEnabled": fertilizer_enabled,
            "pesticideEnabled": pesticide_enabled,
            "tankSwitchOpen": limit_switches.get("tankSwitchOpen", False),
            "drawerSwitchOpen": limit_switches.get("drawerSwitchOpen", False),
            "batteryCurrent": battery_current if battery_current is not None else 0,
        }

    def read_all_sensors(self) -> List[Dict]:
        sensors = []

        soil = self.read_soil_moisture()
        if soil:
            sensors.append(soil)
        else:
            sensors.append({"kind": "soil", "value": None, "unit": "%", "error": True})

        light = self.read_light_level()
        if light:
            sensors.append(light)
        else:
            sensors.append({"kind": "light", "value": None, "unit": "%", "error": True})

        water = self.read_water_level()
        if water:
            sensors.append(water)
        else:
            sensors.append({"kind": "water", "value": None, "unit": "%", "error": True})

        if self.enable_dht22:
            temp, humidity = self.read_dht22()
            if temp:
                sensors.append(temp)
                if humidity:
                    sensors.append(humidity)
                else:
                    sensors.append({"kind": "air", "value": None, "unit": "%", "error": True})
                self._update_health("temperature", True)
                self._update_health("air", True)
            else:
                sensors.append({"kind": "temperature", "value": None, "unit": "C", "error": True})
                sensors.append({"kind": "air", "value": None, "unit": "%", "error": True})
                self._update_health("temperature", False)
                self._update_health("air", False)

        logger.info(f"Read {len(sensors)} sensors")
        return sensors

    def cleanup(self):
        if self.dht_device:
            try:
                self.dht_device.exit()
            except Exception:
                pass
        try:
            GPIO.cleanup([self._tank_gpio, self._drawer_gpio])
        except Exception:
            pass
        logger.info("Sensor cleanup complete")

    async def async_read_all_sensors(self) -> List[Dict]:
        return await asyncio.to_thread(self.read_all_sensors)

    async def async_get_current_state(self, actuator_states: Optional[Dict] = None) -> Dict:
        return await asyncio.to_thread(self.get_current_state, actuator_states)


def read_sensors(config: dict = None) -> List[Dict]:
    sensors_cfg = (config or {}).get('sensors', {})
    reader = SensorReader(sensors_cfg)
    try:
        return reader.read_all_sensors()
    finally:
        reader.cleanup()


async def async_read_sensors(config: dict = None) -> List[Dict]:
    sensors_cfg = (config or {}).get('sensors', {})
    reader = SensorReader(sensors_cfg)
    try:
        return await reader.async_read_all_sensors()
    finally:
        reader.cleanup()
