# GrowMate V2 Device Agent — Handoff Note

**Date:** 2026-06-25  
**Status:** Handoff for device agent implementation  
**Source plan:** `design/v2-device-support-2026-06-24.md`

---

## What to Build

Four deliverables for the Raspberry Pi Zero W v1.1:

| # | Deliverable | Location | Description |
| --- | --- | --- | --- |
| 1 | `main.py` | On-device: `/home/grow/growmate/main.py` | Python main loop: ADS1115 reads, DHT22, GPIO actuator control, command execution, 60s POST interval |
| 2 | `scripts/start.sh` | On-device: `/home/grow/growmate/scripts/start.sh` | Startup script: rpicam-vid daemon, Tailscale check, stream registration, then `main.py` |
| 3 | `growmate.service` | On-device: `/etc/systemd/system/growmate.service` | Systemd unit: dependencies, restart policy, env vars |
| 4 | `docs/device-v2-notes-2026-06-27.md` | In-repo: `docs/device-v2-notes-2026-06-27.md` | Human-readable setup guide, hardware reference, pinout, troubleshooting |

---

## 1. Hardware Specification

### Board
- Raspberry Pi Zero W v1.1 (BCM2835, ARMv6, single-core 1GHz, 512MB RAM)
- WiFi: 802.11n 2.4GHz (~3 Mbps real-world throughput)
- No hardware FPU — avoid float-heavy Python where possible

### Camera
- Camera Module v1.2 (OV5647, 2592×1944 still, up to 640×480@90fps video)
- Connection: 15-pin MIPI CSI-2 ribbon cable
- Fixed focus, f/2.9 aperture
- Driver: `rpicam-vid` (Hardware H.264 via VideoCore IV GPU)
- **Do NOT use** `raspistill`/`raspivid` (legacy, unsupported on Bookworm)

### Sensors

| Sensor | Interface | Details |
| ------ | --------- | ------- |
| DHT22 | Digital, GPIO 4 | Temperature (°C) + humidity (%), single-wire protocol |
| Capacitive soil moisture | Analog → ADS1115 ch3 | 16-bit ADC, 0–65535 raw, map to 0–100% |
| Water level (fertilizer tank) | Analog → ADS1115 ch2 | 16-bit ADC, 0–65535 raw, map to 0–100% |
| LDR / photoresistor (light) | Analog → ADS1115 ch1 | 16-bit ADC, 0–65535 raw, map to 0–100% |
| ACS712 current sensor (battery) | Analog → ADS1115 ch0 | Bidirectional Hall-effect, 185 mV/A sensitivity (5A variant), Vcc/2 at 0A |

**ADC chip details:** ADS1115 (16-bit, 4-channel, I²C, programmable gain). All analog sensors read through this single chip. Gain set to ±4.096V (gain=1). I²C address: `0x48` (default, configurable to `0x49`).

**Battery:** Lead acid 12V 5Ah sealed. ACS712 on battery line measures net charge/discharge current. Server-side coulomb counting estimates SoC. Calibration: at Vcc/2 = 0A, 185mV/A → raw ADC counts map to mA.

### Actuators

| Actuator | GPIO | Type |
| -------- | ---- | ---- |
| 12V water pump | GPIO 10 (Relay 4) | 12V 5A |
| Fertilizer solenoid valve | GPIO 17 (Relay 1) | 12V NC, 1/4" tubing |
| Pesticide solenoid valve | GPIO 27 (Relay 2) | 12V NC, 1/4" tubing |

All actuators controlled via a 3-channel 5V relay module (10A rating). External 12V PSU + 5V step-down for Pi.

### Limit Switches
- **Switch A (GPIO 20):** Fertilizer/pesticide tank lid — NC (LOW when closed = normal, HIGH when open = alarm)
- **Switch B (GPIO 21):** Back drawer (contains soil sensor + optional modem) — NC (LOW when closed = normal, HIGH when open = alarm)
- Both use internal pull-up: `GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)`

### Optional Hardware (device variant)
- **Built-in cellular modem** (USB dongle, e.g. SIM7600/Huawei E3372) — stored in back drawer, plugged into Pi's USB port
- **Solar panel** (e.g. 10W–20W) → solar charge controller → battery (independent circuit, not connected to Pi)

### Pinout

```
GPIO 2 (SDA)  ── I²C SDA (ADS1115, shared bus)
GPIO 3 (SCL)  ── I²C SCL (ADS1115, shared bus)

GPIO 4        ── DHT22 (temperature + humidity, single-wire)

GPIO 17       ── Relay 1 (fertilizer valve)
GPIO 27       ── Relay 2 (pesticide valve)
GPIO 22       ── Relay 3 (not connected)
GPIO 10       ── Relay 4 (pump)

GPIO 20       ── Limit switch A (tank lid — NC, LOW = closed)
GPIO 21       ── Limit switch B (back drawer — NC, LOW = closed)

ADS1115 ch0   ── ACS712 current sensor (analog, battery)
ADS1115 ch1   ── Light sensor / LDR (analog)
ADS1115 ch2   ── Water level sensor / fertilizer tank (analog)
ADS1115 ch3   ── Soil moisture sensor (analog)

5V            ── ACS712 Vcc, DHT22 Vcc, relay module power
3.3V          ── ADS1115 Vcc
I²C addr:     ADS1115 = 0x48 (default, configurable to 0x49)
```

**Note:** No SPI pins used. DHT22 on its own GPIO 4 (not sharing I²C pins). All analog sensors go through ADS1115.

---

## 2. API Contracts

### 2.1 Sensor Report (the main loop)

```
POST https://growmate.bond/api/v2/sensors
Headers:
  x-api-key: <DEVICE_API_KEY>
  Content-Type: application/json
Body (JSON):
{
  "deviceId": "<string>",
  "firmwareVersion": "2.0.0",
  "currentState": {
    "pumpEnabled": false,
    "lightEnabled": false,
    "fertilizerEnabled": false,
    "pesticideEnabled": false,
    "tankSwitchOpen": false,
    "drawerSwitchOpen": false,
    "batteryCurrent": 0
  },
  "sensors": [
    { "kind": "temperature", "value": 28.5, "unit": "C" },
    { "kind": "air", "value": 65.0, "unit": "%" },
    { "kind": "soil", "value": 45.0, "unit": "%", "raw": 12345 },
    { "kind": "water", "value": 80.0, "unit": "%", "raw": 54321 },
    { "kind": "light", "value": 60.0, "unit": "%", "raw": 30000 }
  ]
}
Response (200):
{
  "success": true,
  "updated": 5,
  "commands": [
    { "kind": "pump", "durationMs": 8000 },
    { "kind": "fertilizer", "durationMs": 10000 }
  ]
}
```

**Validation rules:**
- Content-length max: 100KB
- `deviceId` is required (string, not a Convex ID — the device self-identifies)
- Temperature range: -40 to 125
- All other sensor values: 0–100
- Raw ADC values: 0–65535 (16-bit)
- All 5 sensor kinds are required in every POST: `soil`, `light`, `temperature`, `air`, `water`
- `currentState` is optional but should always be sent by V2 devices
- `fertilizerEnabled`/`pesticideEnabled` in currentState must reflect the actual relay state AFTER any commands were executed (closed = false, open = true)

**Commands response:**
- `commands` is an array of action objects (may be empty `[]`)
- Each command: `{ kind: string, ... }`
- Kinds: `pump` (durationMs), `fertilizer` (durationMs), `pesticide` (durationMs), `light` (enabled boolean — V2 devices should ignore `light` commands)
- **Execution rules:**
  1. If `fertilizer` or `pesticide` is commanded, `pump` will ALSO be commanded in the same response. Actuate both simultaneously — the pump carries the chemical through the valve.
  2. If only `pump` is commanded = plain watering (no chemicals).
  3. If multiple durationMs values differ, hold all relays for the maximum duration.
  4. After execution, the next sensor POST's `currentState` must reflect the actual relay states.
- Commands are cleared server-side after each successful sensor POST. The device should execute them **immediately** upon receipt.

### 2.2 Stream Registration

```
POST https://growmate.bond/api/v2/stream/register
Headers:
  x-api-key: <DEVICE_API_KEY>
  Content-Type: application/json
Body:
{
  "deviceId": "<string>",
  "streamUrl": "tcp://100.x.x.x:8554"
}
Response:
{
  "success": true,
  "streamId": "<deviceId>"
}
```

Run this once at startup, after Tailscale is connected and rpicam-vid is listening. The `streamUrl` format must be `tcp://<Tailscale IP>:8554`.

### 2.3 Auth Pattern (for all device endpoints)
The shared `DEVICE_API_KEY` is set as an environment variable on both server and device. This is a static pre-shared key, not per-device tokens. The device includes it as `x-api-key` header on every request.

---

## 3. Camera Streaming

### 3.1 rpicam-vid Configuration

Run on device as a background daemon:

```bash
rpicam-vid -t 0 --inline --listen \
  -o tcp://0.0.0.0:8554 \
  --width 640 --height 480 --framerate 15 \
  --bitrate 1000000 --profile baseline --level 3.1 \
  --denoise cdn_off
```

| Flag | Value | Reason |
| --- | --- | --- |
| `--width` | 640 | Good balance of quality vs perf |
| `--height` | 480 | |
| `--framerate` | 15 | Smooth for plant watching |
| `--bitrate` | 1000000 (1 Mbps) | Fits within ~3 Mbps WiFi budget |
| `--profile` | baseline | Widest decoder support |
| `--level` | 3.1 | Appropriate for 640×480@15fps |
| `--denoise` | cdn_off | Saves GPU cycles on Pi Zero |
| `--inline` | (flag) | SPS/PPS before every keyframe |
| `--listen` | (flag) | TCP server mode |
| `-t 0` | (flag) | Run indefinitely |
| `-o tcp://...` | TCP output | Raw H.264 over TCP |

### 3.2 How the Pipeline Works

```
rpicam-vid ──TCP──→ Server StreamManager ──WebSocket──→ Browser
                          │
                          └──→ Rotating file → S3/MinIO
```

- **Device**: rpicam-vid listens on TCP port 8554, outputs raw H.264 Annex B byte stream. No container (no MP4/TS headers).
- **Server**: connects to `tcp://<Tailscale IP>:8554`, parses NAL units, caches SPS/PPS, writes 60-second segment files, then uploads completed segments to MinIO/S3.
- **Browser**: receives NAL units over WebSocket wrapped in a lightweight protocol: `[1 byte flags][6 bytes timestamp (microseconds)][NAL unit bytes]`. Uses WebCodecs `VideoDecoder` for playback.

### 3.3 NAL Unit Protocol

Raw H.264 Annex B byte stream:
- Start code: `0x00 0x00 0x00 0x01` (4-byte) or `0x00 0x00 0x01` (3-byte)
- NAL unit types (first byte after start code & 0x1F):
  - `7` = SPS (Sequence Parameter Set) — codec profile/level
  - `8` = PPS (Picture Parameter Set) — entropy coding mode
  - `5` = IDR (Instantaneous Decoder Refresh) — keyframe
  - `1` = Non-IDR slice (delta frame)

The device does NOT need to parse or understand NAL units. It simply runs `rpicam-vid` which handles all encoding. The server and browser handle parsing.

---

## 4. Startup Sequence

On boot or service start:

1. **Tailscale** must be connected. `tailscale status` to check, `tailscale up` if not.
2. **rpicam-vid** starts as a background process (daemonized with `&` or proper process management).
3. **Stream registration**: Wait briefly for rpicam-vid to start, then get Tailscale IP (`tailscale ip -4`), POST to `/api/v2/stream/register`.
4. **`main.py`** starts the main sensor/control loop.

The `start.sh` script orchestrates steps 1–4.

---

## 5. main.py — Main Loop Specification

### 5.1 GPIO Setup

`RPi.GPIO` works on current Pi OS but is deprecated. `gpiozero` is preferred for future-proofing. Either is acceptable.

Use BCM pin numbering.

### 5.2 ADS1115 Setup

Use `adafruit-circuitpython-ads1x15` library. I²C via `busio.I2C(board.SCL, board.SDA)`. Gain = 1 (±4.096V range, 0.125 mV per LSB).

### 5.3 DHT22 Reading

Use `adafruit-circuitpython-dht` library. Single-wire protocol on GPIO 4.

### 5.4 Main Loop (60-second interval)

*Actual implementation deviates from this simplified pseudocode — see §5.4a below.*

```
while True:
    currentState = read_gpio_states()
    sensors = read_all_sensors()
    
    payload = {
        "deviceId": DEVICE_ID,
        "firmwareVersion": "2.0.0",
        "currentState": currentState,
        "sensors": sensors
    }
    
    try:
        resp = POST /api/v2/sensors (json=payload, headers={"x-api-key": ...}, timeout=30)
        data = resp.json()
        if data.get("commands"):
            execute_commands(data["commands"])
    except Exception as e:
        log_error(e)
    
    sleep(60)  # Report every 60 seconds
```

#### 5.4a Actual Implementation Divergence

The production device agent (`src/main.py`) wraps this sync loop in a richer async infrastructure:

| Handoff Spec | Actual Implementation |
|---|---|
| `while True: sleep(60)` — synchronous blocking loop | `asyncio.run()` + APScheduler `AsyncIOScheduler` with async jobs |
| No offline queue | SQLite offline queue (24h, WAL, FIFO) via `queue_manager.py` — failed POSTs queued with backoff |
| No circuit breaker | Per-endpoint circuit breaker (`circuit_breaker.py`) — sensor + stream + command endpoints |
| No retry logic | Exponential backoff with jitter (`retry_handler.py`) |
| No config management | YAML config file primary, env var overrides (`config_manager.py` + `config_validator.py` + `config_watcher.py`) |
| No health monitoring | 5-min health checks (`health_monitor.py`): Tailscale IP, circuit breaker state, queue depth, camera process |
| No structured logging | JSON structured logging with correlation IDs (`logging_config.py`) |
| No AP mode (Tailscale only) | AP mode + Flask onboarding portal KEPT as WiFi setup/recovery (`network_manager.py`, `onboarding_portal.py`) |
| Environment vars in systemd unit only | YAML config at `config/config.yaml` (primary), env vars override individual keys |

### 5.5 Sensor Reading Details

```python
def read_adc_mv(channel):
    # ADS1115: return voltage * 1000 (mV)
    # channel 0 = battery current (ACS712), 1 = light, 2 = water, 3 = soil
    
def read_current_ma():
    # ACS712: (adc_V - 2.5) / 0.185 * 1000
    # positive = charging, negative = discharging
    
def read_sensors():
    # soil_pct = max(0, min(100, 100 - (soil_mv / 4096 * 100)))
    # tank_pct = max(0, min(100, tank_mv / 4096 * 100))
    # light_pct = max(0, min(100, light_mv / 4096 * 100))
    # DHT22 → temperature (°C), humidity (%)
    # Return list of {"kind", "value", "unit", "raw"?}
```

**ADC → percentage mapping notes:**
- Soil: inverted (dry = high mV, wet = low mV): `100 - (mV / 4096 * 100)`
- Water tank: proportional: `mV / 4096 * 100`
- Light: proportional: `mV / 4096 * 100`

### 5.6 Command Execution

```python
def execute_commands(commands):
    for cmd in commands:
        kind = cmd["kind"]
        duration_ms = cmd.get("durationMs", 0)
        pin = {"pump": 10, "fertilizer": 17, "pesticide": 27}.get(kind)
        if pin is not None:
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(duration_ms / 1000)
            GPIO.output(pin, GPIO.LOW)
```

**Important:** If multiple commands arrive (e.g., `pump` + `fertilizer`), the above sequential approach works because each actuator has its own relay pin. However, a more efficient approach is to:
1. Set all commanded pins HIGH simultaneously
2. `time.sleep(max(durationMs for cmd in commands) / 1000)`
3. Set all LOW simultaneously

### 5.7 get_current_state()

```python
def get_current_state():
    return {
        "pumpEnabled": GPIO.input(10) == GPIO.HIGH,
        "lightEnabled": False  # V2 has no grow light, always false
        "fertilizerEnabled": GPIO.input(17) == GPIO.HIGH,
        "pesticideEnabled": GPIO.input(27) == GPIO.HIGH,
        "tankSwitchOpen": GPIO.input(20) == GPIO.HIGH,  # NC: LOW=closed, HIGH=open
        "drawerSwitchOpen": GPIO.input(21) == GPIO.HIGH,  # NC: LOW=closed, HIGH=open
        "batteryCurrent": read_current_ma(),
    }
```

---

## 6. systemd Service Specification

**Service file:** `/etc/systemd/system/growmate.service`

```ini
[Unit]
Description=GrowMate V2 Agent
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/home/grow/growmate/start.sh
Restart=always
RestartSec=10
User=grow
Environment=DEVICE_API_KEY=<set during provisioning>
Environment=DEVICE_ID=<unique device ID, set during provisioning>

[Install]
WantedBy=multi-user.target
```

Requirements:
- Depends on `network-online.target` (Tailscale needs network)
- `Restart=always` with 10s delay
- Passes `DEVICE_API_KEY` and `DEVICE_ID` as env vars to both `start.sh` and `main.py`

---

## 7. Device Provisioning Steps (implemented in `scripts/install.sh`)

> The manual steps below document what `scripts/install.sh` automates. For fresh installs, run:
> ```bash
> curl -sSL https://raw.githubusercontent.com/FarelRA/rpi-growmate-pods/main/scripts/install.sh | bash
> ```

1. **Flash OS**: Raspberry Pi OS Lite (32-bit, Bookworm) — ARMv6 compatible
2. **Enable SSH + WiFi**: `touch /boot/firmware/ssh`, configure `wpa_supplicant.conf`
3. **Configure**: `sudo raspi-config` → enable I2C, Camera (not SPI)
4. **System update**: `sudo apt update && sudo apt upgrade -y`
5. **Install deps**:
   ```bash
   sudo apt install -y python3-pip python3-libgpiod rpicam-apps hostapd dnsmasq
   pip3 install requests RPi.GPIO gpiozero adafruit-circuitpython-dht adafruit-circuitpython-ads1x15 flask
   ```
6. **Install Tailscale**:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up   # follow URL to authenticate
   ```
7. **Create project structure** (handled by install.sh):
   ```bash
   mkdir -p /home/grow/growmate
   cp -r src/ /home/grow/growmate/
   cp config/config.yaml.example /home/grow/growmate/config/config.yaml
   cp scripts/start.sh /home/grow/growmate/
   cp templates /home/grow/growmate/
   cp static /home/grow/growmate/
   chmod +x /home/grow/growmate/scripts/*.sh
   ```
8. **Generate config.yaml** — install.sh prompts for API key, device ID, WiFi credentials, log level
9. **Install systemd service**: Copy `systemd/growmate.service` to `/etc/systemd/system/`, then `sudo systemctl enable growmate`
10. **AP mode** activates on first boot if no WiFi credentials are stored; user connects to `growmate-XXXX` AP, opens http://192.168.4.1, enters WiFi credentials
11. **Verify**:
    ```bash
    sudo journalctl -u growmate -f
    ```
    - Check that `POST /api/v2/sensors` returns `{ success: true, commands: [...] }`
    - Check that live stream plays in browser
    - Check that recordings appear after 60 seconds

### Troubleshooting Table (include in docs)

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No camera feed | rpicam-vid not installed | `sudo apt install rpicam-apps` |
| Camera hangs after 30s | GPU memory too low | Add `gpu_mem=256` to config.txt |
| Stream slow/jerky | Bitrate too high for WiFi | Reduce `--bitrate` to 500000 |
| Tailscale not connecting | Outdated version | Re-run install script |
| Sensor readings all zero | ADS1115 wiring | `sudo i2cdetect -y 1` — should show `0x48` |
| Battery current always 0 | ACS712 / ADS1115 issue | Check ACS712 output at 0A (~2.5V) |
| Limit switch always HIGH | Missing pull-up | `GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)` |
| Relay not triggering | Wrong GPIO / power | Check wiring; add driver transistor |

---

## 8. Version-Specific Behavior Summary

| Aspect | V1 (existing) | V2 (this build) |
| --- | --- | --- |
| Endpoint | `POST /api/v1/sensors` | `POST /api/v2/sensors` |
| ADC range | 0–4095 (10-bit) | 0–65535 (16-bit) |
| Temp range | 0–100 | -40 to 125 |
| Grow light | Yes (GPIO relay) | No |
| Fertilizer valve | No | Yes (GPIO 17) |
| Pesticide valve | No | Yes (GPIO 27) |
| Camera | Still images (`POST /api/v1/camera`) | Live H.264 TCP stream |
| Battery monitoring | No | Yes (ACS712 + ADS1115 ch0) |
| Limit switches | No | Yes (GPIO 20, 21) |
| Connectivity | Direct WiFi | Tailscale VPN |
| Firmware version field | Optional | Should send `"2.0.0"` |
| `currentState.lightEnabled` | Required, meaningful | Send `false` (no grow light) |

---

## 9. Verification Checklist

After building, confirm:
1. `main.py` starts, reads all 5 sensors + current via ADS1115, reads DHT22, reads limit switches
2. `POST /api/v2/sensors` returns commands, which are executed on GPIO relays
3. `start.sh` brings up Tailscale, starts rpicam-vid, registers stream, then runs main.py
4. `growmate.service` starts on boot, restarts on failure, logs to journald
5. `docs/device-v2-notes-2026-06-27.md` covers every step from SD card flash to "it works"
6. Live stream is visible in browser dashboard
7. Recordings appear after 60 seconds in the dashboard History panel
