"""
Sensor reading module for GrowMate Pods.

Handles reading from:
- ADS1115 ADC (3 analog sensors: soil moisture, light, water level)
- DHT22 digital sensor (temperature, humidity)

Includes calibration and data formatting for API upload.
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import adafruit_dht

from utils import map_range, clamp


logger = logging.getLogger("growmate.sensors")


# ADC channels (ADS1115)
SOIL_MOISTURE_CHANNEL = 0  # A0
LIGHT_SENSOR_CHANNEL = 1   # A1
WATER_LEVEL_CHANNEL = 2    # A2

# DHT22 GPIO pin
DHT22_PIN = board.D4

# ADC sampling configuration (from ESP32: 8 samples with 10ms delay)
ADC_SAMPLES = 8
ADC_SAMPLE_DELAY = 0.01  # 10ms

# ADS1115 resolution (16-bit)
ADC_MAX_VALUE = 65535


class SensorReader:
    """Reads sensor data from ADS1115 ADC and DHT22."""
    
    def __init__(self, config: Dict):
        """
        Initialize sensor reader.
        
        Args:
            config: Configuration dictionary with calibration values
        """
        self.config = config
        self.calibration = config.get('calibration', {})
        self.enable_dht22 = config.get('sensors', {}).get('enable_dht22', True)
        
        # Initialize I2C and ADS1115
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self.ads = ADS.ADS1115(self.i2c)
            
            # Create analog input channels
            self.soil_channel = AnalogIn(self.ads, ADS.P0)
            self.light_channel = AnalogIn(self.ads, ADS.P1)
            self.water_channel = AnalogIn(self.ads, ADS.P2)
            
            logger.info("ADS1115 ADC initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize ADS1115: {e}")
            raise
        
        # Initialize DHT22
        self.dht_device = None
        if self.enable_dht22:
            try:
                self.dht_device = adafruit_dht.DHT22(DHT22_PIN)
                logger.info("DHT22 sensor initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize DHT22: {e}")
                self.dht_device = None
    
    def read_adc_averaged(self, channel: AnalogIn) -> Optional[int]:
        """
        Read ADC channel with averaging.
        
        Takes 8 samples with 10ms delay between each (matches ESP32 behavior).
        
        Args:
            channel: AnalogIn channel to read
            
        Returns:
            Averaged raw ADC value (0-65535) or None on failure
        """
        samples = []
        
        for _ in range(ADC_SAMPLES):
            try:
                value = channel.value
                samples.append(value)
                time.sleep(ADC_SAMPLE_DELAY)
            except Exception as e:
                logger.warning(f"ADC read error: {e}")
                continue
        
        if not samples:
            return None
        
        return int(sum(samples) / len(samples))
    
    def calibrate_sensor(self, raw_value: int, sensor_type: str) -> int:
        """
        Apply calibration to convert raw ADC value to percentage.
        
        Args:
            raw_value: Raw ADC value (0-65535)
            sensor_type: Sensor type key in calibration config
            
        Returns:
            Calibrated percentage value (0-100)
        """
        cal = self.calibration.get(sensor_type, {'min': 0, 'max': ADC_MAX_VALUE})
        min_val = cal.get('min', 0)
        max_val = cal.get('max', ADC_MAX_VALUE)
        
        # Map raw value to 0-100% using calibration
        percent = map_range(raw_value, min_val, max_val, 0, 100)
        
        return int(round(percent))
    
    def read_soil_moisture(self) -> Optional[Dict]:
        """
        Read soil moisture sensor.
        
        Returns:
            Sensor data dict or None on failure
        """
        try:
            raw = self.read_adc_averaged(self.soil_channel)
            if raw is None:
                return None
            
            value = self.calibrate_sensor(raw, 'soil_moisture')
            
            return {
                'kind': 'soil',
                'value': value,
                'unit': '%',
                'raw': raw
            }
        except Exception as e:
            logger.error(f"Failed to read soil moisture: {e}")
            return None
    
    def read_light_level(self) -> Optional[Dict]:
        """
        Read light level sensor.
        
        Returns:
            Sensor data dict or None on failure
        """
        try:
            raw = self.read_adc_averaged(self.light_channel)
            if raw is None:
                return None
            
            value = self.calibrate_sensor(raw, 'light')
            
            return {
                'kind': 'light',
                'value': value,
                'unit': '%',
                'raw': raw
            }
        except Exception as e:
            logger.error(f"Failed to read light level: {e}")
            return None
    
    def read_water_level(self) -> Optional[Dict]:
        """
        Read water level sensor.
        
        Returns:
            Sensor data dict or None on failure
        """
        try:
            raw = self.read_adc_averaged(self.water_channel)
            if raw is None:
                return None
            
            value = self.calibrate_sensor(raw, 'water_level')
            
            return {
                'kind': 'water',
                'value': value,
                'unit': '%',
                'raw': raw
            }
        except Exception as e:
            logger.error(f"Failed to read water level: {e}")
            return None
    
    def read_dht22(self) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        Read DHT22 temperature and humidity.
        
        Implements retry logic from ESP32: retry once with longer delay.
        
        Returns:
            Tuple of (temperature_dict, humidity_dict) or (None, None) on failure
        """
        if not self.dht_device:
            return None, None
        
        # Try reading with retry (matches ESP32 behavior)
        for attempt in range(2):
            try:
                # Wait before reading (120ms first attempt, 180ms retry)
                delay = 0.12 if attempt == 0 else 0.18
                time.sleep(delay)
                
                temperature = self.dht_device.temperature
                humidity = self.dht_device.humidity
                
                if temperature is not None and humidity is not None:
                    # DHT22 sensors do NOT include 'raw' field (ESP32 compatibility)
                    temp_data = {
                        'kind': 'temperature',
                        'value': int(round(temperature)),
                        'unit': 'C'
                    }
                    
                    humidity_data = {
                        'kind': 'air',
                        'value': int(round(humidity)),
                        'unit': '%'
                    }
                    
                    return temp_data, humidity_data
                
            except RuntimeError as e:
                logger.warning(f"DHT22 read error (attempt {attempt + 1}): {e}")
                continue
            except Exception as e:
                logger.error(f"DHT22 unexpected error: {e}")
                break
        
        return None, None
    
    def read_all_sensors(self) -> List[Dict]:
        """
        Read all available sensors.
        
        Returns only sensors that successfully returned data (matches ESP32 behavior).
        
        Returns:
            List of sensor data dictionaries
        """
        sensors = []
        
        # Read analog sensors
        soil = self.read_soil_moisture()
        if soil:
            sensors.append(soil)
        
        light = self.read_light_level()
        if light:
            sensors.append(light)
        
        water = self.read_water_level()
        if water:
            sensors.append(water)
        
        # Read DHT22
        if self.enable_dht22:
            temp, humidity = self.read_dht22()
            if temp:
                sensors.append(temp)
            if humidity:
                sensors.append(humidity)
        
        logger.info(f"Read {len(sensors)} sensors successfully")
        return sensors
    
    def cleanup(self):
        """Clean up sensor resources."""
        if self.dht_device:
            try:
                self.dht_device.exit()
            except:
                pass
        
        logger.info("Sensor cleanup complete")


# Convenience function
def read_sensors(config: Dict) -> List[Dict]:
    """
    Read all sensors and return data list.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        List of sensor data dictionaries
    """
    reader = SensorReader(config)
    try:
        return reader.read_all_sensors()
    finally:
        reader.cleanup()
