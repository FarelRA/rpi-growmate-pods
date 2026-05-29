# Configuration Guide

Complete configuration reference for GrowMate Pods.

## Table of Contents

- [Configuration File](#configuration-file)
- [Configuration Options](#configuration-options)
- [Hot-Reload Settings](#hot-reload-settings)
- [Calibration](#calibration)
- [Advanced Features](#advanced-features)
- [Performance Tuning](#performance-tuning)
- [Security](#security)
- [Example Configurations](#example-configurations)

## Configuration File

### Location

`/etc/growmate/config.yaml`

### Format

YAML (YAML Ain't Markup Language) - human-readable data serialization format

### Editing

```bash
# Edit configuration
sudo nano /etc/growmate/config.yaml

# Validate syntax
python3 -c "import yaml; yaml.safe_load(open('/etc/growmate/config.yaml'))"

# Apply changes (hot-reload if supported, otherwise restart)
sudo systemctl restart growmate
```

### Backup

```bash
# Backup current configuration
sudo cp /etc/growmate/config.yaml /etc/growmate/config.yaml.backup

# Restore from backup
sudo cp /etc/growmate/config.yaml.backup /etc/growmate/config.yaml
sudo systemctl restart growmate
```

## Configuration Options

### Complete Reference

```yaml
# Configuration version (do not change)
version: 8

# Device identification
device:
  id: "growmate-b827eb123456"  # Auto-generated from MAC address

# Network settings
network:
  provisioned: true              # false = AP mode, true = client mode
  wifi_ssid: "YourNetwork"       # WiFi network name
  wifi_password: "YourPassword"  # WiFi password
  ap_ssid: "GrowMate"           # AP mode SSID prefix (optional)
  ap_password: "growmate"        # AP mode password (optional)
  ap_channel: 6                  # AP mode WiFi channel (optional)

# API endpoints
api:
  sensor_url: "https://api.example.com/sensors"  # Sensor data endpoint
  camera_url: "https://api.example.com/camera"   # Camera image endpoint
  timeout: 30                                     # Request timeout (seconds)

# Timing intervals
intervals:
  sensor_reading: 15      # Sensor reading interval (seconds)
  camera_capture: 900     # Camera capture interval (seconds, 15 min)
  failure_check: 30       # Failure monitoring interval (seconds)
  queue_cleanup: 3600     # Queue cleanup interval (seconds, 1 hour)
  queue_vacuum: 604800    # Database vacuum interval (seconds, 7 days)
  health_check: 300       # Health monitoring interval (seconds, 5 min)

# Camera settings
camera:
  width: 2592             # Image width (pixels)
  height: 1944            # Image height (pixels)
  quality: 85             # JPEG quality (50-100)
  add_exif: true          # Embed sensor data in EXIF metadata
  format: "jpeg"          # Image format (jpeg only currently)

# Offline queue settings
queue:
  enabled: true           # Enable offline queue
  database_path: "/etc/growmate/queue.db"  # SQLite database path
  max_age_hours: 24       # Delete entries older than this (hours)
  max_sensor_entries: 6000  # Maximum sensor data entries
  max_image_entries: 100    # Maximum image entries
  cleanup_interval: 3600    # Cleanup job interval (seconds)
  max_retries: 5            # Maximum upload retry attempts

# Retry configuration
retry:
  max_attempts: 6         # Maximum retry attempts
  initial_delay: 1.0      # Initial delay (seconds)
  max_delay: 32.0         # Maximum delay (seconds)
  backoff_factor: 2.0     # Exponential backoff multiplier
  jitter: 0.25            # Random jitter (±25%)

# Circuit breaker configuration
circuit_breaker:
  failure_threshold: 5    # Open circuit after N failures
  recovery_timeout: 60    # Time in OPEN state (seconds)
  success_threshold: 2    # Close circuit after N successes
  half_open_max_calls: 1  # Max calls in HALF_OPEN state

# Sensor calibration
calibration:
  soil_moisture:
    min: 0                # Raw ADC value for dry soil
    max: 65535            # Raw ADC value for wet soil
  light:
    min: 0                # Raw ADC value for darkness
    max: 65535            # Raw ADC value for bright light
  water_level:
    min: 0                # Raw ADC value for empty
    max: 65535            # Raw ADC value for full

# Sensor configuration
sensors:
  enable_dht22: true      # Enable DHT22 temperature/humidity sensor
  dht22_retries: 2        # DHT22 read retry attempts
  adc_gain: 1             # ADS1115 gain (1, 2, 4, 8, 16)
  adc_samples: 3          # Number of samples to average

# Hardware pin assignments
hardware:
  dht22_pin: 4            # GPIO pin for DHT22 data
  pump_relay_pin: 17      # GPIO pin for pump relay
  light_relay_pin: 27     # GPIO pin for light relay
  i2c_bus: 1              # I2C bus number (usually 1)
  ads1115_address: 0x48   # ADS1115 I2C address

# Logging configuration
logging:
  level: "INFO"           # Global log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  format: "json"          # Log format (json or text)
  modules:                # Per-module log levels
    growmate.sensors: "INFO"
    growmate.camera: "INFO"
    growmate.api: "INFO"
    growmate.network: "INFO"
    growmate.queue: "INFO"

# Feature flags
features:
  hot_reload: true        # Enable configuration hot-reload
  health_monitoring: true # Enable health monitoring
  performance_metrics: false  # Enable performance metrics collection
```

## Hot-Reload Settings

Some settings can be changed without restarting the service. Changes are detected automatically within seconds.

### Hot-Reloadable Settings

**Intervals:**
- `intervals.sensor_reading`
- `intervals.camera_capture`
- `intervals.failure_check`
- `intervals.queue_cleanup`
- `intervals.health_check`

**Camera:**
- `camera.quality`
- `camera.add_exif`

**Queue:**
- `queue.max_retries`
- `queue.cleanup_interval`

**Retry:**
- `retry.max_attempts`
- `retry.initial_delay`
- `retry.max_delay`
- `retry.backoff_factor`
- `retry.jitter`

**Circuit Breaker:**
- `circuit_breaker.failure_threshold`
- `circuit_breaker.recovery_timeout`
- `circuit_breaker.success_threshold`

**Logging:**
- `logging.level`
- `logging.modules.*`

**Features:**
- `features.health_monitoring`
- `features.performance_metrics`

### Restart Required

These settings require service restart:

**Device:**
- `device.id`

**Network:**
- `network.wifi_ssid`
- `network.wifi_password`
- `network.ap_ssid`
- `network.ap_password`

**API:**
- `api.sensor_url`
- `api.camera_url`

**Camera:**
- `camera.width`
- `camera.height`

**Hardware:**
- All `hardware.*` settings

**Queue:**
- `queue.database_path`

## Calibration

### Why Calibrate?

Analog sensors output raw voltage values (0-3.3V) converted to 16-bit integers (0-65535) by the ADC. Calibration maps these raw values to meaningful percentages (0-100%).

### Calibration Process

1. **Read raw values:**
   ```bash
   sudo python3 /opt/growmate/scripts/test_hardware.py
   ```

2. **Note minimum and maximum values:**
   - **Soil moisture:**
     - Min: Sensor completely dry (in air)
     - Max: Sensor fully submerged in water
   - **Light:**
     - Min: Sensor completely covered (darkness)
     - Max: Sensor in bright light
   - **Water level:**
     - Min: Sensor out of water (empty)
     - Max: Sensor fully submerged (full)

3. **Update configuration:**
   ```yaml
   calibration:
     soil_moisture:
       min: 12000    # Example: dry reading
       max: 52000    # Example: wet reading
     light:
       min: 1000     # Example: dark reading
       max: 60000    # Example: bright reading
     water_level:
       min: 5000     # Example: empty reading
       max: 55000    # Example: full reading
   ```

4. **Restart service:**
   ```bash
   sudo systemctl restart growmate
   ```

### Calibration Tips

- **Stable conditions:** Calibrate in stable conditions (no wind, consistent temperature)
- **Multiple readings:** Take several readings and use average
- **Full range:** Use full range of sensor (completely dry to completely wet)
- **Recalibrate:** Recalibrate every 3-6 months as sensors age
- **Document:** Keep notes of calibration values and conditions

### Verification

After calibration, verify readings make sense:

```bash
# Watch live sensor readings
sudo journalctl -u growmate -f | grep "Sensor reading"
```

Expected ranges:
- Soil moisture: 0% (dry) to 100% (saturated)
- Light: 0% (dark) to 100% (bright)
- Water level: 0% (empty) to 100% (full)

## Advanced Features

### Custom Intervals

Adjust intervals based on your needs:

**Fast monitoring (high power consumption):**
```yaml
intervals:
  sensor_reading: 5       # Every 5 seconds
  camera_capture: 300     # Every 5 minutes
```

**Slow monitoring (low power consumption):**
```yaml
intervals:
  sensor_reading: 60      # Every minute
  camera_capture: 3600    # Every hour
```

**Balanced (recommended):**
```yaml
intervals:
  sensor_reading: 15      # Every 15 seconds
  camera_capture: 900     # Every 15 minutes
```

### ADC Configuration

Adjust ADC settings for different sensor types:

**Gain settings:**
```yaml
sensors:
  adc_gain: 1   # ±4.096V (default, most sensors)
  # adc_gain: 2   # ±2.048V (more sensitive)
  # adc_gain: 4   # ±1.024V (very sensitive)
  # adc_gain: 8   # ±0.512V (extremely sensitive)
  # adc_gain: 16  # ±0.256V (maximum sensitivity)
```

Higher gain = more sensitivity but smaller voltage range.

**Sampling:**
```yaml
sensors:
  adc_samples: 3  # Average 3 readings (reduces noise)
```

More samples = more stable readings but slower.

### Queue Management

Adjust queue size based on expected downtime:

**Short downtime (1-2 hours):**
```yaml
queue:
  max_sensor_entries: 500   # ~2 hours at 15s intervals
  max_image_entries: 10     # ~2.5 hours at 15m intervals
```

**Long downtime (24 hours, default):**
```yaml
queue:
  max_sensor_entries: 6000  # ~24 hours at 15s intervals
  max_image_entries: 100    # ~25 hours at 15m intervals
```

**Extended downtime (7 days):**
```yaml
queue:
  max_sensor_entries: 40000  # ~7 days at 15s intervals
  max_image_entries: 700     # ~7 days at 15m intervals
```

**Note:** Larger queues use more disk space (~150MB per day).

### Retry Tuning

Adjust retry behavior for different network conditions:

**Fast, reliable network:**
```yaml
retry:
  max_attempts: 3
  initial_delay: 0.5
  max_delay: 8.0
```

**Slow or unreliable network:**
```yaml
retry:
  max_attempts: 10
  initial_delay: 2.0
  max_delay: 60.0
```

**Balanced (default):**
```yaml
retry:
  max_attempts: 6
  initial_delay: 1.0
  max_delay: 32.0
```

## Performance Tuning

### Low Power Mode

Minimize power consumption:

```yaml
intervals:
  sensor_reading: 60      # Read every minute
  camera_capture: 3600    # Capture every hour

camera:
  width: 1920             # Lower resolution
  height: 1080
  quality: 70             # Lower quality

logging:
  level: "WARNING"        # Less logging
```

### High Performance Mode

Maximum responsiveness:

```yaml
intervals:
  sensor_reading: 5       # Read every 5 seconds
  camera_capture: 300     # Capture every 5 minutes

camera:
  width: 2592             # Full resolution
  height: 1944
  quality: 95             # High quality

retry:
  max_attempts: 3         # Fail fast
  initial_delay: 0.5
  max_delay: 4.0

logging:
  level: "DEBUG"          # Detailed logging
```

### Balanced Mode (Recommended)

Good balance of performance and power:

```yaml
intervals:
  sensor_reading: 15      # Read every 15 seconds
  camera_capture: 900     # Capture every 15 minutes

camera:
  width: 2592             # Full resolution
  height: 1944
  quality: 85             # Good quality

retry:
  max_attempts: 6
  initial_delay: 1.0
  max_delay: 32.0

logging:
  level: "INFO"
```

## Security

### Network Security

1. **Use HTTPS:** Always use HTTPS for API endpoints
   ```yaml
   api:
     sensor_url: "https://api.example.com/sensors"  # ✓ Secure
     # sensor_url: "http://api.example.com/sensors"  # ✗ Insecure
   ```

2. **Strong WiFi password:**
   ```yaml
   network:
     wifi_password: "MyStr0ng!P@ssw0rd"  # ✓ Strong
     # wifi_password: "password"          # ✗ Weak
   ```

3. **Change AP password:**
   ```yaml
   network:
     ap_password: "MyCustomPassword123"  # ✓ Custom
     # ap_password: "growmate"            # ✗ Default
   ```

### File Permissions

Protect configuration file:

```bash
# Restrict access to root only
sudo chmod 600 /etc/growmate/config.yaml
sudo chown root:root /etc/growmate/config.yaml
```

### API Authentication

If your API requires authentication, you can add custom headers (requires code modification):

```python
# In src/api_client.py, add headers:
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {api_key}',
    'X-API-Key': api_key
}
```

## Example Configurations

### Home Garden

```yaml
version: 8
device:
  id: "growmate-home001"
network:
  provisioned: true
  wifi_ssid: "HomeNetwork"
  wifi_password: "MyHomePassword"
api:
  sensor_url: "https://mygarden.example.com/api/sensors"
  camera_url: "https://mygarden.example.com/api/camera"
intervals:
  sensor_reading: 30      # Every 30 seconds
  camera_capture: 1800    # Every 30 minutes
camera:
  width: 1920
  height: 1080
  quality: 80
calibration:
  soil_moisture: {min: 15000, max: 50000}
  light: {min: 2000, max: 58000}
  water_level: {min: 8000, max: 52000}
```

### Commercial Greenhouse

```yaml
version: 8
device:
  id: "growmate-greenhouse-a1"
network:
  provisioned: true
  wifi_ssid: "GreenhouseWiFi"
  wifi_password: "SecurePassword123"
api:
  sensor_url: "https://greenhouse-api.company.com/v1/sensors"
  camera_url: "https://greenhouse-api.company.com/v1/images"
  timeout: 60
intervals:
  sensor_reading: 10      # Every 10 seconds
  camera_capture: 600     # Every 10 minutes
camera:
  width: 2592
  height: 1944
  quality: 90
queue:
  max_sensor_entries: 10000
  max_image_entries: 200
logging:
  level: "INFO"
  modules:
    growmate.sensors: "DEBUG"
```

### Research Lab

```yaml
version: 8
device:
  id: "growmate-lab-exp42"
network:
  provisioned: true
  wifi_ssid: "LabNetwork"
  wifi_password: "LabPassword"
api:
  sensor_url: "https://lab-data.university.edu/api/v2/sensors"
  camera_url: "https://lab-data.university.edu/api/v2/images"
intervals:
  sensor_reading: 5       # Every 5 seconds (high frequency)
  camera_capture: 300     # Every 5 minutes
camera:
  width: 2592
  height: 1944
  quality: 95             # High quality for analysis
sensors:
  adc_samples: 5          # More samples for accuracy
logging:
  level: "DEBUG"          # Detailed logging for research
features:
  performance_metrics: true
```

### Low Power Remote

```yaml
version: 8
device:
  id: "growmate-remote01"
network:
  provisioned: true
  wifi_ssid: "RemoteSite"
  wifi_password: "RemotePassword"
api:
  sensor_url: "https://remote-api.example.com/sensors"
  camera_url: "https://remote-api.example.com/camera"
intervals:
  sensor_reading: 120     # Every 2 minutes (low power)
  camera_capture: 7200    # Every 2 hours
camera:
  width: 1920
  height: 1080
  quality: 70             # Lower quality to save bandwidth
queue:
  max_sensor_entries: 2000
  max_image_entries: 50
logging:
  level: "WARNING"        # Minimal logging
```

## Troubleshooting Configuration

### Configuration Won't Load

```bash
# Check syntax
python3 -c "import yaml; yaml.safe_load(open('/etc/growmate/config.yaml'))"

# Check for tabs (YAML doesn't allow tabs)
cat -A /etc/growmate/config.yaml | grep "^I"

# Validate indentation (must be consistent)
```

### Changes Not Applied

```bash
# Check if hot-reload is enabled
grep "hot_reload" /etc/growmate/config.yaml

# Force restart
sudo systemctl restart growmate

# Watch logs for reload confirmation
sudo journalctl -u growmate -f | grep "reload"
```

### Invalid Values

Check logs for validation errors:

```bash
sudo journalctl -u growmate | grep -i "invalid\|error"
```

Common issues:
- Negative values where positive required
- Values outside valid range (e.g., quality > 100)
- Wrong data types (string instead of number)
- Missing required fields

## Support

For hardware setup, see [HARDWARE.md](HARDWARE.md)

For troubleshooting, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

For API details, see [API.md](API.md)
