# GrowMate Pods - Raspberry Pi Zero W

IoT plant monitoring system with sensors, camera, cloud API integration, and actuator control. Port of ESP32-CAM GrowMate firmware to Raspberry Pi Zero W.

## Features

- **Sensor Monitoring**
  - Soil moisture (analog via ADS1115)
  - Light level (analog via ADS1115)
  - Water level (analog via ADS1115)
  - Temperature and humidity (DHT22)
  - Configurable calibration for accurate readings
  - 15-second reading intervals

- **Camera System**
  - Pi Camera Module v1 (5MP)
  - JPEG image capture
  - 15-minute capture intervals
  - Automatic upload to cloud

- **Cloud Integration**
  - HTTPS API communication
  - Sensor data upload (JSON)
  - Image upload
  - Command reception from server
  - Automatic retry with exponential backoff

- **Actuator Control**
  - Water pump (timed duration control)
  - Grow light (on/off control)
  - Cloud-commanded operation
  - Automatic safety shutoff

- **WiFi Management**
  - AP mode for initial setup
  - Web-based configuration portal
  - Automatic client mode switching
  - Fallback to AP mode on failures

- **System Reliability**
  - Systemd service integration
  - Auto-start on boot
  - Auto-restart on failure
  - Comprehensive logging
  - Graceful error handling

## Hardware Requirements

| Component | Specification | Cost | Notes |
|-----------|--------------|------|-------|
| Raspberry Pi Zero W | BCM2835, 512MB RAM, WiFi | $15 | Main controller |
| Pi Camera Module v1 | 5MP | $15 | CSI interface |
| ADS1115 ADC | 16-bit, 4-channel, I2C | $5 | **Required** - Pi has no ADC |
| DHT22 | Temperature/humidity sensor | $5 | Digital (GPIO) |
| Soil moisture sensor | Analog | $3 | Via ADS1115 A0 |
| Light sensor | Photoresistor | $2 | Via ADS1115 A1 |
| Water level sensor | Analog | $3 | Via ADS1115 A2 |
| 2-channel relay module | 5V | $5 | Pump + light control |
| MicroSD card | 16GB+ | $8 | OS + storage |
| Power supply | 5V 2.5A | $8 | Adequate current |
| **Total** | | **$69** | |

## Pin Assignment

```
GPIO 2/3   - I2C (SDA/SCL) for ADS1115
GPIO 4     - DHT22 sensor
GPIO 17    - Water pump relay
GPIO 27    - Grow light relay
CSI port   - Pi Camera Module v1
```

## Installation

### Prerequisites

- Raspberry Pi Zero W
- MicroSD card (16GB+) with Raspberry Pi OS Lite
- All hardware components wired according to pin assignment
- Internet connection for initial setup

### Quick Install

```bash
# Clone repository
git clone https://github.com/USER/rpi-growmate-pods.git
cd rpi-growmate-pods

# Run installation script
sudo bash scripts/install.sh

# Reboot to enable I2C and camera
sudo reboot

# After reboot, start service
sudo systemctl start growmate
```

### Manual Installation

1. **Update system:**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Install dependencies:**
   ```bash
   sudo apt install -y python3 python3-pip python3-dev i2c-tools \
       libgpiod2 libcamera-apps hostapd dnsmasq
   ```

3. **Enable I2C and Camera:**
   ```bash
   sudo raspi-config
   # Interface Options -> I2C -> Enable
   # Interface Options -> Camera -> Enable
   sudo reboot
   ```

4. **Install Python packages:**
   ```bash
   pip3 install -r requirements.txt
   ```

5. **Copy files:**
   ```bash
   sudo mkdir -p /opt/growmate
   sudo cp -r src templates static config systemd scripts /opt/growmate/
   sudo mkdir -p /etc/growmate
   sudo cp config/config.yaml.example /etc/growmate/config.yaml
   ```

6. **Install systemd service:**
   ```bash
   sudo cp systemd/growmate.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable growmate
   sudo systemctl start growmate
   ```

## Configuration

### Initial Setup (Onboarding)

On first boot, the device enters AP mode:

1. Connect to WiFi network: `GrowMate-XXXXXX`
2. Password: `growmate`
3. Open browser: `http://192.168.4.1`
4. Select your WiFi network
5. Enter WiFi password
6. Click "Save and Continue"

The device will automatically connect to your WiFi and begin monitoring.

### Configuration File

Configuration is stored at `/etc/growmate/config.yaml`:

```yaml
version: 4

device:
  id: "growmate-b827eb123456"

network:
  provisioned: true
  wifi_ssid: "YourNetwork"
  wifi_password: "YourPassword"

api:
  sensor_url: "https://api.example.com/sensors"
  camera_url: "https://api.example.com/camera"

intervals:
  sensor_reading: 15      # seconds
  camera_capture: 900     # seconds (15 minutes)

calibration:
  soil_moisture: {min: 0, max: 65535}
  light: {min: 0, max: 65535}
  water_level: {min: 0, max: 65535}

sensors:
  enable_dht22: true
```

### Sensor Calibration

To calibrate sensors:

1. Read raw values: `sudo python3 /opt/growmate/scripts/test_hardware.py`
2. Note minimum value (dry/dark/empty)
3. Note maximum value (wet/bright/full)
4. Update `/etc/growmate/config.yaml` with calibration values
5. Restart service: `sudo systemctl restart growmate`

## Usage

### Service Management

```bash
# Start service
sudo systemctl start growmate

# Stop service
sudo systemctl stop growmate

# Restart service
sudo systemctl restart growmate

# Check status
sudo systemctl status growmate

# View logs
sudo journalctl -u growmate -f

# View recent logs
sudo journalctl -u growmate -n 100
```

### Hardware Testing

Test all hardware components:

```bash
sudo python3 /opt/growmate/scripts/test_hardware.py
```

This will test:
- I2C bus and ADS1115 ADC
- All 3 analog sensors
- DHT22 sensor
- Pi Camera
- GPIO relays (pump, light)
- Network interface

### Re-entering Onboarding Mode

If you need to reconfigure WiFi:

1. Edit config: `sudo nano /etc/growmate/config.yaml`
2. Set `provisioned: false`
3. Restart: `sudo systemctl restart growmate`
4. Device will enter AP mode

Or delete the config file:
```bash
sudo rm /etc/growmate/config.yaml
sudo systemctl restart growmate
```

## API Integration

### Sensor Data Upload

**Endpoint:** `POST /api/sensors`

**Request:**
```json
{
  "deviceId": "growmate-b827eb123456",
  "firmwareVersion": "2.0.0-rpi",
  "sensors": [
    {"kind": "soil", "value": 45, "unit": "%", "raw": 1843},
    {"kind": "light", "value": 78, "unit": "%", "raw": 3195},
    {"kind": "water", "value": 92, "unit": "%", "raw": 3767},
    {"kind": "temperature", "value": 24, "unit": "C", "raw": -1},
    {"kind": "air", "value": 65, "unit": "%", "raw": -1}
  ],
  "currentState": {
    "pumpEnabled": false,
    "lightEnabled": true
  }
}
```

**Response:**
```json
{
  "commands": [
    {"kind": "pump", "durationMs": 5000},
    {"kind": "light", "enabled": true}
  ]
}
```

### Camera Image Upload

**Endpoint:** `POST /api/camera`

**Headers:**
- `Content-Type: image/jpeg`
- `X-Device-Id: growmate-b827eb123456`

**Body:** Raw JPEG bytes

## Troubleshooting

### Service won't start

```bash
# Check service status
sudo systemctl status growmate

# Check logs
sudo journalctl -u growmate -n 50

# Common issues:
# - I2C not enabled: sudo raspi-config
# - Camera not enabled: sudo raspi-config
# - Missing dependencies: pip3 install -r requirements.txt
```

### Sensors not reading

```bash
# Test I2C bus
sudo i2cdetect -y 1

# Should show device at 0x48 (ADS1115)
# If not, check wiring

# Test hardware
sudo python3 /opt/growmate/scripts/test_hardware.py
```

### Camera not working

```bash
# Test camera
libcamera-hello

# Check camera is enabled
sudo raspi-config
# Interface Options -> Camera -> Enable

# Check cable connection
```

### WiFi connection issues

```bash
# Check WiFi status
nmcli device status

# Check logs
sudo journalctl -u growmate | grep -i wifi

# Re-enter onboarding mode
sudo rm /etc/growmate/config.yaml
sudo systemctl restart growmate
```

### AP mode not working

```bash
# Check hostapd status
sudo systemctl status hostapd

# Check dnsmasq status
sudo systemctl status dnsmasq

# Check configuration
sudo cat /etc/hostapd/hostapd.conf
sudo cat /etc/dnsmasq.conf
```

## Development

### Project Structure

```
rpi-growmate-pods/
├── src/                    # Python source code
│   ├── main.py            # Main application
│   ├── config_manager.py  # Configuration handling
│   ├── sensors.py         # Sensor reading
│   ├── camera_service.py  # Camera capture
│   ├── actuators.py       # Relay control
│   ├── api_client.py      # API communication
│   ├── network_manager.py # WiFi management
│   ├── onboarding_portal.py # Flask web app
│   └── utils.py           # Utilities
├── templates/             # HTML templates
├── static/                # CSS, JS, images
├── config/                # Configuration templates
├── systemd/               # Service files
├── scripts/               # Installation scripts
├── requirements.txt       # Python dependencies
├── PLAN.md               # Implementation plan
└── README.md             # This file
```

### Running Locally

For development without hardware:

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run with mock hardware (TODO: implement mocks)
python3 src/main.py
```

### Testing

```bash
# Test individual modules
python3 -c "from src.config_manager import ConfigManager; print('OK')"

# Test hardware (requires Pi with hardware)
sudo python3 scripts/test_hardware.py
```

## Comparison with ESP32 Version

### Advantages

- 1000x more RAM (512MB vs 520KB)
- Better camera (5MP vs 2MP)
- Full Linux OS (easier debugging)
- Better ADC resolution (16-bit vs 12-bit)
- More flexible configuration

### Disadvantages

- Requires external ADC module (+$5)
- Higher power consumption (~150mA vs ~80mA)
- Higher total cost ($69 vs $40)
- Longer boot time (30-60s vs 1-2s)
- More complex AP mode setup

## License

[Specify your license here]

## Credits

- Original ESP32 implementation: [Link to ESP32 repo]
- Ported to Raspberry Pi Zero W by [Your name]

## Support

For issues and questions:
- GitHub Issues: [Repository URL]
- Documentation: [Link to docs]

## Roadmap

- [ ] Add unit tests
- [ ] Add mock hardware for development
- [ ] Add OTA updates
- [ ] Add web dashboard
- [ ] Add MQTT support
- [ ] Add multiple device support
