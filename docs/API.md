# API Documentation

Complete API reference for GrowMate Pods cloud integration.

## Table of Contents

- [Overview](#overview)
- [Sensor Data Upload](#sensor-data-upload)
- [Camera Image Upload](#camera-image-upload)
- [Command Format](#command-format)
- [Error Handling](#error-handling)
- [Example Implementations](#example-implementations)
- [Best Practices](#best-practices)

## Overview

GrowMate Pods communicates with your cloud server through two HTTPS endpoints:
- **Sensor endpoint:** Receives sensor data and returns commands
- **Camera endpoint:** Receives JPEG images with metadata

### Communication Flow

```
┌─────────────┐                    ┌─────────────┐
│  GrowMate   │                    │  Your API   │
│    Pods     │                    │   Server    │
└──────┬──────┘                    └──────┬──────┘
       │                                  │
       │  POST /sensors (JSON)            │
       ├─────────────────────────────────>│
       │                                  │
       │  Response: commands (JSON)       │
       │<─────────────────────────────────┤
       │                                  │
       │  POST /camera (JPEG)             │
       ├─────────────────────────────────>│
       │                                  │
       │  Response: 200 OK                │
       │<─────────────────────────────────┤
       │                                  │
```

### Configuration

Set your API endpoints in `/etc/growmate/config.yaml`:

```yaml
api:
  sensor_url: "https://api.example.com/sensors"
  camera_url: "https://api.example.com/camera"
```

## Sensor Data Upload

### Endpoint

**URL:** Configured as `api.sensor_url` in config.yaml

**Method:** `POST`

**Content-Type:** `application/json`

**Frequency:** Every 15 seconds (configurable)

### Request Headers

```
Content-Type: application/json
X-Correlation-Id: <uuid>
User-Agent: GrowMate/2.0.0
```

### Request Body

```json
{
  "deviceId": "growmate-b827eb123456",
  "firmwareVersion": "2.0.0",
  "timestamp": "2024-05-29T14:30:00Z",
  "sensors": [
    {
      "kind": "soil",
      "value": 45,
      "unit": "%",
      "raw": 29491
    },
    {
      "kind": "light",
      "value": 78,
      "unit": "%",
      "raw": 51118
    },
    {
      "kind": "water",
      "value": 92,
      "unit": "%",
      "raw": 60292
    },
    {
      "kind": "temperature",
      "value": 25.3,
      "unit": "C"
    },
    {
      "kind": "air",
      "value": 60.5,
      "unit": "%"
    }
  ],
  "currentState": {
    "pumpEnabled": false,
    "lightEnabled": false
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `deviceId` | string | Unique device identifier (MAC-based) |
| `firmwareVersion` | string | Software version (semantic versioning) |
| `timestamp` | string | ISO 8601 timestamp (UTC) |
| `sensors` | array | Array of sensor readings |
| `sensors[].kind` | string | Sensor type: `soil`, `light`, `water`, `temperature`, `air` |
| `sensors[].value` | number | Calibrated value (percentage or degrees) |
| `sensors[].unit` | string | Unit of measurement: `%`, `C` |
| `sensors[].raw` | number | Raw ADC value (0-65535, only for analog sensors) |
| `currentState` | object | Current actuator states |
| `currentState.pumpEnabled` | boolean | Water pump state |
| `currentState.lightEnabled` | boolean | Grow light state |

### Important Notes

- **ADC sensors** (soil, light, water) include `raw` field with 16-bit ADC value
- **DHT22 sensors** (temperature, air) do NOT include `raw` field
- Temperature is always in Celsius
- Percentages are 0-100 (calibrated from raw ADC values)
- `deviceId` format: `growmate-<last 12 chars of MAC address>`

### Response Format

**Success (200 OK):**

```json
{
  "commands": [
    {
      "kind": "pump",
      "durationMs": 5000
    },
    {
      "kind": "light",
      "enabled": true
    }
  ]
}
```

**No commands:**

```json
{
  "commands": []
}
```

### Response Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `commands` | array | Array of commands to execute |
| `commands[].kind` | string | Command type: `pump` or `light` |
| `commands[].durationMs` | number | Pump duration in milliseconds (pump only) |
| `commands[].enabled` | boolean | Light state (light only) |

## Camera Image Upload

### Endpoint

**URL:** Configured as `api.camera_url` in config.yaml

**Method:** `POST`

**Content-Type:** `image/jpeg`

**Frequency:** Every 15 minutes (configurable)

### Request Headers

```
Content-Type: image/jpeg
X-Device-Id: growmate-b827eb123456
X-Correlation-Id: <uuid>
User-Agent: GrowMate/2.0.0
```

### Request Body

Raw JPEG image bytes with embedded EXIF metadata.

**Image specifications:**
- Format: JPEG
- Resolution: 2592x1944 (5MP, configurable)
- Quality: 85% (configurable 50-100)
- Color space: RGB
- Orientation: Landscape

### EXIF Metadata

The JPEG includes embedded EXIF metadata:

| EXIF Tag | Description | Example |
|----------|-------------|---------|
| DateTime | Capture timestamp | `2024:05:29 14:30:00` |
| Make | Device manufacturer | `GrowMate` |
| Model | Device model | `Pods v2.0` |
| ImageDescription | Device ID | `growmate-b827eb123456` |
| UserComment | Sensor readings (JSON) | See below |

**UserComment JSON format:**
```json
{
  "soil": 45,
  "light": 78,
  "water": 92,
  "temperature": 25.3,
  "humidity": 60.5
}
```

### Response Format

**Success (200 OK):**

```json
{
  "status": "success",
  "imageId": "img_abc123"
}
```

**Error (4xx/5xx):**

```json
{
  "error": "Invalid image format",
  "code": "INVALID_FORMAT"
}
```

### Example cURL Request

```bash
curl -X POST https://api.example.com/camera \
  -H "Content-Type: image/jpeg" \
  -H "X-Device-Id: growmate-b827eb123456" \
  -H "X-Correlation-Id: 550e8400-e29b-41d4-a716-446655440000" \
  --data-binary "@/tmp/capture.jpg"
```

## Command Format

Commands are returned in the sensor data upload response.

### Pump Command

Activates water pump for specified duration.

```json
{
  "kind": "pump",
  "durationMs": 5000
}
```

**Fields:**
- `kind`: Must be `"pump"`
- `durationMs`: Duration in milliseconds (1-60000)

**Behavior:**
- Pump activates immediately
- Runs for specified duration
- Automatically shuts off after duration
- Maximum duration: 60 seconds (safety limit)

**Example durations:**
- 1000ms = 1 second
- 5000ms = 5 seconds
- 10000ms = 10 seconds
- 30000ms = 30 seconds

### Light Command

Controls grow light on/off state.

```json
{
  "kind": "light",
  "enabled": true
}
```

**Fields:**
- `kind`: Must be `"light"`
- `enabled`: `true` to turn on, `false` to turn off

**Behavior:**
- Light switches immediately
- Remains in specified state until next command
- State persists across reboots

### Multiple Commands

You can send multiple commands in one response:

```json
{
  "commands": [
    {"kind": "pump", "durationMs": 5000},
    {"kind": "light", "enabled": true}
  ]
}
```

Commands are executed in order.

## Error Handling

### HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response |
| 400 | Bad Request | Check request format |
| 401 | Unauthorized | Check authentication |
| 403 | Forbidden | Check API key/permissions |
| 404 | Not Found | Check endpoint URL |
| 429 | Too Many Requests | Reduce request frequency |
| 500 | Server Error | Retry with backoff |
| 503 | Service Unavailable | Retry with backoff |

### Retry Behavior

GrowMate automatically retries failed uploads:

1. **Exponential backoff:** 1s, 2s, 4s, 8s, 16s, 32s
2. **Jitter:** ±25% random variation
3. **Max attempts:** 6 (configurable)
4. **Circuit breaker:** Opens after 5 consecutive failures

### Offline Queue

When uploads fail, data is stored locally:

- **Sensor data:** Up to 6000 entries (~24 hours at 15s intervals)
- **Images:** Up to 100 images (~24 hours at 15m intervals)
- **Storage:** SQLite database at `/etc/growmate/queue.db`
- **Auto-cleanup:** Entries older than 24 hours are deleted

Queue drains automatically when connectivity returns.

## Example Implementations

### Python (Flask)

```python
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route('/sensors', methods=['POST'])
def sensors():
    data = request.json
    device_id = data['deviceId']
    sensors = data['sensors']
    
    # Process sensor data
    soil = next(s['value'] for s in sensors if s['kind'] == 'soil')
    
    # Decide if watering needed
    commands = []
    if soil < 30:  # Soil too dry
        commands.append({
            'kind': 'pump',
            'durationMs': 5000
        })
    
    return jsonify({'commands': commands})

@app.route('/camera', methods=['POST'])
def camera():
    device_id = request.headers.get('X-Device-Id')
    image_data = request.data
    
    # Save image
    filename = f"{device_id}_{int(time.time())}.jpg"
    with open(f"images/{filename}", 'wb') as f:
        f.write(image_data)
    
    return jsonify({'status': 'success', 'imageId': filename})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')
```

### Node.js (Express)

```javascript
const express = require('express');
const app = express();

app.use(express.json());
app.use(express.raw({ type: 'image/jpeg', limit: '10mb' }));

app.post('/sensors', (req, res) => {
    const { deviceId, sensors } = req.body;
    
    // Process sensor data
    const soil = sensors.find(s => s.kind === 'soil').value;
    
    // Decide if watering needed
    const commands = [];
    if (soil < 30) {
        commands.push({
            kind: 'pump',
            durationMs: 5000
        });
    }
    
    res.json({ commands });
});

app.post('/camera', (req, res) => {
    const deviceId = req.headers['x-device-id'];
    const imageData = req.body;
    
    // Save image
    const filename = `${deviceId}_${Date.now()}.jpg`;
    fs.writeFileSync(`images/${filename}`, imageData);
    
    res.json({ status: 'success', imageId: filename });
});

app.listen(443, () => {
    console.log('API server running on port 443');
});
```

### PHP

```php
<?php
// sensors.php
header('Content-Type: application/json');

$data = json_decode(file_get_contents('php://input'), true);
$deviceId = $data['deviceId'];
$sensors = $data['sensors'];

// Find soil moisture
$soil = null;
foreach ($sensors as $sensor) {
    if ($sensor['kind'] === 'soil') {
        $soil = $sensor['value'];
        break;
    }
}

// Decide if watering needed
$commands = [];
if ($soil < 30) {
    $commands[] = [
        'kind' => 'pump',
        'durationMs' => 5000
    ];
}

echo json_encode(['commands' => $commands]);
?>

<?php
// camera.php
$deviceId = $_SERVER['HTTP_X_DEVICE_ID'];
$imageData = file_get_contents('php://input');

// Save image
$filename = "{$deviceId}_" . time() . ".jpg";
file_put_contents("images/{$filename}", $imageData);

header('Content-Type: application/json');
echo json_encode(['status' => 'success', 'imageId' => $filename]);
?>
```

## Best Practices

### Security

1. **Use HTTPS:** Always use HTTPS endpoints (required)
2. **Validate input:** Check deviceId format, sensor ranges
3. **Rate limiting:** Limit requests per device (e.g., 10/minute)
4. **Authentication:** Consider API keys or JWT tokens
5. **Sanitize commands:** Validate command parameters before returning

### Performance

1. **Respond quickly:** Keep response time < 1 second
2. **Async processing:** Process data asynchronously if needed
3. **Database indexing:** Index deviceId and timestamp fields
4. **Image storage:** Use object storage (S3, etc.) for images
5. **Caching:** Cache device configurations

### Reliability

1. **Idempotency:** Handle duplicate requests gracefully
2. **Error responses:** Return meaningful error messages
3. **Logging:** Log all requests with correlation IDs
4. **Monitoring:** Monitor API health and response times
5. **Backups:** Backup sensor data and images regularly

### Data Management

1. **Retention:** Define data retention policy (e.g., 90 days)
2. **Aggregation:** Aggregate old data for long-term storage
3. **Cleanup:** Regularly delete old data
4. **Compression:** Compress images for storage
5. **Analytics:** Process data for insights and alerts

### Command Safety

1. **Validate duration:** Limit pump duration to reasonable values
2. **Rate limit commands:** Don't water too frequently
3. **State tracking:** Track actuator states to prevent conflicts
4. **Timeouts:** Implement command timeouts
5. **Logging:** Log all commands sent to devices

## Testing

### Test Sensor Endpoint

```bash
curl -X POST https://your-api.com/sensors \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "growmate-test123",
    "firmwareVersion": "2.0.0",
    "timestamp": "2024-05-29T14:30:00Z",
    "sensors": [
      {"kind": "soil", "value": 45, "unit": "%", "raw": 29491},
      {"kind": "light", "value": 78, "unit": "%", "raw": 51118},
      {"kind": "water", "value": 92, "unit": "%", "raw": 60292},
      {"kind": "temperature", "value": 25.3, "unit": "C"},
      {"kind": "air", "value": 60.5, "unit": "%"}
    ],
    "currentState": {
      "pumpEnabled": false,
      "lightEnabled": false
    }
  }'
```

### Test Camera Endpoint

```bash
# Create test image
convert -size 2592x1944 xc:blue test.jpg

# Upload
curl -X POST https://your-api.com/camera \
  -H "Content-Type: image/jpeg" \
  -H "X-Device-Id: growmate-test123" \
  --data-binary "@test.jpg"
```

## Support

For configuration help, see [CONFIGURATION.md](CONFIGURATION.md)

For troubleshooting, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
