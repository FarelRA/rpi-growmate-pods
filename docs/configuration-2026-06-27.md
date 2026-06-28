# Configuration Guide

Complete configuration reference for GrowMate Pods (V2).

Everything is configurable — no hardcoded pins, intervals, or thresholds.

## Table of Contents

- [Configuration File](#configuration-file)
- [Complete Reference](#complete-reference)
- [Hot-Reload Settings](#hot-reload-settings)
- [Calibration](#calibration)
- [Tuning Examples](#tuning-examples)
- [Security](#security)
- [Env Var Overrides](#env-var-overrides)

## Configuration File

### Location

The file at `/etc/growmate/config.yaml` is created interactively by `install.sh`.
You can also copy from the example and edit manually:

```bash
sudo cp config/config.yaml.example /etc/growmate/config.yaml
sudo nano /etc/growmate/config.yaml
```

### Validation

```bash
python3 -c "import yaml; yaml.safe_load(open('/etc/growmate/config.yaml'))"
sudo journalctl -u growmate | grep "validation"
```

### Hot-Reload

Most runtime settings reload without restart:

```bash
sudo nano /etc/growmate/config.yaml
# Changes detected within seconds — watch:
sudo journalctl -u growmate -f | grep "reload"
```

For non-reloadable changes (pins, network, queue schema):

```bash
sudo systemctl restart growmate
```

## Complete Reference

```yaml
# ===========================================================================
# version — Schema version (do not change)
# ===========================================================================
version: 9

# ===========================================================================
# device — Identity
# ===========================================================================
device:
  id: "growmate-b827eb123456"   # Auto MAC-derived; override via DEVICE_ID env

# ===========================================================================
# api — Backend endpoints, timeouts
# ===========================================================================
api:
  sensor_url: "https://growmate.bond/api/v2/sensors"
  stream_register_url: "https://growmate.bond/api/v2/stream/register"
  timeout_sensor: 30.0           # HTTP timeout for sensor uploads (s)
  timeout_stream_register: 10.0  # HTTP timeout for stream registration (s)

# ===========================================================================
# network — WiFi provisioning (set by onboarding portal)
# ===========================================================================
network:
  provisioned: false             # true → skip AP mode on boot
  wifi_ssid: ""                  # Set by onboarding portal
  wifi_password: ""              # Set by onboarding portal
  wifi:
    interface: "wlan0"           # Wireless interface name
    connect_timeout: 12          # Seconds per connection attempt
    connect_retries: 4           # Number of connection retries

# ===========================================================================
# ap_mode — Access Point (first-time setup / recovery)
# ===========================================================================
ap_mode:
  ssid: "GrowMate-A1B2C3"        # AP SSID (max 32 chars; auto MAC-derived if empty)
  password: "growmate"           # AP WiFi password (min 8 chars)
  channel: 1                     # WiFi channel (1–11 for 2.4 GHz; 0 = auto)
  ip_address: "192.168.4.1"     # AP gateway
  netmask: "255.255.255.0"      # AP netmask
  dhcp_range_start: "192.168.4.2"
  dhcp_range_end: "192.168.4.20"
  interface: "wlan0"

# ===========================================================================
# onboarding — Flask portal bind address
# ===========================================================================
onboarding:
  host: "0.0.0.0"
  port: 80

# ===========================================================================
# intervals — All RELOADABLE
# ===========================================================================
intervals:
  sensor_reading: 60             # Sensor read + upload cycle (10–300 s)
  failure_monitor: 30            # Failure threshold check (5–300 s)
  camera_watchdog: 30            # rpicam-vid process health (5–300 s)
  queue_cleanup: 3600            # Queue purge (60–86400 s)
  queue_vacuum: 604800           # SQLite VACUUM (1 h – 30 days)
  queue_stats: 300               # Queue depth logging (30–3600 s)
  health_check: 300              # Health metric publication (10–3600 s)

# ===========================================================================
# queue — Offline data buffering (NON-RELOADABLE)
# ===========================================================================
queue:
  enabled: true
  db_path: "/var/lib/growmate/queue.db"
  max_age_hours: 24              # Purge entries older than N hours (1–168)
  max_sensor_entries: 1440       # ~1 day at 60 s
  cleanup_interval: 3600         # Purge job interval (overrides intervals.*)
  max_retries: 5                 # Upload attempts before discard (1–20)
  vacuum_interval: 604800        # VACUUM interval (overrides intervals.*)

# ===========================================================================
# upload_processor — Queue drain settings
# ===========================================================================
upload_processor:
  max_concurrent: 3              # Simultaneous uploads
  delay: 0.5                     # Seconds between items
  idle_sleep: 2.0                # Sleep when queue is empty
  batch_sleep: 0.1               # Sleep after processing an item

# ===========================================================================
# retry — Exponential back-off (RELOADABLE)
# ===========================================================================
retry:
  max_attempts: 6                # HTTP retries (1–10)
  initial_delay: 1.0             # First retry delay (0.1–10 s)
  max_delay: 32.0                # Ceiling (1–300 s, >= initial_delay)
  jitter: 0.25                  # Randomisation 0.0–0.5

# ===========================================================================
# circuit_breaker — Failure isolation (RELOADABLE)
# ===========================================================================
circuit_breaker:
  failure_threshold: 5           # Consecutive failures → OPEN (1–20)
  recovery_timeout: 60           # Seconds in OPEN before HALF-OPEN (5–600)
  success_threshold: 2           # Consecutive successes in HALF-OPEN → CLOSED (1–10)

# ===========================================================================
# sensors — ADC, pinout, calibration, debounce (NON-RELOADABLE)
# ===========================================================================
sensors:
  enable_dht22: true             # Set false if no DHT22 is wired
  dht22_pin: 4                   # GPIO for DHT22 data line (2–27)

  adc:                           # ADS1115 Analog-to-Digital Converter
    i2c_bus: 1                   # I2C bus number (0 or 1)
    i2c_address: 0x48            # I2C address (0x48, 0x49, 0x4A, 0x4B)
    gain: 1                      # PGA gain (1=±4.096V, 2=±2.048V, etc.)
    samples: 8                   # Samples averaged per reading (1–64)
    sample_delay: 0.01           # Seconds between samples (0.001–1.0)
    max_value: 65535             # 16-bit ADC max value

  channels:                      # Map sensor → ADC channel (P0–P3)
    battery_current: 0
    light: 1
    water: 2
    soil: 3

  calibration:                   # Raw-value → percentage mapping
    soil:
      min: 0
      max: 65535
    light:
      min: 0
      max: 65535
    water:
      min: 0
      max: 65535

  battery_current:               # ACS712 formula params
    midpoint_voltage: 2.5        # Voltage at 0 A (VCC/2)
    sensitivity: 0.185           # V/A (185 mV/A for 5 A variant)

  limit_switches:                # Tank + drawer limit switch GPIOs
    tank_gpio: 20
    drawer_gpio: 21
    pull_up_down: "PUD_UP"       # PUD_UP, PUD_DOWN, or PUD_OFF
    debounce_ms: 50              # Settle time before sampling (1–500 ms)
    debounce_samples: 5          # Majority-vote count (3–21)
    debounce_sample_interval: 0.01  # Seconds between samples

  health:                        # Per-sensor degradation tracking
    failure_threshold: 3         # Consecutive failures → degraded

# ===========================================================================
# actuators — Relay GPIOs and behaviour (NON-RELOADABLE)
# ===========================================================================
actuators:
  pins:
    pump: 10
    fertilizer: 17
    pesticide: 27
  active_high: true              # Relay energises on HIGH
  initial_value: false           # Startup state
  journal_size: 1000             # Max relay history entries
  journal_trim: 500              # Trim to N entries on overflow

# ===========================================================================
# camera — rpicam-vid live H.264 stream (NON-RELOADABLE)
# ===========================================================================
camera:
  enabled: true
  port: 8554                     # TCP listen port
  width: 640                     # Video width (160–3280)
  height: 480                    # Video height (120–2464)
  framerate: 15                  # Target FPS (1–60)
  bitrate: 1000000              # Target bitrate (100k–25M bps)
  profile: "baseline"            # H.264: baseline | main | high
  level: "3.1"                   # H.264 level
  denoise: "cdn_off"             # cdn_off | cdn_fast | cdn_hq
  restart_delay: 0.5             # Seconds before restart after crash

# ===========================================================================
# failure — Re-onboarding threshold
# ===========================================================================
failure:
  consecutive_threshold: 5       # N consecutive upload failures → re-enter
                                  # AP mode for recovery (2–20)

# ===========================================================================
# health_monitor — System health tracking
# ===========================================================================
health_monitor:
  history_size: 100              # Snapshots kept in memory (10–1000)
  camera_crash_threshold: 5      # Crashes/h to mark UNHEALTHY (1–100)

# ===========================================================================
# stream_registration — rpicam-vid registration retry
# ===========================================================================
stream_registration:
  max_attempts: 10               # Total retries at startup (1–100)
  base_delay: 1.0                # Initial retry delay (0.1–60 s)
  max_delay: 60.0                # Ceiling (1–300 s)

# ===========================================================================
# logging — Log level, format, rotation (RELOADABLE)
# ===========================================================================
logging:
  level: "INFO"                  # DEBUG | INFO | WARNING | ERROR | CRITICAL
  file: "/var/log/growmate/growmate.log"
  format: "json"                 # json or text
  max_bytes: 10485760           # 10 MB before rotation (64 KB – 1 GB)
  backup_count: 5                # Rotated files to keep (0–100)
  modules: {}                    # Per-module overrides, e.g.:
                                 #   growmate.sensors: "DEBUG"
                                 #   growmate.api: "WARNING"

# ===========================================================================
# features — Feature flags (RELOADABLE)
# ===========================================================================
features:
  offline_queue: true
  hot_reload: true
  circuit_breaker: true
```

## Hot-Reload Settings

The following can be changed at runtime without restarting the service.

Changes are detected via filesystem watcher within 1–2 seconds.

### Reloadable

| Key | Description |
|-----|-------------|
| `intervals.*` | All timing intervals |
| `retry.*` | Exponential back-off params |
| `circuit_breaker.*` | Failure thresholds and timeouts |
| `logging.level` | Root logger level |
| `logging.modules.*` | Per-module log levels |
| `features.*` | Feature toggles |
| `upload_processor.*` | Queue drain concurrency and delays |
| `failure.consecutive_threshold` | Re-onboarding trigger count |
| `health_monitor.*` | Health tracking params |
| `stream_registration.*` | Stream retry params |

### Non-Reloadable (restart required)

| Key | Description |
|-----|-------------|
| `version` | Schema version |
| `device.id` | Device identifier |
| `network.*` | WiFi credentials and interface |
| `api.*` | Endpoint URLs and timeouts |
| `queue.*` | Queue schema settings |
| `sensors.*` | ADC, pins, calibration, debounce |
| `actuators.*` | Relay pins and behaviour |
| `camera.*` | rpicam-vid stream params |
| `ap_mode.*` | Access point network config |
| `onboarding.*` | Portal bind address |

## Calibration

Analog sensor raw values (0–65535) are mapped to percentage (0–100%) using
the `sensors.calibration.*.min` / `.max` bounds.

### Find Your Bounds

```bash
# Read raw ADC values for each sensor
sudo python3 /home/pi/growmate/scripts/test_hardware.py
```

1. **Soil moisture:** Read in dry air (min) and fully submerged (max)
2. **Light:** Read in total darkness (min) and direct sunlight (max)
3. **Water level:** Read with sensor dry (min) and fully submerged (max)

### Apply

```yaml
sensors:
  calibration:
    soil:  {min: 12000, max: 52000}
    light: {min: 1000,  max: 60000}
    water: {min: 5000,  max: 55000}
```

Then **restart** (calibration is non-reloadable):

```bash
sudo systemctl restart growmate
```

### ACS712 Current Sensor

The formula is `(adc_V − midpoint_voltage) / sensitivity × 1000` mA.

- Default `midpoint_voltage: 2.5` (VCC/2 at 0 A)
- Default `sensitivity: 0.185` (185 mV/A for ACS712 5 A variant)

Change these if using a different ACS712 variant (20 A = 100 mV/A, 30 A = 66 mV/A).

### Verify

```bash
sudo journalctl -u growmate -f | grep "sensors"
```

Expected ranges:
- Soil moisture: 0% (dry) to 100% (saturated)
- Light: 0% (dark) to 100% (bright)
- Water level: 0% (empty) to 100% (full)
- Battery current: -5000 mA (discharge) to +5000 mA (charge)

## Tuning Examples

### High-Frequency Monitoring

```yaml
intervals:
  sensor_reading: 15
  failure_monitor: 15
  health_check: 60

queue:
  max_sensor_entries: 6000
```

### Low-Power / Solar

```yaml
intervals:
  sensor_reading: 300          # Every 5 minutes
  failure_monitor: 120
  camera_watchdog: 120

camera:
  enabled: false               # Disable rpicam-vid to save CPU

logging:
  level: "WARNING"

features:
  circuit_breaker: true        # Keep to avoid pointless retries
```

### Unreliable Network

```yaml
retry:
  max_attempts: 10
  initial_delay: 2.0
  max_delay: 120.0

queue:
  max_sensor_entries: 20000
  max_age_hours: 72
```

### Sensor-Only (No Camera, No DHT22)

```yaml
sensors:
  enable_dht22: false

camera:
  enabled: false
```

### Custom GPIO Layout

```yaml
sensors:
  dht22_pin: 17
  limit_switches:
    tank_gpio: 23
    drawer_gpio: 24

actuators:
  pins:
    pump: 5
    fertilizer: 6
    pesticide: 13

camera:
  enabled: false               # Pin 5 conflicts with camera CSI on some boards
```

## Security

### Network

```yaml
ap_mode:
  password: "MyCustomPassword"  # Change from default

network:
  wifi:
    connect_timeout: 30
    connect_retries: 1          # Fail fast rather than loop
```

### File Permissions

```bash
sudo chmod 600 /etc/growmate/config.yaml
sudo chown root:root /etc/growmate/config.yaml
```

### API Authentication

The `x-api-key` header is set from the `DEVICE_API_KEY` environment variable.
Never put the API key in config.yaml — use `sudo systemctl edit growmate` instead:

```ini
[Service]
Environment=DEVICE_API_KEY=<your-secret-key>
```

## Env Var Overrides

Any YAML key can be overridden by an environment variable at runtime.
This is useful for secrets and per-deployment overrides without editing the file.

Priority: **Env var > YAML file > code default**

| Env var | Overrides |
|---------|-----------|
| `DEVICE_ID` | `device.id` |
| `DEVICE_API_KEY` | `api.api_key` (secret — never in file) |
| `GROWMATE_<KEY>` | Any dotted key, e.g.: |
| `GROWMATE_API_SENSOR_URL` | `api.sensor_url` |
| `GROWMATE_INTERVALS_SENSOR_READING` | `intervals.sensor_reading` |
| `GROWMATE_SENSORS_ENABLE_DHT22` | `sensors.enable_dht22` |

---

## Support

For hardware setup, see [HARDWARE.md](HARDWARE.md)
For troubleshooting, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
For API endpoints, see [API.md](API.md)
For V2 device notes, see [device-v2-notes.md](device-v2-notes.md)
