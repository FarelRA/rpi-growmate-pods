# GrowMate Troubleshooting Guide

This guide covers common issues and their solutions for the GrowMate Raspberry Pi system.

## Table of Contents

- [Service Issues](#service-issues)
- [Hardware Issues](#hardware-issues)
- [Network Issues](#network-issues)
- [API and Upload Issues](#api-and-upload-issues)
- [Performance Issues](#performance-issues)
- [Log Analysis](#log-analysis)

---

## Service Issues

### Service Won't Start

**Symptoms:** `systemctl status growmate` shows failed or inactive

**Diagnosis:**
```bash
sudo systemctl status growmate
sudo journalctl -u growmate -n 100 --no-pager
```

**Common Causes:**
1. **Missing dependencies**
   ```bash
   sudo pip3 install -r /opt/growmate/requirements.txt
   ```

2. **I2C not enabled**
   ```bash
   sudo raspi-config nonint do_i2c 0
   sudo reboot
   ```

3. **Camera not enabled**
   ```bash
   sudo raspi-config nonint do_camera 0
   sudo reboot
   ```

4. **Configuration file missing or invalid**
   ```bash
   # Check if config exists
   ls -la /etc/growmate/config.yaml
   
   # Validate YAML syntax
   python3 -c "import yaml; yaml.safe_load(open('/etc/growmate/config.yaml'))"
   ```

5. **Permission issues**
   ```bash
   sudo chown -R root:root /opt/growmate
   sudo chmod -R 755 /opt/growmate
   ```

### Service Crashes Repeatedly

**Symptoms:** Service restarts every 10 seconds

**Diagnosis:**
```bash
sudo journalctl -u growmate -f
```

**Common Causes:**
1. **Hardware not connected** - Check I2C devices, camera, sensors
2. **Import errors** - Missing Python dependencies
3. **Configuration errors** - Invalid YAML or missing required fields

**Solution:**
```bash
# Test hardware
sudo python3 /opt/growmate/scripts/test_hardware.py

# Check for Python errors
sudo python3 /opt/growmate/src/main.py
```

---

## Hardware Issues

### I2C Device Not Detected

**Symptoms:** `i2cdetect` doesn't show device at 0x48

**Diagnosis:**
```bash
sudo i2cdetect -y 1
```

**Solutions:**
1. **Check wiring** - Verify SDA (GPIO 2), SCL (GPIO 3), VCC, GND
2. **Check I2C is enabled**
   ```bash
   lsmod | grep i2c
   # Should show i2c_dev and i2c_bcm2835
   ```
3. **Load I2C modules**
   ```bash
   sudo modprobe i2c-dev
   sudo modprobe i2c-bcm2835
   ```
4. **Check for conflicts** - Only one device should use address 0x48

### Sensors Return Invalid Values

**Symptoms:** Sensor readings are 0, -1, or nonsensical

**Diagnosis:**
```bash
sudo python3 /opt/growmate/scripts/test_hardware.py
```

**Solutions:**
1. **Check sensor connections** - Verify power and signal wires
2. **Check calibration** - Update min/max values in config.yaml
3. **DHT22 specific** - Requires 10kΩ pull-up resistor between DATA and VCC
4. **ADC specific** - Check ADS1115 channel connections (A0, A1, A2)

### Camera Not Working

**Symptoms:** Camera capture fails or returns errors

**Diagnosis:**
```bash
# Test camera directly
libcamera-hello --timeout 2000

# Check camera is detected
vcgencmd get_camera
# Should show: supported=1 detected=1
```

**Solutions:**
1. **Enable camera interface**
   ```bash
   sudo raspi-config
   # Interface Options -> Camera -> Enable
   sudo reboot
   ```
2. **Check cable connection** - Ensure ribbon cable is fully inserted
3. **Check camera module** - Try different camera if available
4. **Update firmware**
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo rpi-update
   sudo reboot
   ```

### GPIO Relays Not Switching

**Symptoms:** Pump or light commands don't activate relays

**Diagnosis:**
```bash
# Test GPIO manually
python3 << EOF
from gpiozero import OutputDevice
pump = OutputDevice(17)
pump.on()
# Check if relay clicks
pump.off()
EOF
```

**Solutions:**
1. **Check wiring** - Verify GPIO 17 (pump), GPIO 27 (light)
2. **Check relay power** - Relays need 5V power supply
3. **Check relay type** - Active high vs active low
4. **Check GPIO permissions** - Service runs as root

---

## Network Issues

### Can't Connect to AP Mode

**Symptoms:** GrowMate-XXXXXX network not visible

**Diagnosis:**
```bash
# Check if hostapd is running
sudo systemctl status hostapd

# Check if device is in AP mode
nmcli device status
```

**Solutions:**
1. **Check configuration file exists**
   ```bash
   ls -la /etc/growmate/config.yaml
   # If missing or provisioned=false, device should enter AP mode
   ```
2. **Manually trigger AP mode**
   ```bash
   sudo rm /etc/growmate/config.yaml
   sudo systemctl restart growmate
   ```
3. **Check hostapd configuration**
   ```bash
   sudo cat /etc/hostapd/hostapd.conf
   # Should show GrowMate-XXXXXX SSID
   ```
4. **Check for conflicts**
   ```bash
   # Disable NetworkManager if present
   sudo systemctl stop NetworkManager
   sudo systemctl disable NetworkManager
   ```

### Can't Connect to WiFi Network

**Symptoms:** Device stays in AP mode after configuration

**Diagnosis:**
```bash
sudo journalctl -u growmate | grep -i "wifi\|network"
```

**Solutions:**
1. **Check WiFi credentials** - Verify SSID and password in config.yaml
2. **Check WiFi signal** - Move closer to router
3. **Check WiFi band** - Pi Zero W only supports 2.4GHz
4. **Check router settings** - MAC filtering, hidden SSID, etc.
5. **Manual WiFi test**
   ```bash
   sudo nmcli device wifi connect "YourSSID" password "YourPassword"
   ```

### Consecutive Failures Trigger AP Mode

**Symptoms:** Device re-enters AP mode after running normally

**Diagnosis:**
```bash
sudo journalctl -u growmate | grep -i "consecutive\|failure"
```

**Explanation:** After 5 consecutive failures (sensor read, WiFi connect, or upload), device automatically re-enters AP mode for reconfiguration.

**Solutions:**
1. **Check network connectivity** - Ensure stable internet connection
2. **Check API endpoint** - Verify API URL is accessible
3. **Check sensor hardware** - Ensure sensors are connected
4. **Monitor failures**
   ```bash
   sudo journalctl -u growmate -f | grep -i "fail"
   ```

---

## API and Upload Issues

### Sensor Data Upload Fails

**Symptoms:** Logs show upload errors or timeouts

**Diagnosis:**
```bash
sudo journalctl -u growmate | grep -i "upload\|api"
```

**Solutions:**
1. **Check API endpoint**
   ```bash
   curl -X POST https://your-api-url.com/sensors \
     -H "Content-Type: application/json" \
     -d '{"deviceId":"test","sensors":[]}'
   ```
2. **Check internet connectivity**
   ```bash
   ping -c 4 8.8.8.8
   curl -I https://www.google.com
   ```
3. **Check API URL in config**
   ```bash
   grep "sensor_url" /etc/growmate/config.yaml
   ```
4. **Check firewall** - Ensure outbound HTTPS (port 443) is allowed

### Camera Upload Fails

**Symptoms:** Sensor uploads work but camera uploads fail

**Diagnosis:**
```bash
sudo journalctl -u growmate | grep -i "camera"
```

**Solutions:**
1. **Check camera URL** - Verify separate endpoint for camera uploads
2. **Check image size** - Large images may timeout (default 45s timeout)
3. **Check API accepts multipart/form-data**
4. **Test manual upload**
   ```bash
   curl -X POST https://your-api-url.com/camera \
     -H "X-Device-Id: your-device-id" \
     -F "image=@/tmp/test.jpg"
   ```

### API Returns Errors

**Symptoms:** API responds with 4xx or 5xx errors

**Common Error Codes:**
- **400 Bad Request** - Invalid JSON format or missing required fields
- **401 Unauthorized** - Authentication required (not implemented in basic version)
- **404 Not Found** - Incorrect API endpoint URL
- **500 Internal Server Error** - API backend issue
- **503 Service Unavailable** - API temporarily down

**Solutions:**
1. **Check JSON format** - Ensure matches ESP32 API contract
2. **Check device ID** - Verify correct device ID in config
3. **Check API logs** - Review server-side logs for details
4. **Test with curl** - Manually test API endpoints

---

## Performance Issues

### High Memory Usage

**Symptoms:** System becomes slow or unresponsive

**Diagnosis:**
```bash
# Monitor memory usage
free -h

# Monitor GrowMate process
sudo python3 /opt/growmate/scripts/monitor_performance.py --duration 60
```

**Solutions:**
1. **Check for memory leaks** - Monitor over time
2. **Reduce camera resolution** - Edit camera_service.py
3. **Increase swap** - Add swap file if needed
4. **Check for runaway processes**
   ```bash
   top -o %MEM
   ```

### High CPU Usage

**Symptoms:** CPU constantly at 100%

**Diagnosis:**
```bash
top -o %CPU
sudo python3 /opt/growmate/scripts/monitor_performance.py
```

**Solutions:**
1. **Check for infinite loops** - Review logs for repeated errors
2. **Increase intervals** - Reduce sensor/camera frequency in config
3. **Check for blocking operations** - Network timeouts, etc.

### Slow Boot Time

**Symptoms:** Takes >2 minutes to start after boot

**Solutions:**
1. **Check systemd dependencies** - Service waits for network-online.target
2. **Optimize startup** - Disable unnecessary services
3. **Check SD card speed** - Use Class 10 or better

---

## Log Analysis

### Viewing Logs

**Real-time logs:**
```bash
sudo journalctl -u growmate -f
```

**Recent logs:**
```bash
sudo journalctl -u growmate -n 100 --no-pager
```

**Logs since boot:**
```bash
sudo journalctl -u growmate -b
```

**Logs for specific time:**
```bash
sudo journalctl -u growmate --since "2024-01-01 10:00:00"
sudo journalctl -u growmate --since "1 hour ago"
```

**Filter by priority:**
```bash
sudo journalctl -u growmate -p err  # Errors only
sudo journalctl -u growmate -p warning  # Warnings and above
```

### Common Log Messages

**Normal Operation:**
```
INFO: Sensor reading successful
INFO: Camera capture successful
INFO: Upload successful
```

**Warnings:**
```
WARNING: DHT22 read failed, retrying...
WARNING: Upload retry attempt 2/2
WARNING: Camera capture took longer than expected
```

**Errors:**
```
ERROR: Failed to connect to WiFi
ERROR: API upload failed after retries
ERROR: I2C device not found at 0x48
ERROR: Camera initialization failed
```

**Critical:**
```
ERROR: Consecutive failures: 5/5 - Re-entering onboarding mode
```

### Debugging Tips

1. **Enable verbose logging** - Edit main.py to set log level to DEBUG
2. **Check Python tracebacks** - Full stack traces in logs
3. **Test components individually** - Use test_hardware.py
4. **Monitor in real-time** - Use `journalctl -f` while testing
5. **Save logs for analysis**
   ```bash
   sudo journalctl -u growmate > growmate.log
   ```

---

## Getting Help

If you've tried the solutions above and still have issues:

1. **Collect diagnostic information:**
   ```bash
   # System info
   uname -a
   cat /etc/os-release
   
   # Service status
   sudo systemctl status growmate
   
   # Recent logs
   sudo journalctl -u growmate -n 200 > growmate-logs.txt
   
   # Hardware test
   sudo python3 /opt/growmate/scripts/test_hardware.py > hardware-test.txt
   
   # I2C devices
   sudo i2cdetect -y 1 > i2c-devices.txt
   ```

2. **Check documentation:**
   - README.md - Installation and configuration
   - WIRING.md - Hardware wiring guide
   - PLAN.md - Implementation details

3. **Run test suites:**
   ```bash
   python3 scripts/test_e2e.py
   python3 scripts/test_failures.py
   ```

4. **Report issue with:**
   - Raspberry Pi model and OS version
   - GrowMate version (git commit hash)
   - Hardware configuration
   - Log files
   - Steps to reproduce

---

## Quick Reference

**Essential Commands:**
```bash
# Service control
sudo systemctl start|stop|restart|status growmate

# View logs
sudo journalctl -u growmate -f

# Test hardware
sudo python3 /opt/growmate/scripts/test_hardware.py

# Check I2C
sudo i2cdetect -y 1

# Test camera
libcamera-hello

# Re-enter AP mode
sudo rm /etc/growmate/config.yaml && sudo systemctl restart growmate

# Monitor performance
sudo python3 /opt/growmate/scripts/monitor_performance.py
```

**Configuration Files:**
- `/etc/growmate/config.yaml` - Main configuration
- `/etc/systemd/system/growmate.service` - Service definition
- `/opt/growmate/` - Application files

**Log Locations:**
- Systemd journal: `journalctl -u growmate`
- No separate log files (uses systemd journal)
