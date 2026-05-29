# GrowMate Pods

GrowMate Pods is an automated plant monitoring and care system for Raspberry Pi. It watches your plants, takes pictures, and can water them automatically through a simple cloud API.

## What It Does

- Monitors soil moisture, light levels, temperature, and humidity
- Takes photos of your plants every 15 minutes
- Sends all data to your cloud server
- Waters plants and controls grow lights based on commands from your server
- Works offline - stores data locally when internet is down

## Installation

Install GrowMate on your Raspberry Pi with one command:

```bash
curl -sSL https://raw.githubusercontent.com/FarelRA/rpi-growmate-pods/main/scripts/install.sh | sudo bash
```

Or clone and install manually:

```bash
git clone https://github.com/FarelRA/rpi-growmate-pods.git
cd rpi-growmate-pods
sudo bash scripts/install.sh
```

The installer will set up everything automatically and start the service.

## Hardware You'll Need

- Raspberry Pi Zero W (or any Pi with WiFi)
- Pi Camera Module
- Soil moisture sensor
- Light sensor
- Temperature/humidity sensor (DHT22)
- Water pump and relay
- ADS1115 ADC module (for reading sensors)

Total cost: around $70

See [docs/HARDWARE.md](docs/HARDWARE.md) for detailed parts list and wiring.

## Setup

After installation, connect to the WiFi network `GrowMate-XXXXXX` (password: `growmate`) and open `http://192.168.4.1` in your browser. Enter your WiFi credentials and your API endpoint.

That's it! Your GrowMate will start monitoring your plants.

## Configuration

Edit `/etc/growmate/config.yaml` to customize:

```yaml
api:
  sensor_url: "https://your-api.com/sensors"
  camera_url: "https://your-api.com/camera"

intervals:
  sensor_reading: 15      # seconds
  camera_capture: 900     # seconds

calibration:
  soil_moisture: {min: 0, max: 65535}
  light: {min: 0, max: 65535}
```

Restart the service after changes: `sudo systemctl restart growmate`

## Usage

### Check Status

```bash
sudo systemctl status growmate
```

### View Logs

```bash
sudo journalctl -u growmate -f
```

### Test Hardware

```bash
sudo python3 /opt/growmate/scripts/test_hardware.py
```

## API Format

Your server receives sensor data as JSON:

```json
{
  "deviceId": "growmate-abc123",
  "sensors": [
    {"kind": "soil", "value": 45, "unit": "%"},
    {"kind": "light", "value": 78, "unit": "%"},
    {"kind": "temperature", "value": 25, "unit": "C"}
  ]
}
```

And can send back commands:

```json
{
  "commands": [
    {"kind": "pump", "durationMs": 5000},
    {"kind": "light", "enabled": true}
  ]
}
```

Camera images are uploaded as JPEG files with device ID in the header.

## Troubleshooting

**Service won't start?**
```bash
sudo journalctl -u growmate -n 50
```

**Sensors not working?**
```bash
sudo i2cdetect -y 1
sudo python3 /opt/growmate/scripts/test_hardware.py
```

**Need to change WiFi?**
```bash
sudo rm /etc/growmate/config.yaml
sudo systemctl restart growmate
```

For more help, see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you'd like to change.

Please make sure to test your changes:

```bash
python3 scripts/test_system_integration.py
```

## License

This project is licensed under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.

## Support

- Report bugs: [GitHub Issues](https://github.com/FarelRA/rpi-growmate-pods/issues)
- Ask questions: [GitHub Discussions](https://github.com/FarelRA/rpi-growmate-pods/discussions)
- Documentation: [docs/](docs/)
