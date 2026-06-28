# GrowMate V2 Device — Setup Guide

**Board:** Raspberry Pi Zero W v1.1 (BCM2835, ARMv6, single-core 1GHz, 512MB RAM)  
**OS:** Raspberry Pi OS Lite (32-bit, Bookworm)  
**API Base:** `https://growmate.bond/api/v2`

---

## Table of Contents

- [Provisioning Steps](#provisioning-steps)
- [Hardware Reference](#hardware-reference)
- [Pinout](#pinout)
- [ADC → Percentage Mapping](#adc--percentage-mapping)
- [Camera Streaming](#camera-streaming)
- [Startup Sequence](#startup-sequence)
- [main.py Overview](#agentpy-overview)
- [systemd Service](#systemd-service)
- [Troubleshooting](#troubleshooting)
- [Version Comparison](#version-comparison)

---

## Provisioning Steps

### 1. Flash OS

Download **Raspberry Pi OS Lite (32-bit, Bookworm)** — ARMv6 compatible.

```bash
# Use Raspberry Pi Imager or dd
# Enable SSH + WiFi at flash time:
touch /boot/firmware/ssh
```

Configure `wpa_supplicant.conf` on the boot partition for initial network access.

### 2. First Boot

```bash
ssh pi@<ip-address>  # default password: raspberry
sudo raspi-config
# → Interface Options → I2C: enable
# → Interface Options → Camera: enable (legacy camera toggle)
# → Performance Options → GPU Memory: set to 256
sudo reboot
```

### 3. System Update

```bash
sudo apt update && sudo apt upgrade -y
```

### 4. Install Dependencies

```bash
sudo apt install -y python3-pip python3-libgpiod rpicam-apps
pip3 install requests RPi.GPIO gpiozero adafruit-circuitpython-dht adafruit-circuitpython-ads1x15
```

### 5. Install Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up  # follow URL to authenticate
```

Verify: `tailscale status` and note the Tailscale IP (`tailscale ip -4`).

### 6. Create Project Structure

```bash
mkdir -p /home/grow/growmate
```

Copy these files onto the device (via SCP or Git):

| File | Destination |
|------|------------|
| `main.py` | `/home/grow/growmate/main.py` |
| `start.sh` | `/home/grow/growmate/start.sh` |

```bash
chmod +x /home/grow/growmate/*.sh
```

### 7. Configure Environment

The service relies on two environment variables. Set them in the systemd unit file (see [systemd Service](#systemd-service)):

- `DEVICE_API_KEY` — Shared pre-shared key for all device-to-server auth
- `DEVICE_ID` — Unique device identifier (string, not a Convex ID)

### 8. Install systemd Service

```bash
sudo cp growmate.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable growmate
sudo systemctl start growmate
```

### 9. Verify

```bash
sudo journalctl -u growmate -f
```

Check that:
- `POST /api/v2/sensors` returns `{ "success": true, "commands": [...] }`
- Live stream plays in browser dashboard
- Recordings appear after 60 seconds in the History panel

---

## Hardware Reference

### Board

- **Model:** Raspberry Pi Zero W v1.1
- **SoC:** BCM2835 (ARMv6, single-core 1GHz)
- **RAM:** 512MB
- **WiFi:** 802.11n 2.4GHz (~3 Mbps real-world throughput)
- **No hardware FPU** — avoid float-heavy Python where possible

### Camera

- **Module:** Camera Module v1.2 (OV5647)
- **Resolution:** 2592×1944 still, up to 640×480@90fps video
- **Connection:** 15-pin MIPI CSI-2 ribbon cable
- **Focus:** Fixed, f/2.9 aperture
- **Driver:** `rpicam-vid` (Hardware H.264 via VideoCore IV GPU)
- **Do NOT use** `raspistill`/`raspivid` (legacy, unsupported on Bookworm)

### Sensors

| Sensor | Interface | Details |
| ------ | --------- | ------- |
| DHT22 | Digital, GPIO 4 | Temperature (°C) + humidity (%), single-wire protocol |
| Capacitive soil moisture | Analog → ADS1115 ch3 | 16-bit ADC, 0–65535 raw, map to 0–100% |
| Water level (fertilizer tank) | Analog → ADS1115 ch2 | 16-bit ADC, 0–65535 raw, map to 0–100% |
| LDR / photoresistor (light) | Analog → ADS1115 ch1 | 16-bit ADC, 0–65535 raw, map to 0–100% |
| ACS712 current sensor (battery) | Analog → ADS1115 ch0 | Bidirectional Hall-effect, 185 mV/A (5A variant), Vcc/2 at 0A |

**ADC chip:** ADS1115 (16-bit, 4-channel, I²C, programmable gain). Gain = 1 (±4.096V). I²C address: `0x48` (default, configurable to `0x49`).

**Battery:** Lead acid 12V 5Ah sealed. ACS712 on battery line measures net charge/discharge current. Server-side coulomb counting estimates SoC. Calibration: at Vcc/2 = 0A, 185mV/A → raw ADC counts map to mA.

### Actuators

| Actuator | GPIO | Type |
| -------- | ---- | ---- |
| 12V water pump | GPIO 10 (Relay 4) | 12V 5A |
| Fertilizer solenoid valve | GPIO 17 (Relay 1) | 12V NC, 1/4" tubing |
| Pesticide solenoid valve | GPIO 27 (Relay 2) | 12V NC, 1/4" tubing |

All actuators via a 3-channel 5V relay module (10A rating). External 12V PSU + 5V step-down for Pi. GPIO 22 (Relay 3) is not connected.

### Limit Switches

- **Switch A (GPIO 20):** Fertilizer/pesticide tank lid — NC (LOW when closed = normal, HIGH when open = alarm)
- **Switch B (GPIO 21):** Back drawer — NC (LOW when closed = normal, HIGH when open = alarm)
- Both use internal pull-up: `GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)`

### Optional Hardware

- **Built-in cellular modem** (USB dongle, e.g. SIM7600/Huawei E3372) — stored in back drawer
- **Solar panel** (e.g. 10W–20W) → solar charge controller → battery (independent circuit)

---

## Pinout

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

No SPI pins used. DHT22 on its own GPIO 4 (not sharing I²C pins). All analog sensors go through ADS1115.

---

## ADC → Percentage Mapping

| Sensor | Formula | Notes |
|--------|---------|-------|
| Soil moisture | `100 - (mV / 4096 * 100)` | Inverted: dry = high mV, wet = low mV |
| Water tank | `mV / 4096 * 100` | Proportional |
| Light | `mV / 4096 * 100` | Proportional |

All ADC percentages clamped to 0–100.

---

## Camera Streaming

### rpicam-vid Daemon

```bash
rpicam-vid -t 0 --inline --listen \
  -o tcp://0.0.0.0:8554 \
  --width 640 --height 480 --framerate 15 \
  --bitrate 1000000 --profile baseline --level 3.1 \
  --denoise cdn_off
```

| Flag | Value | Reason |
|------|-------|--------|
| `--width/height` | 640×480 | Balance of quality vs perf |
| `--framerate` | 15 | Smooth for plant watching |
| `--bitrate` | 1 Mbps | Fits within ~3 Mbps WiFi budget |
| `--profile` | baseline | Widest decoder support |
| `--level` | 3.1 | Appropriate for 640×480@15fps |
| `--denoise` | cdn_off | Saves GPU cycles on Pi Zero |
| `--inline` | — | SPS/PPS before every keyframe |
| `--listen` | — | TCP server mode |

### Pipeline

```
rpicam-vid ──TCP──→ Server StreamManager ──WebSocket──→ Browser
                          │
                          └──→ Rotating file → S3/MinIO
```

The device runs `rpicam-vid` — it does NOT need to parse NAL units. The server and browser handle all parsing.

### Stream Registration

Run once at startup, after Tailscale is connected and rpicam-vid is listening:

```
POST /api/v2/stream/register
Body: { "deviceId": "<id>", "streamUrl": "tcp://<Tailscale IP>:8554" }
```

---

## Startup Sequence

On boot or service start:

1. **Tailscale** connects. `tailscale status` to check, `tailscale up` if not.
2. **rpicam-vid** starts as a background process.
3. **Stream registration**: Wait briefly for rpicam-vid to start, get Tailscale IP, POST to `/api/v2/stream/register`.
4. **`main.py`** starts the main sensor/control loop (60s interval POST to `/api/v2/sensors`).

The `start.sh` script orchestrates steps 1–4.

---

## main.py Overview

### GPIO Setup

`RPi.GPIO` or `gpiozero`. Use BCM pin numbering.

### ADS1115

`adafruit-circuitpython-ads1x15` library. I²C via `busio.I2C(board.SCL, board.SDA)`. Gain = 1 (±4.096V, 0.125 mV/LSB).

### DHT22

`adafruit-circuitpython-dht` library on GPIO 4.

### Main Loop (60-second interval)

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
    resp = POST /api/v2/sensors (json=payload, headers={"x-api-key": ...}, timeout=30)
    if resp.json().get("commands"):
        execute_commands(resp.json()["commands"])
    sleep(60)
```

### Command Execution

If multiple commands arrive (e.g. `pump` + `fertilizer`):
1. Set all commanded pins HIGH simultaneously
2. `sleep(max(durationMs for cmd in commands) / 1000)`
3. Set all LOW simultaneously

---

## systemd Service

**File:** `/etc/systemd/system/growmate.service`

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

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No camera feed | rpicam-vid not installed | `sudo apt install rpicam-apps` |
| Camera hangs after 30s | GPU memory too low | Add `gpu_mem=256` to config.txt |
| Stream slow/jerky | Bitrate too high for WiFi | Reduce `--bitrate` to 500000 |
| Tailscale not connecting | Outdated version | Re-run install script |
| Sensor readings all zero | ADS1115 wiring | `sudo i2cdetect -y 1` — should show `0x48` |
| Battery current always 0 | ACS712 / ADS1115 issue | Check ACS712 output at 0A (~2.5V) |
| Limit switch always HIGH | Missing pull-up | `GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)` |
| Relay not triggering | Wrong GPIO / power | Check wiring; add driver transistor |

---

## Version Comparison

| Aspect | V1 (existing) | V2 (this build) |
|--------|---------------|-----------------|
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
