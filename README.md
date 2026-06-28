# GrowMate V2 Pods

Automated plant monitoring and care system for Raspberry Pi Zero W. Reads sensors (soil moisture, light, water level, temperature, humidity, battery current), controls relays (pump, fertilizer, pesticide), streams live H.264 video, and reports to a cloud API.

## What It Does

- Monitors 6 sensor types every 60s via ADS1115 ADC + DHT22
- Reports to `POST /api/v2/sensors` with x-api-key auth
- Executes commands from server: pump, fertilizer, pesticide (simultaneous activation)
- Streams live H.264 video via rpicam-vid daemon (no still captures)
- Offline queue (SQLite, 24h) — never loses sensor data
- Circuit breaker + retry handler for resilient API communication
- Hot-reloadable YAML config with env var overrides
- Health monitor (5-min checks) — sensor health, queue depth, camera watchdog, Tailscale status
- AP mode onboarding for first-time WiFi setup (Flask web portal)
- Tailscale VPN for day-to-day secure connectivity

## Hardware BOM

| Component | Qty | Notes |
|-----------|-----|-------|
| Raspberry Pi Zero W | 1 | Any Pi with WiFi + camera CSI |
| ADS1115 ADC module | 1 | 4-ch 16-bit I2C ADC |
| Soil moisture sensor | 1 | Analog, capacitive |
| Light sensor (LDR) | 1 | Analog |
| Water level sensor | 1 | Analog |
| DHT22 | 1 | Temp/humidity, GPIO4 |
| ACS712 (5A) | 1 | Battery current, ADC ch0 |
| 3-channel relay module | 1 | 5V, active-high |
| 12V pump | 1 | Watering |
| 12V solenoid valve | 1 | Fertilizer |
| 12V solenoid valve | 1 | Pesticide |
| Limit switches (NC) | 2 | Tank empty, drawer open (GPIO20, GPIO21) |
| Camera module | 1 | Any Pi-compatible (OV5647, IMX219, etc.) |
| 12V battery | 1 | Power source |
| Step-down converter | 1 | 12V → 5V for Pi |

## V2 Pinout

| GPIO | Component | Type |
|------|-----------|------|
| GPIO4 | DHT22 data | Input (single-wire) |
| GPIO10 | Pump relay | Output (active-high) |
| GPIO17 | Fertilizer relay | Output (active-high) |
| GPIO27 | Pesticide relay | Output (active-high) |
| GPIO20 | Tank limit switch | Input (NC, pull-up) |
| GPIO21 | Drawer limit switch | Input (NC, pull-up) |

**ADC channels (ADS1115):**

| Channel | Sensor | Formula |
|---------|--------|---------|
| ch0 | ACS712 battery current | `(V - 2.5) / 0.185 * 1000` mA |
| ch1 | Light sensor | `mV / 4096 * 100` % (proportional) |
| ch2 | Water level | `mV / 4096 * 100` % (proportional) |
| ch3 | Soil moisture | `100 - (mV / 4096 * 100)` % (inverted) |

## Installation

```bash
sudo bash scripts/install.sh
```

The installer:
1. Installs system deps (rpicam-apps, hostapd, dnsmasq, i2c-tools, etc.)
2. Enables I2C
3. Configures AP mode support (hostapd + dnsmasq for first-time setup)
4. Copies source files to `/home/pi/growmate/`
5. Installs Python deps
6. Installs Tailscale
7. Installs and starts systemd service

### Post-Install

```bash
# Set API credentials
sudo systemctl edit growmate
```

Add:
```
[Service]
Environment=DEVICE_API_KEY=<your-api-key>
Environment=DEVICE_ID=<your-device-id>
```

```bash
# Authenticate Tailscale
sudo tailscale up

# Restart service
sudo systemctl restart growmate
```

## Configuration

### Environment Variables (take precedence)

| Variable | Required | Description |
|----------|----------|-------------|
| `DEVICE_API_KEY` | Yes | API key for x-api-key auth |
| `DEVICE_ID` | Yes | Device identifier (alphanumeric, hyphens, underscores) |
| `GROWMATE_<KEY>` | No | Override any YAML key (e.g., `GROWMATE_INTERVALS_SENSOR_READING=30`) |

### YAML Config (`/etc/growmate/config.yaml`)

```yaml
device:
  id: "growmate-001"          # overridden by DEVICE_ID env var
api:
  sensor_url: "https://growmate.bond/api/v2/sensors"
intervals:
  sensor_reading: 60          # hot-reloadable, min 10s
```

Changes to intervals and retry settings apply without restart (hot-reload via config_watcher).

## API

### Sensor Report (`POST /api/v2/sensors`)

```json
{
  "deviceId": "growmate-001",
  "firmwareVersion": "2.0.0",
  "currentState": {
    "pumpEnabled": false,
    "lightEnabled": false,
    "fertilizerEnabled": false,
    "pesticideEnabled": false,
    "tankSwitchOpen": false,
    "drawerSwitchOpen": false,
    "batteryCurrent": -120
  },
  "sensors": [
    {"kind": "soil", "value": 45, "unit": "%"},
    {"kind": "light", "value": 78, "unit": "%"},
    {"kind": "water", "value": 62, "unit": "%"},
    {"kind": "temperature", "value": 25.3, "unit": "C"},
    {"kind": "humidity", "value": 55, "unit": "%"}
  ]
}
```

**Headers:** `x-api-key: <DEVICE_API_KEY>`, `Content-Type: application/json`

**Response:**
```json
{
  "success": true,
  "commands": [
    {"kind": "pump", "durationMs": 5000},
    {"kind": "fertilizer", "durationMs": 8000}
  ]
}
```

### Stream Registration (`POST /api/v2/stream/register`)

```json
{
  "deviceId": "growmate-001",
  "streamUrl": "tcp://100.x.x.x:8554"
}
```

## First-Time Setup (AP Mode)

On first boot (unprovisioned), the device creates a WiFi AP:

1. Connect to `GrowMate-XXXXXX` WiFi (password: `growmate`)
2. Open `http://192.168.4.1`
3. Enter your WiFi credentials
4. Set device ID and API key
5. Device connects to WiFi and starts monitoring

AP mode is also available as recovery — if the service detects excessive failures, it re-enters AP mode for reconfiguration.

## Camera

Live H.264 video stream via rpicam-vid (TCP port 8554):

```
rpicam-vid -t 0 --inline --listen \
  -o tcp://0.0.0.0:8554 \
  --width 640 --height 480 --framerate 15 \
  --bitrate 1000000 --profile baseline --level 3.1 \
  --denoise cdn_off
```

The health monitor checks the rpicam-vid process every 30s and restarts it on crash. After 5+ crashes in 1 hour, reports UNHEALTHY.

## Offline Resilience

- **SQLite queue:** Sensor data queued locally when API unreachable
- **Circuit breaker:** Opens after 5 consecutive POST failures (30s recovery timeout)
- **Retry handler:** Exponential backoff 1–32s with 25% jitter (max 6 attempts)
- **Health monitor:** 5-minute checks — sensor health, queue depth, circuit breaker states, Tailscale connectivity, camera status
- **Hot-reload:** YAML changes to intervals/retry/features apply without restart

## Commands

| Kind | Behavior |
|------|----------|
| `pump` | Activates GPIO10 for durationMs |
| `fertilizer` | Activates GPIO17 + GPIO10 simultaneously for max(durationMs) |
| `pesticide` | Activates GPIO27 + GPIO10 simultaneously for max(durationMs) |
| `light` | **Ignored** (V2 has no grow light) |

If multiple commands arrive, all relays are held for the maximum durationMs across all commands.

## Service Management

```bash
# Status
systemctl status growmate

# Logs
journalctl -u growmate -f

# Restart
systemctl restart growmate

# Environment (credentials)
systemctl edit growmate
```

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

## Documentation

- [Full Setup Guide](docs/device-v2-notes-2026-06-27.md)
- [Hardware Details](docs/hardware-2026-06-26.md)
- [Wiring Diagrams](docs/wiring-2026-06-26.md)
- [API Reference](docs/api-2026-06-27.md)
- [Configuration Reference](docs/configuration-2026-06-27.md)
- [Troubleshooting](docs/troubleshooting-2026-06-27.md)
