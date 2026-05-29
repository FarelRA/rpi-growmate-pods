#!/usr/bin/env python3
"""
Hardware testing script for GrowMate Pods.

Tests all hardware components:
- ADS1115 ADC (I2C communication)
- 3 analog sensors (soil, light, water)
- DHT22 sensor (temperature, humidity)
- Pi Camera Module v1
- GPIO relays (pump, light)
"""

import sys
import time
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

print("=" * 60)
print("GrowMate Pods - Hardware Test")
print("=" * 60)
print()

# Test 1: I2C Bus
print("[1/6] Testing I2C bus...")
try:
    import board
    import busio
    i2c = busio.I2C(board.SCL, board.SDA)
    print("✓ I2C bus initialized")
    
    # Scan for devices
    while not i2c.try_lock():
        pass
    devices = i2c.scan()
    i2c.unlock()
    
    print(f"✓ Found {len(devices)} I2C device(s): {[hex(d) for d in devices]}")
    
    if 0x48 in devices:
        print("✓ ADS1115 detected at address 0x48")
    else:
        print("✗ ADS1115 NOT detected (expected at 0x48)")
except Exception as e:
    print(f"✗ I2C test failed: {e}")

print()

# Test 2: ADS1115 ADC
print("[2/6] Testing ADS1115 ADC...")
try:
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    
    ads = ADS.ADS1115(i2c)
    
    # Test all 3 channels
    channels = [
        (ADS.P0, "Soil Moisture (A0)"),
        (ADS.P1, "Light Level (A1)"),
        (ADS.P2, "Water Level (A2)")
    ]
    
    for channel, name in channels:
        analog_in = AnalogIn(ads, channel)
        value = analog_in.value
        voltage = analog_in.voltage
        print(f"✓ {name}: {value} (raw), {voltage:.2f}V")
    
except Exception as e:
    print(f"✗ ADS1115 test failed: {e}")

print()

# Test 3: DHT22 Sensor
print("[3/6] Testing DHT22 sensor...")
try:
    import adafruit_dht
    
    dht_device = adafruit_dht.DHT22(board.D4)
    
    # Try reading (may need multiple attempts)
    for attempt in range(3):
        try:
            time.sleep(2)
            temperature = dht_device.temperature
            humidity = dht_device.humidity
            
            if temperature is not None and humidity is not None:
                print(f"✓ Temperature: {temperature:.1f}°C")
                print(f"✓ Humidity: {humidity:.1f}%")
                break
        except RuntimeError as e:
            if attempt < 2:
                print(f"  Retry {attempt + 1}/3...")
            else:
                print(f"✗ DHT22 read failed after 3 attempts")
    
    dht_device.exit()
    
except Exception as e:
    print(f"✗ DHT22 test failed: {e}")

print()

# Test 4: Pi Camera
print("[4/6] Testing Pi Camera Module...")
try:
    from picamera2 import Picamera2
    
    camera = Picamera2()
    config = camera.create_still_configuration(
        main={"size": (1600, 1200)},
        buffer_count=1
    )
    camera.configure(config)
    camera.start()
    
    print("✓ Camera initialized (1600x1200)")
    
    # Capture test image
    test_image = "/tmp/growmate_test.jpg"
    camera.capture_file(test_image, format='jpeg')
    
    # Check file size
    import os
    size = os.path.getsize(test_image)
    print(f"✓ Test image captured: {size} bytes")
    print(f"  Saved to: {test_image}")
    
    camera.stop()
    camera.close()
    
except Exception as e:
    print(f"✗ Camera test failed: {e}")

print()

# Test 5: GPIO Relays
print("[5/6] Testing GPIO relays...")
try:
    from gpiozero import OutputDevice
    
    pump = OutputDevice(17, active_high=True, initial_value=False)
    light = OutputDevice(27, active_high=True, initial_value=False)
    
    print("✓ GPIO initialized (Pump: GPIO17, Light: GPIO27)")
    
    # Test pump relay
    print("  Testing pump relay (2 second pulse)...")
    pump.on()
    time.sleep(2)
    pump.off()
    print("✓ Pump relay test complete")
    
    # Test light relay
    print("  Testing light relay (2 second pulse)...")
    light.on()
    time.sleep(2)
    light.off()
    print("✓ Light relay test complete")
    
    pump.close()
    light.close()
    
except Exception as e:
    print(f"✗ GPIO test failed: {e}")

print()

# Test 6: Network Interface
print("[6/6] Testing network interface...")
try:
    import subprocess
    
    # Check wlan0 exists
    result = subprocess.run(
        ['ip', 'link', 'show', 'wlan0'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("✓ wlan0 interface exists")
        
        # Check if interface is up
        if 'state UP' in result.stdout:
            print("✓ wlan0 is UP")
        else:
            print("  wlan0 is DOWN (this is normal if not connected)")
    else:
        print("✗ wlan0 interface not found")
    
except Exception as e:
    print(f"✗ Network test failed: {e}")

print()
print("=" * 60)
print("Hardware test complete!")
print("=" * 60)
print()
print("Next steps:")
print("1. Review test results above")
print("2. Fix any hardware issues")
print("3. Run 'sudo systemctl start growmate' to start the service")
print()
