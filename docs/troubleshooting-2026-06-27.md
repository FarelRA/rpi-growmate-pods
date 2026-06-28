# Troubleshooting Guide

Common issues and solutions for GrowMate Pods.

## Table of Contents

- [Service Issues](#service-issues)
- [Hardware Issues](#hardware-issues)
- [Network Issues](#network-issues)
- [Sensor Issues](#sensor-issues)
- [Camera Issues](#camera-issues)
- [API Issues](#api-issues)
- [Performance Issues](#performance-issues)
- [Log Analysis](#log-analysis)
- [Recovery Procedures](#recovery-procedures)

## Service Issues

### Service Won't Start

**Symptoms:** `sudo systemctl status growmate` shows "failed" or "inactive"

**Diagnosis:**
```bash
sudo systemctl status growmate
sudo journalctl -u growmate -n 50
```

**Common causes:**

1. **Missing dependencies**
   ```bash
   # Reinstall dependencies
   cd /opt/growmate
   sudo pip3 install -r requirements.txt
   ```

2. **Permission issues**
   ```bash
   # Fix permissions
   sudo chown -R root:root /opt/growmate
   sudo chmod -R 755 /opt/growmate
   sudo chmod 755 /etc/growmate
   ```

3. **Invalid configuration**
   ```bash
   # Check config syntax
   python3 -c "import yaml; yaml.safe_load(open('/etc/growmate/config.yaml'))"
   
   # Reset to defaults
   sudo rm /etc/growmate/config.yaml
   sudo systemctl restart growmate
   ```

4. **Python path issues**
   ```bash
   # Verify Python version
   python3 --version  # Should be 3.9+
   
   # Check if modules load
    python3 -c "import adafruit_ads1x15"
   ```

### Service Crashes Repeatedly

**Symptoms:** Service starts but crashes within seconds/minutes

**Diagnosis:**
```bash
# Watch logs in real-time
sudo journalctl -u growmate -f

# Check for segfaults
sudo journalctl -k | grep segfault
```

**Solutions:**

1. **Hardware not connected**
   - Service expects hardware to be present
   - Run hardware test: `sudo python3 /opt/growmate/scripts/test_hardware.py`
   - Check all connections

2. **Memory issues**
   ```bash
   # Check available memory
   free -h
   
   # Reduce camera resolution in config.yaml
   camera:
     width: 1920
     height: 1080
   ```

3. **SD card corruption**
   ```bash
   # Check filesystem
   sudo fsck -f /dev/mmcblk0p2
   
   # Check SD card health
   sudo badblocks -v /dev/mmcblk0
   ```

### Service Runs But Does Nothing

**Symptoms:** Service is active but no sensor readings or uploads

**Diagnosis:**
```bash
# Check if jobs are scheduled
sudo journalctl -u growmate | grep "Scheduled job"

# Check for errors
sudo journalctl -u growmate | grep -i error
```

**Solutions:**

1. **Not provisioned**
   - Device may still be in AP mode
   - Check config: `sudo cat /etc/growmate/config.yaml | grep provisioned`
   - Should be `provisioned: true`

2. **Network not connected**
   ```bash
   # Check WiFi status
   nmcli device status
   
   # Check if device can reach internet
   ping -c 3 8.8.8.8
   ```

3. **API endpoints not configured**
   ```bash
   # Verify API URLs in config
   sudo cat /etc/growmate/config.yaml | grep url
   ```

## Hardware Issues

### I2C Device Not Detected

**Symptoms:** `sudo i2cdetect -y 1` doesn't show device at 0x48

**Solutions:**

1. **I2C not enabled**
   ```bash
   # Enable I2C
   sudo raspi-config nonint do_i2c 0
   
   # Load modules
   sudo modprobe i2c-dev
   sudo modprobe i2c-bcm2835
   
   # Make permanent
   echo "i2c-dev" | sudo tee -a /etc/modules
   echo "i2c-bcm2835" | sudo tee -a /etc/modules
   
   # Reboot
   sudo reboot
   ```

2. **Wiring issue**
   - Check SDA connection (GPIO 2, Pin 3)
   - Check SCL connection (GPIO 3, Pin 5)
   - Check VDD connection (3.3V, Pin 1 or 17)
   - Check GND connection (Pin 6, 9, 14, 20, 25, 30, 34, or 39)
   - Verify no loose connections

3. **Wrong I2C bus**
   ```bash
   # Try bus 0 instead of 1
   sudo i2cdetect -y 0
   ```

4. **Defective ADS1115**
   - Try different I2C address (solder jumpers on module)
   - Test with different ADS1115 module

### Relay Not Switching

**Symptoms:** Relay doesn't click or actuators don't activate

**Solutions:**

1. **Check GPIO output**
   ```bash
   # Test GPIO 17 (pump relay)
   gpio -g mode 17 out
   gpio -g write 17 0  # Should activate relay
   gpio -g write 17 1  # Should deactivate relay
   ```

2. **Insufficient power**
   - Relay module needs 5V power
   - Check VCC connection to Pin 2 or 4 (5V)
   - Verify power supply can provide enough current

3. **Wrong trigger level**
   - Most relay modules are active LOW
   - GPIO LOW (0) = relay ON
   - GPIO HIGH (1) = relay OFF
   - Check relay module documentation

4. **Defective relay**
   - Listen for click sound when switching
   - Measure continuity across NO/COM contacts
   - Replace relay module if defective

### DHT22 Not Reading

**Symptoms:** Temperature/humidity readings fail or show errors

**Solutions:**

1. **Missing pull-up resistor**
   - DHT22 requires 10kΩ resistor between VCC and Data
   - Without it, readings will be unreliable
   - Add resistor between Pin 1 (3.3V) and Pin 7 (GPIO 4)

2. **Timing issues**
   - DHT22 is slow (2-second minimum between reads)
   - Service already implements retry logic
   - If still failing, sensor may be defective

3. **Power issues**
   - DHT22 needs stable 3.3V power
   - Check voltage at sensor VCC pin
   - Should be 3.2-3.4V

4. **Wiring**
   - Verify Data pin connected to GPIO 4 (Pin 7)
   - Check VCC connected to 3.3V (Pin 1 or 17)
   - Check GND connected to ground

## Network Issues

### Can't Connect to AP Mode

**Symptoms:** GrowMate-XXXXXX network not visible

**Solutions:**

1. **Check if in AP mode**
   ```bash
   # Check logs
   sudo journalctl -u growmate | grep "AP mode"
   
   # Force AP mode
   sudo rm /etc/growmate/config.yaml
   sudo systemctl restart growmate
   ```

2. **hostapd not running**
   ```bash
   # Check hostapd status
   sudo systemctl status hostapd
   
   # Restart service
   sudo systemctl restart growmate
   ```

3. **WiFi adapter busy**
   ```bash
   # Check if connected to network
   nmcli device status
   
   # Disconnect from network
   nmcli device disconnect wlan0
   sudo systemctl restart growmate
   ```

### Can't Connect to WiFi

**Symptoms:** Device stays in AP mode, won't connect to home network

**Solutions:**

1. **Wrong credentials**
   - Re-enter WiFi password through onboarding portal
   - Check for typos in SSID and password
   - SSID is case-sensitive

2. **WiFi signal too weak**
   ```bash
   # Scan for networks
   sudo iwlist wlan0 scan | grep -E "ESSID|Signal"
   
   # Check signal strength (should be > -70 dBm)
   ```

3. **Incompatible WiFi settings**
   - GrowMate supports 2.4GHz only (Pi Zero W limitation)
   - Check router is broadcasting 2.4GHz network
   - Try disabling 5GHz if dual-band router

4. **Network configuration issues**
   ```bash
   # Reset network settings
   sudo nmcli connection delete "GrowMate WiFi"
   sudo rm /etc/growmate/config.yaml
   sudo systemctl restart growmate
   ```

### Internet Connection Issues

**Symptoms:** Connected to WiFi but can't reach API

**Solutions:**

1. **Check connectivity**
   ```bash
   # Test DNS resolution
   nslookup google.com
   
   # Test internet connectivity
   ping -c 3 8.8.8.8
   
   # Test HTTPS connectivity
   curl -I https://google.com
   ```

2. **Firewall blocking**
   - Check if router firewall blocks outbound HTTPS
   - Try accessing API from another device on same network
   - Check API server firewall rules

3. **DNS issues**
   ```bash
   # Try different DNS server
   echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
   ```

## Sensor Issues

### Sensor Readings Are Wrong

**Symptoms:** Values don't match reality (e.g., dry soil shows 100%)

**Solution:** Calibrate sensors

```bash
# Run hardware test to see raw values
sudo python3 /opt/growmate/scripts/test_hardware.py

# Note the raw ADC values for dry and wet conditions
# Update config.yaml:
calibration:
  soil_moisture: {min: 12000, max: 52000}  # Example values
  light: {min: 1000, max: 60000}
  water_level: {min: 5000, max: 55000}

# Restart service
sudo systemctl restart growmate
```

**Calibration procedure:**

1. **Soil moisture:**
   - Dry: Remove sensor from soil, note raw value
   - Wet: Submerge in water, note raw value

2. **Light:**
   - Dark: Cover sensor completely, note raw value
   - Bright: Expose to bright light, note raw value

3. **Water level:**
   - Empty: Remove from water, note raw value
   - Full: Fully submerge, note raw value

### Sensor Readings Fluctuate Wildly

**Symptoms:** Values jump around erratically

**Solutions:**

1. **Electrical noise**
   - Keep sensor wires away from power cables
   - Use shielded cables for long runs
   - Add 0.1µF capacitor across sensor power pins

2. **Poor connections**
   - Check all wire connections are secure
   - Clean oxidized contacts
   - Solder connections instead of using jumpers

3. **Power supply noise**
   - Use quality power supply
   - Add 1000µF capacitor near Pi power input
   - Use separate power supply for Pi and actuators

### Sensor Stops Working

**Symptoms:** Sensor was working, now returns errors

**Solutions:**

1. **Corrosion**
   - Inspect sensor for corrosion
   - Clean with isopropyl alcohol
   - Replace if heavily corroded

2. **Water damage**
   - Check for moisture in connections
   - Dry thoroughly before reconnecting
   - Use waterproof connectors

3. **Sensor failure**
   - Test sensor with multimeter
   - Replace if defective

## Camera Issues

### Camera Not Detected

**Symptoms:** `libcamera-hello` fails or camera test fails

**Solutions:**

1. **Camera not enabled**
   ```bash
   # Enable camera interface
   sudo raspi-config nonint do_camera 0
   sudo reboot
   ```

2. **Ribbon cable not connected**
   - Power off Pi
   - Check ribbon cable is fully inserted
   - Contacts should face away from USB ports
   - Latch should be closed firmly

3. **Defective camera**
   - Try different camera module
   - Check for physical damage

### Camera Images Are Black

**Symptoms:** Camera captures but images are all black

**Solutions:**

1. **Lens cap still on**
   - Remove protective film from lens

2. **Insufficient light**
   - Camera needs some light to function
   - Check environment lighting

3. **Wrong camera settings**
   - Check exposure settings in code
   - May need to adjust for low-light conditions

### Camera Captures Fail

**Symptoms:** Camera errors during capture

**Solutions:**

1. **Insufficient memory**
   ```bash
   # Check available memory
   free -h
   
   # Reduce camera resolution in config.yaml
   ```

2. **GPU memory too low**
   ```bash
   # Increase GPU memory
   sudo raspi-config
   # Navigate to: Performance Options -> GPU Memory
   # Set to 128MB or higher
   sudo reboot
   ```

## API Issues

### Upload Failures

**Symptoms:** Logs show "Upload failed" or HTTP errors

**Diagnosis:**
```bash
# Check API connectivity
curl -X POST https://your-api.com/sensors \
  -H "Content-Type: application/json" \
  -d '{"test": true}'

# Check logs for error codes
sudo journalctl -u growmate | grep "HTTP"
```

**Solutions by error code:**

- **HTTP 400 (Bad Request):** Invalid JSON format, check API documentation
- **HTTP 401 (Unauthorized):** Authentication required, add API key to config
- **HTTP 403 (Forbidden):** API key invalid or expired
- **HTTP 404 (Not Found):** Wrong API endpoint URL
- **HTTP 500 (Server Error):** API server issue, check server logs
- **HTTP 503 (Service Unavailable):** API server down, wait and retry

### Queue Filling Up

**Symptoms:** Logs show increasing queue depth, disk space decreasing

**Diagnosis:**
```bash
# Check queue depth
sudo journalctl -u growmate | grep queue_depth

# Check database size
ls -lh /etc/growmate/queue.db
```

**Solutions:**

1. **API server down**
   - Fix API server
   - Queue will drain automatically when server returns

2. **Network issues**
   - Fix network connectivity
   - Queue will drain when network returns

3. **Queue full**
   ```bash
   # Clear old entries manually
   sqlite3 /etc/growmate/queue.db "DELETE FROM sensor_data WHERE created_at < datetime('now', '-2 days');"
   sqlite3 /etc/growmate/queue.db "DELETE FROM images WHERE created_at < datetime('now', '-2 days');"
   sqlite3 /etc/growmate/queue.db "VACUUM;"
   ```

## Performance Issues

### High CPU Usage

**Diagnosis:**
```bash
# Check CPU usage
top -b -n 1 | grep growmate

# Monitor in real-time
sudo python3 /opt/growmate/scripts/monitor_performance.py --continuous
```

**Solutions:**

1. **Camera resolution too high**
   - Reduce resolution in config.yaml
   - 1920x1080 is usually sufficient

2. **Resolution too high or framerate too high**
   - Reduce width/height or framerate in `camera.*` config

3. **Excessive logging**
   - Reduce log level in config.yaml
   - Change from DEBUG to INFO or WARNING

### High Memory Usage

**Diagnosis:**
```bash
# Check memory usage
free -h
ps aux | grep python
```

**Solutions:**

1. **Memory leak**
   - Restart service: `sudo systemctl restart growmate`
   - Update to latest version

2. **Large queue**
   - Clear old queue entries (see Queue Filling Up)

### SD Card Wearing Out

**Symptoms:** Filesystem errors, read-only filesystem

**Prevention:**
```bash
# Reduce writes by using log rotation
sudo nano /etc/systemd/journald.conf
# Set: SystemMaxUse=100M

# Move queue to RAM disk (loses data on reboot)
# Not recommended for production
```

**Recovery:**
```bash
# Backup data
sudo cp -r /etc/growmate /home/grow/growmate-backup

# Check filesystem
sudo fsck -f /dev/mmcblk0p2

# Replace SD card if errors persist
```

## Log Analysis

### Understanding Log Levels

- **DEBUG:** Detailed information for debugging
- **INFO:** Normal operation messages
- **WARNING:** Something unexpected but not critical
- **ERROR:** Operation failed but service continues
- **CRITICAL:** Severe error, service may stop

### Common Log Messages

**Normal operation:**
```
INFO: Sensor reading completed: soil=45%, light=78%, temp=25C
INFO: Camera capture successful
INFO: Upload successful: sensor_data
```

**Warnings:**
```
WARNING: DHT22 read failed, retrying...
WARNING: Upload retry 2/5
WARNING: Queue depth: 150 entries
```

**Errors:**
```
ERROR: Failed to read from ADS1115
ERROR: Camera capture failed: insufficient memory
ERROR: Upload failed: HTTP 500
```

### Useful Log Commands

```bash
# View live logs
sudo journalctl -u growmate -f

# View last 100 lines
sudo journalctl -u growmate -n 100

# View logs from today
sudo journalctl -u growmate --since today

# View errors only
sudo journalctl -u growmate -p err

# Search for specific text
sudo journalctl -u growmate | grep "sensor"

# Export logs to file
sudo journalctl -u growmate > /tmp/growmate.log
```

## Recovery Procedures

### Factory Reset

**Warning:** This deletes all configuration and queue data

```bash
# Stop service
sudo systemctl stop growmate

# Remove configuration and queue
sudo rm -rf /etc/growmate/*

# Restart service (will enter onboarding mode)
sudo systemctl start growmate
```

### Reinstall Software

```bash
# Stop service
sudo systemctl stop growmate

# Backup configuration
sudo cp /etc/growmate/config.yaml /tmp/config.yaml.backup

# Remove installation
sudo rm -rf /opt/growmate

# Reinstall
cd ~/rpi-growmate-pods
sudo bash scripts/install.sh

# Restore configuration
sudo cp /tmp/config.yaml.backup /etc/growmate/config.yaml

# Start service
sudo systemctl start growmate
```

### Recover from Corrupted SD Card

1. **Backup what you can:**
   ```bash
   # Mount SD card on another computer
   # Copy /etc/growmate/config.yaml
   ```

2. **Flash new SD card:**
   - Use Raspberry Pi Imager
   - Flash Raspberry Pi OS Lite

3. **Reinstall GrowMate:**
   ```bash
   curl -sSL https://raw.githubusercontent.com/FarelRA/rpi-growmate-pods/main/scripts/install.sh | sudo bash
   ```

4. **Restore configuration:**
   - Copy backed up config.yaml to /etc/growmate/
   - Or reconfigure through onboarding portal

## Getting Help

If you can't resolve your issue:

1. **Collect diagnostic information:**
   ```bash
   # System info
   uname -a
   cat /etc/os-release
   
   # Service status
   sudo systemctl status growmate
   
   # Recent logs
   sudo journalctl -u growmate -n 200 > /tmp/growmate-logs.txt
   
   # Hardware test
   sudo python3 /opt/growmate/scripts/test_hardware.py > /tmp/hardware-test.txt
   ```

2. **Open GitHub issue:**
   - Include diagnostic information
   - Describe what you tried
   - Include error messages

3. **Check documentation:**
   - [HARDWARE.md](HARDWARE.md) - Hardware setup
   - [CONFIGURATION.md](CONFIGURATION.md) - Configuration options
   - [API.md](API.md) - API integration
   - [WIRING.md](WIRING.md) - Wiring details
   - [device-v2-notes.md](device-v2-notes.md) - V2 device setup

---

## V2-Specific Troubleshooting

Issues specific to the V2 device agent on Raspberry Pi Zero W.

### V2 Camera: rpicam-vid

**Symptom: No camera feed**

```bash
# Check if rpicam-vid is running
ps aux | grep rpicam-vid

# Install if missing
sudo apt install rpicam-apps

# Test camera directly
rpicam-hello --timeout 5000
```

**Symptom: Camera hangs after ~30 seconds**

GPU memory too low — increase in `/boot/firmware/config.txt`:
```ini
gpu_mem=256
```

Reboot after change.

**Symptom: Stream is slow or jerky**

WiFi bandwidth insufficient. Reduce bitrate:
```bash
# In start.sh, change --bitrate to 500000 (500 Kbps)
rpicam-vid ... --bitrate 500000 ...
```

### V2 Tailscale Issues

**Symptom: Tailscale not connecting**

```bash
# Check status
tailscale status

# Restart Tailscale
sudo tailscale down
sudo tailscale up  # Re-authenticate

# Update Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
```

**Symptom: Stream registration fails**

```bash
# Check Tailscale IP
tailscale ip -4

# Verify rpicam-vid is listening
ss -tlnp | grep 8554

# Test registration manually
curl -X POST https://growmate.bond/api/v2/stream/register \
  -H "x-api-key: $DEVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"deviceId":"'"$DEVICE_ID"'","streamUrl":"tcp://'"$(tailscale ip -4)"':8554"}'
```

### V2 Sensor Issues

**Symptom: Sensor readings all zero**

```bash
# Check ADS1115 on I2C bus
sudo i2cdetect -y 1
# Should show 0x48

# If empty, check wiring:
# - SDA → GPIO 2 (Pin 3)
# - SCL → GPIO 3 (Pin 5)
# - VDD → 3.3V (Pin 1 or 17)
# - GND → GND
```

**Symptom: Battery current always 0**

```bash
# Check ACS712 output at 0A (should be ~2.5V = Vcc/2)
# Verify wiring:
# - ACS712 VCC → 5V
# - ACS712 OUT → ADS1115 ch0
# - ACS712 GND → GND
# - ACS712 IP+ → Battery (+)
# - ACS712 IP- → Load/charger (-)
```

**Symptom: Limit switch always reads HIGH**

Missing pull-up resistor or wrong GPIO mode:
```python
# Must use internal pull-up
GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
```

### V2 Relay Issues

**Symptom: Relay not triggering**

Verify V2 GPIO assignments (different from V1):
```bash
# V2 pinout:
# GPIO 17 → Relay 1 (fertilizer valve)
# GPIO 27 → Relay 2 (pesticide valve)
# GPIO 10 → Relay 4 (pump)

# Test relay manually
gpio -g mode 17 out
gpio -g write 17 1  # Should activate relay
gpio -g write 17 0  # Should deactivate
```

### V2 Service Issues

**Symptom: growmate.service fails to start**

```bash
# Check service status
sudo systemctl status growmate

# View logs
sudo journalctl -u growmate -n 50

# Common causes:
# 1. Tailscale not connected — check 'tailscale status'
# 2. DEVICE_API_KEY or DEVICE_ID not set in service file
# 3. start.sh not executable: chmod +x /home/grow/growmate/*.sh

# Verify environment variables in service
sudo systemctl cat growmate
```

**Symptom: Service starts but main.py exits immediately**

```bash
# Run main.py manually to see errors
sudo -u grow DEVICE_API_KEY=test DEVICE_ID=test python3 /home/grow/growmate/main.py

# Check for missing Python packages
pip3 list | grep -E "ads1x15|circuitpython-dht|RPi.GPIO"
```
