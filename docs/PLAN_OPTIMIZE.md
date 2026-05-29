# GrowMate RPI Optimization Plan - PLAN2.md

**Status:** Planning  
**Goal:** Remove all ESP32 constraints, optimize for Raspberry Pi, utilize full hardware capabilities  
**API Compatibility:** External API parity maintained, internal architecture completely redesigned  
**Approach:** Embrace breaking changes, no tech debt

---

## Executive Summary

This plan completely overhauls the GrowMate RPI implementation to remove all ESP32 quirks and constraints. We will leverage the Raspberry Pi's superior hardware (512MB RAM vs 520KB, full Linux OS, better camera) while maintaining external API compatibility with the backend server.

**Key Changes:**
- Remove loop counter timing → Modern async scheduling
- Remove ephemeral camera → Persistent 5MP camera service
- Remove fixed intervals → Flexible configuration
- Add 1-day offline queue → SQLite-based data persistence
- Remove ESP32 memory constraints → Utilize full 512MB RAM
- Simplify web interface → WiFi credentials only (onboarding)
- Add modern error handling → Exponential backoff, circuit breaker
- Add structured logging → JSON logs with rotation

**What Stays (External API Parity):**
- Sensor data JSON format: `{deviceId, firmwareVersion, sensors[], currentState}`
- Sensor kinds: `"soil"`, `"light"`, `"water"`, `"temperature"`, `"air"`
- Camera upload: multipart/form-data with X-Device-Id header
- Command response format: `{commands: [{kind, durationMs/enabled}]}`
- HTTP endpoints and methods

**What Changes (Everything Else):**
- Internal architecture
- Timing mechanisms
- Camera resolution and lifecycle
- Error handling
- Configuration format
- Logging approach
- Data persistence
- Code structure

---

## Current State Analysis - ESP32 Quirks to Remove

### 1. Timing Architecture (MAJOR ISSUE)

**Current Implementation:**
```python
# main.py:53
self.loops_since_camera = 0  # Match ESP32 loop counter approach

# main.py:268-289
camera_period = CAMERA_INTERVAL_SECONDS // SENSOR_INTERVAL_SECONDS
while self.running:
    # Read sensors
    # ...
    self.loops_since_camera += 1
    if self.loops_since_camera >= camera_period:
        # Capture camera
        if success:
            self.loops_since_camera = 0  # Reset only on success
```

**Problems:**
- Loop counter is an ESP32 embedded pattern (no real-time OS)
- Inaccurate timing (drift accumulates)
- Synchronous blocking (can't do concurrent operations)
- Tightly coupled sensor/camera timing
- Difficult to add flexible scheduling

**Target:**
- Async/await architecture with proper scheduling
- Independent sensor and camera schedules
- Concurrent operations (upload while reading sensors)
- Accurate time-based scheduling
- Easy to add new scheduled tasks

### 2. Camera Service (MAJOR ISSUE)

**Current Implementation:**
```python
# main.py:205-220
camera = CameraService()
camera.initialize()  # Init
jpeg_bytes = camera.capture_jpeg()  # Capture
camera.cleanup()  # Deinit immediately
```

**Problems:**
- Ephemeral lifecycle wastes time (init overhead every 15 minutes)
- Limited to 800x600 (SVGA) to match ESP32
- Fixed quality (85)
- No metadata, no advanced features
- Pi Camera v1 can do 2592x1944 (5MP) - we're using 10% of capability!

**Target:**
- Persistent camera service (init once, keep alive)
- Full 5MP resolution (2592x1944)
- Configurable quality
- EXIF metadata (timestamp, device ID, sensor readings)
- Fast captures (no init overhead)
- Support for burst mode, time-lapse (future)

### 3. Memory Constraints (ARTIFICIAL LIMITATION)

**Current Implementation:**
- Conservative patterns designed for 520KB RAM
- No data buffering or queuing
- Immediate upload (no batching)
- No caching
- Minimal in-memory state

**Problems:**
- Pi has 512MB RAM (1000x more than ESP32!)
- We're not utilizing available resources
- No offline operation support
- Data loss during network outages

**Target:**
- SQLite-based offline queue (1 day capacity)
- In-memory caching where beneficial
- Batch uploads when efficient
- Utilize RAM for better performance

### 4. Error Handling (TOO SIMPLE)

**Current Implementation:**
```python
# utils.py:53
@retry(max_attempts=2, delay=1.5)
def upload_with_retry():
    # Fixed 2 attempts, 1.5s delay
```

**Problems:**
- Fixed retry count and delay
- No exponential backoff
- No jitter (thundering herd problem)
- No circuit breaker
- Poor handling of prolonged outages

**Target:**
- Exponential backoff with jitter
- Circuit breaker pattern
- Intelligent retry strategies
- Graceful degradation
- Better error categorization

### 5. Configuration (INFLEXIBLE)

**Current Implementation:**
- YAML file at `/etc/growmate/config.yaml`
- Requires service restart for changes
- Limited options
- No validation
- No hot-reload

**Problems:**
- Downtime for config changes
- Difficult to tune and debug
- No runtime adjustments
- Poor user experience

**Target:**
- Hot-reload configuration (no restart)
- Comprehensive validation
- More granular settings
- Feature flags
- Better defaults

### 6. Synchronous Architecture (BLOCKING)

**Current Implementation:**
```python
# main.py:256-310
def run(self):
    while self.running:
        sensor_data = self.read_sensors()  # Blocking
        self.upload_sensors(sensor_data)   # Blocking
        if camera_due:
            image = self.capture_camera()  # Blocking
            self.upload_camera(image)      # Blocking
        time.sleep(interval)               # Blocking
```

**Problems:**
- Everything blocks everything else
- Can't upload while reading sensors
- Can't capture camera while uploading
- Poor resource utilization
- Slow response to commands

**Target:**
- Async/await architecture
- Concurrent operations
- Non-blocking I/O
- Better responsiveness
- Efficient resource usage

### 7. Logging (BASIC)

**Current Implementation:**
- Simple text logging
- Fixed format
- No structure
- No rotation
- No remote logging

**Problems:**
- Difficult to parse and analyze
- No integration with log aggregators
- Logs can fill disk
- No correlation between related events

**Target:**
- Structured JSON logging
- Per-module log levels
- Automatic rotation
- Correlation IDs
- Remote logging support (optional)

### 8. Web Interface (OVER-ENGINEERED FOR ONBOARDING)

**Current Implementation:**
- Flask app with templates
- Network scanning
- Configuration form
- Favicon serving
- Event-based completion signaling

**Problems:**
- More complex than needed for just WiFi credentials
- Uses threading and events (ESP32 pattern)
- Could be simpler

**Target:**
- Minimal web interface for WiFi credentials ONLY
- Simple form: SSID and password
- No network scanning (user knows their WiFi)
- Clean, fast, minimal dependencies

---

## Target Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                     GrowMate Application                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Scheduler  │  │  Data Queue  │  │ Config Watch │      │
│  │  (APScheduler)│  │   (SQLite)   │  │  (Watchdog)  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Async Task Manager                       │   │
│  │  - Sensor reading task (every 15s)                   │   │
│  │  - Camera capture task (every 15m)                   │   │
│  │  - Upload task (continuous, processes queue)         │   │
│  │  - Housekeeping task (every 1s)                      │   │
│  │  - Health check task (every 60s)                     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Sensors   │  │   Camera    │  │  Actuators  │         │
│  │  (Persistent)│  │ (Persistent)│  │ (Persistent)│         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Network Layer                            │   │
│  │  - API Client (async HTTP with connection pool)      │   │
│  │  - Circuit Breaker                                    │   │
│  │  - Exponential Backoff                                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              Onboarding Web Interface (Minimal)              │
│  - Single page: WiFi SSID + Password form                   │
│  - Saves to config, triggers restart                         │
└─────────────────────────────────────────────────────────────┘
```

### Component Architecture

#### 1. Scheduler (APScheduler)
- Replaces loop counter approach
- Manages all periodic tasks
- Accurate time-based scheduling
- Independent task schedules
- Easy to add new tasks

#### 2. Data Queue (SQLite)
- Stores failed uploads (sensor data + images)
- 1-day capacity (~96 sensor readings + 96 images)
- Automatic cleanup of old entries
- FIFO processing
- Atomic operations

#### 3. Config Watcher (Watchdog)
- Monitors config file for changes
- Hot-reload without restart
- Validates before applying
- Logs config changes

#### 4. Async Task Manager
- Coordinates all async tasks
- Handles task lifecycle
- Error handling and recovery
- Graceful shutdown

#### 5. Persistent Services
- Sensors: Initialize once, read on demand
- Camera: Initialize once, capture on demand (5MP)
- Actuators: Always running, command-driven

#### 6. Network Layer
- Async HTTP client (aiohttp)
- Connection pooling
- Circuit breaker pattern
- Exponential backoff with jitter
- Request/response logging

---

## Implementation Phases

### Phase 1: Foundation - Async Architecture & Scheduling (CRITICAL)

**Goal:** Replace synchronous loop with async architecture and proper scheduling

**Duration:** 4-5 days

#### Tasks:

1. **Setup Async Framework**
   - Add dependencies: `asyncio`, `aiohttp`, `APScheduler`
   - Create async main loop
   - Setup event loop and signal handling
   - Add graceful shutdown mechanism

2. **Implement Scheduler**
   - Replace loop counter with APScheduler
   - Create independent schedules:
     - Sensor reading: every 15s (configurable)
     - Camera capture: every 15m (configurable)
     - Upload processing: continuous
     - Housekeeping: every 1s
     - Health check: every 60s
   - Add job persistence (survive restarts)
   - Add job monitoring and error handling

3. **Convert Components to Async**
   - `APIClient`: Convert to async with aiohttp
   - `SensorReader`: Make async-compatible
   - `CameraService`: Make async-compatible
   - `ActuatorController`: Make async-compatible
   - `NetworkManager`: Make async-compatible

4. **Async Task Coordination**
   - Create task manager
   - Handle concurrent operations
   - Implement task cancellation
   - Add task health monitoring

**Deliverables:**
- Async main application loop
- APScheduler integration
- All components async-compatible
- Independent task scheduling
- Graceful shutdown

**Testing:**
- Unit tests for async components
- Integration tests for task coordination
- Timing accuracy tests
- Concurrent operation tests

**Breaking Changes:**
- Main application structure completely rewritten
- Component interfaces changed to async
- No backward compatibility with old main.py

---

### Phase 2: Camera Enhancement - Full 5MP (HIGH VALUE)

**Goal:** Utilize full Pi Camera v1 capabilities (5MP)

**Duration:** 2-3 days

#### Tasks:

1. **Persistent Camera Service**
   - Remove ephemeral lifecycle (init/capture/cleanup)
   - Initialize camera once at startup
   - Keep camera alive throughout application lifetime
   - Add proper cleanup on shutdown
   - Handle camera errors gracefully (reinitialize if needed)

2. **Increase Resolution to 5MP**
   - Change resolution: 800x600 → 2592x1944
   - Update configuration: `CAMERA_WIDTH = 2592`, `CAMERA_HEIGHT = 1944`
   - Test image sizes (expect ~1-2MB per image)
   - Verify upload performance

3. **Configurable Quality**
   - Add config option: `camera.quality` (50-100)
   - Default: 85 (good balance)
   - Presets: low (70), medium (85), high (95)
   - Allow runtime changes via config reload

4. **Image Metadata (EXIF)**
   - Add timestamp to EXIF
   - Add device ID to EXIF
   - Add sensor readings to EXIF (optional)
   - Add GPS coordinates (if available)

5. **Performance Optimization**
   - Measure capture time (should be <2s for 5MP)
   - Optimize buffer handling
   - Add capture timeout
   - Monitor memory usage

**Deliverables:**
- Persistent camera service
- Full 5MP captures
- Configurable quality
- EXIF metadata
- Performance benchmarks

**Testing:**
- Camera initialization tests
- Capture quality tests
- Performance tests (capture time, memory)
- Long-running stability tests
- Error recovery tests

**Breaking Changes:**
- Camera resolution increased (larger files)
- Camera lifecycle changed (persistent)
- Configuration format updated

**External API Impact:**
- None (same upload format, just larger images)
- Backend may need to handle larger files (~1-2MB vs ~100KB)

---

### Phase 3: Data Queue - Offline Operation (RELIABILITY)

**Goal:** Add 1-day offline queue for sensor data and images

**Duration:** 3-4 days

#### Tasks:

1. **SQLite Queue Implementation**
   - Create database schema (see Data Structures section)
   - Tables: `sensor_queue`, `image_queue`, `metadata`
   - Indexes for efficient queries
   - Automatic cleanup of old entries (>24 hours)

2. **Queue Operations**
   - `enqueue_sensor_data(data)`: Add sensor reading to queue
   - `enqueue_image(image_bytes, metadata)`: Add image to queue
   - `dequeue_next()`: Get next item to upload (FIFO)
   - `mark_uploaded(id)`: Remove from queue after successful upload
   - `get_queue_stats()`: Return queue depth, oldest entry, etc.

3. **Upload Processor**
   - Continuous async task
   - Process queue items in order
   - Retry failed uploads with exponential backoff
   - Circuit breaker integration
   - Rate limiting (don't overwhelm server)

4. **Queue Management**
   - Monitor queue depth
   - Warn if queue approaching capacity
   - Automatic cleanup of old entries
   - Vacuum database periodically
   - Handle disk space issues

5. **Integration with Main Loop**
   - Sensor reading → enqueue → upload processor handles it
   - Camera capture → enqueue → upload processor handles it
   - Decouple data collection from upload
   - Continue collecting even if uploads fail

**Deliverables:**
- SQLite-based queue
- Queue operations API
- Upload processor task
- Queue management utilities
- Monitoring and alerts

**Testing:**
- Queue operations tests
- Offline operation tests (disconnect network)
- Queue capacity tests (fill to 1 day)
- Recovery tests (restart with full queue)
- Performance tests (queue throughput)

**Breaking Changes:**
- Upload logic completely rewritten
- Data flow changed (collect → queue → upload)
- Database added as dependency

**External API Impact:**
- None (uploads still use same format)
- May see delayed uploads during outages (expected behavior)

---

### Phase 4: Error Handling - Exponential Backoff & Circuit Breaker (ROBUSTNESS)

**Goal:** Implement industry-standard error handling patterns

**Duration:** 2-3 days

#### Tasks:

1. **Exponential Backoff with Jitter**
   - Replace fixed retry (2 attempts, 1.5s)
   - Implement exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s (max)
   - Add random jitter (±25%) to prevent thundering herd
   - Configurable max attempts and max delay
   - Per-operation backoff state

2. **Circuit Breaker Pattern**
   - States: CLOSED (normal), OPEN (failing), HALF_OPEN (testing)
   - Thresholds:
     - Open circuit after 5 consecutive failures
     - Half-open after 60s
     - Close after 2 consecutive successes
   - Per-endpoint circuit breakers (sensor API, camera API)
   - Metrics and monitoring

3. **Error Categorization**
   - Transient errors (retry): network timeout, 5xx errors
   - Permanent errors (don't retry): 4xx errors, invalid data
   - Rate limit errors (backoff longer): 429 errors
   - Circuit open errors (queue and wait)

4. **Graceful Degradation**
   - Continue sensor reading even if uploads fail
   - Continue camera capture even if uploads fail
   - Queue everything for later
   - Log errors but don't crash

5. **Health Monitoring**
   - Track success/failure rates
   - Track circuit breaker states
   - Track queue depth
   - Expose metrics for monitoring

**Deliverables:**
- Exponential backoff implementation
- Circuit breaker implementation
- Error categorization logic
- Health monitoring
- Metrics collection

**Testing:**
- Backoff timing tests
- Circuit breaker state transition tests
- Error categorization tests
- Failure scenario tests
- Recovery tests

**Breaking Changes:**
- Retry logic completely rewritten
- Error handling patterns changed
- New dependencies (circuit breaker library)

**External API Impact:**
- None (better handling of API failures)
- May reduce load on server during outages

---

### Phase 5: Configuration - Hot-Reload & Validation (FLEXIBILITY)

**Goal:** Enable configuration changes without restart

**Duration:** 2 days

#### Tasks:

1. **Config File Watcher**
   - Use `watchdog` library to monitor config file
   - Detect file changes
   - Trigger reload on change
   - Debounce rapid changes (wait 1s after last change)

2. **Config Validation**
   - JSON Schema or Pydantic models
   - Validate all fields
   - Check ranges and constraints
   - Provide helpful error messages
   - Reject invalid configs (keep current)

3. **Hot-Reload Logic**
   - Load new config
   - Validate new config
   - Apply changes to running components
   - Update scheduler jobs if intervals changed
   - Update camera settings if changed
   - Log all config changes

4. **Reloadable Settings**
   - Sensor interval
   - Camera interval
   - Camera quality
   - API endpoints
   - Retry settings
   - Log levels
   - Feature flags

5. **Non-Reloadable Settings**
   - Device ID (requires restart)
   - WiFi credentials (requires restart)
   - Database path (requires restart)

**Deliverables:**
- Config file watcher
- Config validation
- Hot-reload implementation
- Documentation of reloadable settings

**Testing:**
- Config change detection tests
- Validation tests (valid/invalid configs)
- Hot-reload tests (verify changes applied)
- Edge case tests (rapid changes, invalid changes)

**Breaking Changes:**
- Config loading logic changed
- Config validation added
- New dependencies (watchdog, pydantic)

**External API Impact:**
- None

---

### Phase 6: Logging - Structured JSON Logs (OBSERVABILITY)

**Goal:** Implement structured logging for better analysis

**Duration:** 1-2 days

#### Tasks:

1. **Structured Logging Setup**
   - Use `structlog` or `python-json-logger`
   - JSON format for all logs
   - Include standard fields: timestamp, level, logger, message
   - Include context fields: device_id, correlation_id, component

2. **Per-Module Log Levels**
   - Configure log levels per module in config
   - Default: INFO for all
   - Allow runtime changes via config reload
   - Examples:
     - `logging.sensors: DEBUG`
     - `logging.camera: INFO`
     - `logging.api_client: WARNING`

3. **Log Rotation**
   - Use `logging.handlers.RotatingFileHandler`
   - Rotate by size: 10MB per file
   - Keep 5 backup files
   - Total: 50MB max
   - Automatic cleanup

4. **Correlation IDs**
   - Generate correlation ID for each sensor reading cycle
   - Include in all related log entries
   - Include in API requests (X-Correlation-Id header)
   - Helps trace operations across components

5. **Log Destinations**
   - Console: Human-readable format (development)
   - File: JSON format (production)
   - Systemd journal: Structured format
   - Optional: Remote logging (syslog, Loki)

**Deliverables:**
- Structured JSON logging
- Per-module log levels
- Log rotation
- Correlation IDs
- Multiple log destinations

**Testing:**
- Log format tests
- Log rotation tests
- Log level tests
- Correlation ID tests

**Breaking Changes:**
- Log format changed (JSON instead of text)
- Log parsing tools may need updates

**External API Impact:**
- None (internal logging only)

---

### Phase 7: Web Interface - Minimal Onboarding (SIMPLIFICATION)

**Goal:** Simplify web interface to ONLY WiFi credentials

**Duration:** 1 day

#### Tasks:

1. **Simplify Onboarding Page**
   - Remove network scanning (user knows their WiFi)
   - Single form with 2 fields:
     - WiFi SSID (text input)
     - WiFi Password (password input)
   - Submit button
   - Simple, clean design
   - No JavaScript required

2. **Remove Unnecessary Features**
   - Remove `/api/networks` endpoint
   - Remove network scanning logic
   - Remove complex event signaling
   - Remove threading complexity
   - Keep only: `/` (form) and `/api/config` (POST)

3. **Streamline Backend**
   - Simple Flask app (or even simpler: http.server)
   - POST handler: save config, trigger restart
   - No threading, no events
   - Minimal dependencies

4. **AP Mode Management**
   - Keep existing AP mode logic
   - SSID: `GrowMate-XXXXXX`
   - Password: `growmate`
   - IP: `192.168.4.1`
   - Automatic switch to client mode after config

**Deliverables:**
- Simplified onboarding page (2 fields only)
- Minimal backend (no unnecessary features)
- Clean, fast, reliable

**Testing:**
- Onboarding flow tests
- Form submission tests
- Config save tests
- AP mode tests

**Breaking Changes:**
- Network scanning removed
- Web interface simplified
- Some endpoints removed

**External API Impact:**
- None (onboarding is local only)

---

## Data Structures & Schemas

### SQLite Queue Schema

```sql
-- Sensor data queue
CREATE TABLE sensor_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_id TEXT NOT NULL,
    firmware_version TEXT NOT NULL,
    sensor_data TEXT NOT NULL,  -- JSON string
    current_state TEXT NOT NULL,  -- JSON string
    retry_count INTEGER DEFAULT 0,
    last_retry_at TIMESTAMP,
    status TEXT DEFAULT 'pending'  -- pending, uploading, failed
);

CREATE INDEX idx_sensor_queue_status ON sensor_queue(status);
CREATE INDEX idx_sensor_queue_created_at ON sensor_queue(created_at);

-- Image queue
CREATE TABLE image_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_id TEXT NOT NULL,
    image_data BLOB NOT NULL,  -- JPEG bytes
    image_size INTEGER NOT NULL,  -- bytes
    metadata TEXT,  -- JSON string (EXIF, sensor readings, etc.)
    retry_count INTEGER DEFAULT 0,
    last_retry_at TIMESTAMP,
    status TEXT DEFAULT 'pending'  -- pending, uploading, failed
);

CREATE INDEX idx_image_queue_status ON image_queue(status);
CREATE INDEX idx_image_queue_created_at ON image_queue(created_at);

-- Queue metadata
CREATE TABLE queue_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Store queue statistics
INSERT INTO queue_metadata (key, value) VALUES 
    ('total_sensor_uploads', '0'),
    ('total_image_uploads', '0'),
    ('total_failures', '0'),
    ('last_successful_upload', NULL);
```

**Queue Capacity Calculation:**
- 1 day = 24 hours
- Sensor readings: every 15s = 4 per minute = 240 per hour = 5,760 per day
- Camera captures: every 15m = 4 per hour = 96 per day
- Sensor data size: ~500 bytes per reading
- Image size: ~1.5MB per image (5MP JPEG)
- Total storage: (5,760 × 500 bytes) + (96 × 1.5MB) = 2.88MB + 144MB = ~147MB

**Cleanup Policy:**
- Delete entries older than 24 hours
- Run cleanup every hour
- Vacuum database weekly

---

### Configuration Schema (YAML)

```yaml
# /etc/growmate/config.yaml
version: 5  # Increment for breaking changes

device:
  id: "growmate-b827eb123456"  # Auto-generated from MAC

network:
  provisioned: true
  wifi_ssid: "YourNetwork"
  wifi_password: "YourPassword"

api:
  sensor_url: "https://avid-mammoth-766.convex.site/api/sensors"
  camera_url: "https://avid-mammoth-766.convex.site/api/camera"
  timeout_sensor: 12.0  # seconds
  timeout_camera: 45.0  # seconds

intervals:
  sensor_reading: 15  # seconds (hot-reloadable)
  camera_capture: 900  # seconds (hot-reloadable)

camera:
  width: 2592  # 5MP (hot-reloadable)
  height: 1944  # 5MP (hot-reloadable)
  quality: 85  # 0-100 (hot-reloadable)
  add_exif: true  # Add metadata to images (hot-reloadable)

calibration:
  soil: {min: 0, max: 65535}
  light: {min: 0, max: 65535}
  water: {min: 0, max: 65535}

sensors:
  enable_dht22: true
  adc_samples: 8  # Number of samples to average
  adc_sample_delay: 0.01  # seconds between samples

queue:
  enabled: true
  max_age_hours: 24  # Delete entries older than this
  max_sensor_entries: 6000  # ~1 day at 15s intervals
  max_image_entries: 100  # ~1 day at 15m intervals
  cleanup_interval: 3600  # seconds (1 hour)

retry:
  max_attempts: 6  # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s
  initial_delay: 1.0  # seconds
  max_delay: 32.0  # seconds
  jitter: 0.25  # ±25% random jitter

circuit_breaker:
  failure_threshold: 5  # Open circuit after N failures
  recovery_timeout: 60  # seconds in OPEN state before HALF_OPEN
  success_threshold: 2  # Close circuit after N successes in HALF_OPEN

logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "json"  # json or text
  file: "/var/log/growmate/growmate.log"
  max_bytes: 10485760  # 10MB
  backup_count: 5
  modules:  # Per-module log levels (hot-reloadable)
    sensors: "INFO"
    camera: "INFO"
    api_client: "INFO"
    queue: "INFO"
    scheduler: "INFO"

features:
  offline_queue: true
  hot_reload: true
  structured_logging: true
  circuit_breaker: true
```

**Configuration Validation Rules:**
- `intervals.sensor_reading`: 5-300 seconds
- `intervals.camera_capture`: 60-3600 seconds
- `camera.quality`: 50-100
- `camera.width` × `camera.height`: max 5MP (2592×1944)
- `retry.max_attempts`: 1-10
- `queue.max_age_hours`: 1-168 (1 week max)

---

### External API Specification (UNCHANGED)

These API contracts MUST remain unchanged for backend compatibility.

#### 1. Sensor Data Upload

**Endpoint:** POST to `api.sensor_url`

**Headers:**
```
Content-Type: application/json
```

**Request Body:**
```json
{
  "deviceId": "growmate-b827eb123456",
  "firmwareVersion": "2.0.0",
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
      "value": 25,
      "unit": "C"
    },
    {
      "kind": "air",
      "value": 60,
      "unit": "%"
    }
  ],
  "currentState": {
    "pumpEnabled": false,
    "lightEnabled": false
  }
}
```

**Response:**
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

**Notes:**
- ADC sensors (soil, light, water) include `raw` field
- DHT22 sensors (temperature, air) do NOT include `raw` field
- All sensors include `unit` field
- Sensor kinds are fixed: "soil", "light", "water", "temperature", "air"

#### 2. Camera Image Upload

**Endpoint:** POST to `api.camera_url`

**Headers:**
```
Content-Type: multipart/form-data
X-Device-Id: growmate-b827eb123456
```

**Form Data:**
- Field name: `image`
- Content: JPEG image bytes
- Filename: `capture.jpg` (optional)

**Response:**
```json
{
  "success": true,
  "message": "Image uploaded successfully"
}
```

**Notes:**
- Image size will increase from ~100KB (800×600) to ~1-2MB (2592×1944)
- Backend must handle larger files
- Upload timeout increased to 45s (already configured)

---

## Technical Specifications

### Async Architecture

**Event Loop:**
- Use `asyncio` for async/await
- Single event loop for entire application
- Graceful shutdown on SIGTERM/SIGINT

**Task Management:**
```python
async def main():
    # Create tasks
    sensor_task = asyncio.create_task(sensor_reading_loop())
    camera_task = asyncio.create_task(camera_capture_loop())
    upload_task = asyncio.create_task(upload_processor_loop())
    housekeeping_task = asyncio.create_task(housekeeping_loop())
    
    # Wait for shutdown signal
    await shutdown_event.wait()
    
    # Cancel all tasks
    for task in [sensor_task, camera_task, upload_task, housekeeping_task]:
        task.cancel()
    
    # Wait for tasks to finish
    await asyncio.gather(*tasks, return_exceptions=True)
```

**Scheduling:**
- Use APScheduler with AsyncIOScheduler
- Jobs run in event loop (no threading)
- Job persistence for restart recovery

**Concurrency:**
- Sensor reading and upload can happen concurrently
- Camera capture and upload can happen concurrently
- Multiple uploads can happen concurrently (with rate limiting)

---

### Camera Service Specification

**Initialization:**
```python
class CameraService:
    def __init__(self, config):
        self.config = config
        self.camera = None
        self.initialized = False
    
    async def initialize(self):
        """Initialize camera once at startup"""
        self.camera = Picamera2()
        config = self.camera.create_still_configuration(
            main={"size": (self.config.width, self.config.height)},
            buffer_count=2  # Double buffering
        )
        self.camera.configure(config)
        self.camera.start()
        self.initialized = True
    
    async def capture_jpeg(self) -> bytes:
        """Capture image (fast, no init overhead)"""
        if not self.initialized:
            await self.initialize()
        
        stream = io.BytesIO()
        self.camera.capture_file(stream, format='jpeg')
        return stream.getvalue()
    
    async def cleanup(self):
        """Cleanup on shutdown"""
        if self.camera:
            self.camera.stop()
            self.camera.close()
```

**Performance Targets:**
- Initialization: <3s (one-time cost)
- Capture: <2s (5MP JPEG)
- Memory: <50MB for camera buffers

---

### Queue Processor Specification

**Upload Processor:**
```python
async def upload_processor_loop():
    """Continuously process upload queue"""
    while True:
        try:
            # Get next item from queue
            item = await queue.dequeue_next()
            
            if item is None:
                # Queue empty, wait a bit
                await asyncio.sleep(1)
                continue
            
            # Upload with retry and circuit breaker
            success = await upload_with_retry(item)
            
            if success:
                await queue.mark_uploaded(item.id)
            else:
                await queue.mark_failed(item.id)
            
        except Exception as e:
            logger.error(f"Upload processor error: {e}")
            await asyncio.sleep(5)
```

**Rate Limiting:**
- Max 10 concurrent uploads
- Max 100 uploads per minute
- Backoff if server returns 429 (rate limit)

---

### Circuit Breaker Specification

**States:**
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests fail immediately
- HALF_OPEN: Testing recovery, limited requests pass through

**State Transitions:**
```
CLOSED --[5 failures]--> OPEN
OPEN --[60s timeout]--> HALF_OPEN
HALF_OPEN --[2 successes]--> CLOSED
HALF_OPEN --[1 failure]--> OPEN
```

**Implementation:**
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60, success_threshold=2):
        self.state = "CLOSED"
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
    
    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                self.success_count = 0
            else:
                raise CircuitBreakerOpenError()
        
        try:
            result = await func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise
    
    def on_success(self):
        if self.state == "HALF_OPEN":
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = "CLOSED"
                self.failure_count = 0
        elif self.state == "CLOSED":
            self.failure_count = 0
    
    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == "HALF_OPEN":
            self.state = "OPEN"
        elif self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
```

---

### Exponential Backoff Specification

**Algorithm:**
```python
async def exponential_backoff_retry(func, max_attempts=6, initial_delay=1.0, max_delay=32.0, jitter=0.25):
    """Retry with exponential backoff and jitter"""
    for attempt in range(max_attempts):
        try:
            return await func()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise  # Last attempt, give up
            
            # Calculate delay: 2^attempt * initial_delay
            delay = min(initial_delay * (2 ** attempt), max_delay)
            
            # Add jitter: ±25%
            jitter_amount = delay * jitter * (2 * random.random() - 1)
            delay += jitter_amount
            
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay:.2f}s: {e}")
            await asyncio.sleep(delay)
```

**Example Delays (with jitter):**
- Attempt 1: 1s ± 0.25s = 0.75-1.25s
- Attempt 2: 2s ± 0.5s = 1.5-2.5s
- Attempt 3: 4s ± 1s = 3-5s
- Attempt 4: 8s ± 2s = 6-10s
- Attempt 5: 16s ± 4s = 12-20s
- Attempt 6: 32s ± 8s = 24-40s

---

## Testing Strategy

### Unit Tests

**Coverage Target:** 80%+ for new code

**Test Categories:**

1. **Async Components**
   - Test async functions with `pytest-asyncio`
   - Mock external dependencies (sensors, camera, network)
   - Test concurrent operations
   - Test cancellation and cleanup

2. **Queue Operations**
   - Test enqueue/dequeue operations
   - Test queue capacity limits
   - Test cleanup of old entries
   - Test concurrent access
   - Test database integrity

3. **Circuit Breaker**
   - Test state transitions
   - Test failure counting
   - Test recovery timeout
   - Test success threshold

4. **Exponential Backoff**
   - Test delay calculations
   - Test jitter randomness
   - Test max attempts
   - Test max delay cap

5. **Configuration**
   - Test config loading
   - Test config validation
   - Test hot-reload
   - Test invalid configs

6. **Camera Service**
   - Test initialization
   - Test capture (with mock camera)
   - Test error handling
   - Test cleanup

### Integration Tests

**Test Scenarios:**

1. **End-to-End Flow**
   - Start application
   - Read sensors
   - Capture camera
   - Upload data
   - Process commands
   - Verify all components work together

2. **Offline Operation**
   - Disconnect network
   - Continue collecting data
   - Verify queue fills up
   - Reconnect network
   - Verify queue drains

3. **Error Recovery**
   - Simulate API failures
   - Verify retry logic
   - Verify circuit breaker
   - Verify recovery

4. **Configuration Changes**
   - Change config file
   - Verify hot-reload
   - Verify new settings applied
   - Verify no restart needed

5. **Long-Running Stability**
   - Run for 24+ hours
   - Monitor memory usage
   - Monitor queue depth
   - Verify no leaks or crashes

### Hardware Tests

**On Actual Raspberry Pi:**

1. **Sensor Reading**
   - Test all sensors (ADC, DHT22)
   - Verify calibration
   - Test error handling

2. **Camera Capture**
   - Test 5MP captures
   - Verify image quality
   - Measure capture time
   - Test memory usage

3. **Actuator Control**
   - Test pump control
   - Test light control
   - Verify safety interlocks

4. **Network Operations**
   - Test WiFi connection
   - Test AP mode
   - Test uploads
   - Test onboarding

### Performance Tests

**Benchmarks:**

1. **Camera Performance**
   - Capture time: <2s for 5MP
   - Memory usage: <50MB
   - No memory leaks over 100 captures

2. **Queue Performance**
   - Enqueue: <10ms
   - Dequeue: <10ms
   - Query: <50ms
   - Cleanup: <1s for 1000 entries

3. **Upload Performance**
   - Sensor upload: <2s
   - Image upload: <10s (5MP)
   - Concurrent uploads: 10+ simultaneous

4. **Startup Performance**
   - Cold start: <10s
   - Component initialization: <5s
   - First sensor reading: <15s

### Load Tests

**Stress Scenarios:**

1. **Queue Capacity**
   - Fill queue to 1-day capacity
   - Verify performance doesn't degrade
   - Verify cleanup works

2. **Rapid Config Changes**
   - Change config every second
   - Verify hot-reload handles it
   - Verify no crashes

3. **Network Instability**
   - Intermittent connectivity
   - Verify retry logic
   - Verify queue management

---

## Migration Guide

### From Current Version to Optimized Version

**Breaking Changes:**

1. **Configuration File Format**
   - Old: Version 4
   - New: Version 5
   - Changes: New sections (queue, retry, circuit_breaker, logging)
   - Migration: Automatic upgrade on first run

2. **Database Added**
   - New: SQLite database at `/var/lib/growmate/queue.db`
   - Migration: Created automatically on first run
   - Permissions: `growmate` user must have write access

3. **Log Format**
   - Old: Text logs
   - New: JSON logs
   - Migration: Update log parsing tools if any

4. **Python Version**
   - Old: Python 3.7+
   - New: Python 3.9+ (for async features)
   - Migration: Update system Python or use virtual environment

5. **Dependencies**
   - New: `aiohttp`, `APScheduler`, `watchdog`, `structlog`
   - Migration: Run `pip install -r requirements.txt`

**Migration Steps:**

1. **Backup Current System**
   ```bash
   sudo systemctl stop growmate
   sudo cp /etc/growmate/config.yaml /etc/growmate/config.yaml.backup
   sudo journalctl -u growmate > /tmp/growmate-logs-backup.txt
   ```

2. **Update Code**
   ```bash
   cd /opt/growmate
   git pull origin main
   sudo pip3 install -r requirements.txt
   ```

3. **Migrate Configuration**
   ```bash
   # Automatic migration script
   sudo python3 /opt/growmate/scripts/migrate_config.py
   ```

4. **Create Database Directory**
   ```bash
   sudo mkdir -p /var/lib/growmate
   sudo chown growmate:growmate /var/lib/growmate
   sudo chmod 755 /var/lib/growmate
   ```

5. **Update Systemd Service**
   ```bash
   sudo cp systemd/growmate.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

6. **Start New Version**
   ```bash
   sudo systemctl start growmate
   sudo journalctl -u growmate -f
   ```

7. **Verify Operation**
   ```bash
   # Check service status
   sudo systemctl status growmate
   
   # Check queue database
   sudo sqlite3 /var/lib/growmate/queue.db "SELECT COUNT(*) FROM sensor_queue;"
   
   # Check logs
   sudo tail -f /var/log/growmate/growmate.log
   ```

**Rollback Plan:**

If issues occur, rollback to previous version:

```bash
# Stop new version
sudo systemctl stop growmate

# Restore old config
sudo cp /etc/growmate/config.yaml.backup /etc/growmate/config.yaml

# Checkout old version
cd /opt/growmate
git checkout v1.0  # Previous stable version

# Restart
sudo systemctl start growmate
```

---

## Dependencies & Requirements

### System Requirements

**Hardware:**
- Raspberry Pi Zero W (or better)
- 512MB RAM minimum
- 1GB free disk space (for queue and logs)
- Pi Camera Module v1 (5MP)
- ADS1115 ADC
- DHT22 sensor
- Relay module (2-channel)

**Operating System:**
- Raspberry Pi OS Lite (Debian 11+ / Bullseye+)
- Python 3.9 or higher
- systemd for service management

### Python Dependencies

**Core:**
```
# requirements.txt
asyncio>=3.4.3
aiohttp>=3.8.0
APScheduler>=3.10.0
watchdog>=3.0.0
structlog>=23.1.0
python-json-logger>=2.0.0

# Existing dependencies
PyYAML>=6.0
picamera2>=0.3.0
adafruit-circuitpython-ads1x15>=2.2.0
adafruit-circuitpython-dht>=3.7.0
gpiozero>=1.6.2
requests>=2.28.0  # Keep for backward compatibility, migrate to aiohttp
Flask>=2.3.0  # Simplified for onboarding only
```

**Development:**
```
# requirements-dev.txt
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
pytest-mock>=3.11.0
black>=23.7.0
flake8>=6.1.0
mypy>=1.5.0
```

### System Dependencies

```bash
# APT packages
sudo apt install -y \
    python3.9 \
    python3-pip \
    python3-dev \
    i2c-tools \
    libgpiod2 \
    python3-libgpiod \
    libcamera-apps \
    python3-libcamera \
    python3-picamera2 \
    sqlite3 \
    libsqlite3-dev
```

---

## Timeline & Milestones

### Phase 1: Foundation (Week 1)
**Duration:** 4-5 days

**Milestones:**
- Day 1-2: Async architecture setup, event loop
- Day 3: APScheduler integration, task management
- Day 4: Convert components to async
- Day 5: Testing and debugging

**Deliverable:** Working async application with proper scheduling

### Phase 2: Camera Enhancement (Week 1-2)
**Duration:** 2-3 days

**Milestones:**
- Day 1: Persistent camera service, 5MP resolution
- Day 2: Configurable quality, EXIF metadata
- Day 3: Testing and performance optimization

**Deliverable:** Full 5MP camera with metadata

### Phase 3: Data Queue (Week 2)
**Duration:** 3-4 days

**Milestones:**
- Day 1: SQLite schema, queue operations
- Day 2: Upload processor, queue management
- Day 3: Integration with main loop
- Day 4: Testing offline operation

**Deliverable:** 1-day offline queue working

### Phase 4: Error Handling (Week 2-3)
**Duration:** 2-3 days

**Milestones:**
- Day 1: Exponential backoff implementation
- Day 2: Circuit breaker implementation
- Day 3: Integration and testing

**Deliverable:** Robust error handling

### Phase 5: Configuration (Week 3)
**Duration:** 2 days

**Milestones:**
- Day 1: Config watcher, validation
- Day 2: Hot-reload implementation, testing

**Deliverable:** Hot-reload configuration

### Phase 6: Logging (Week 3)
**Duration:** 1-2 days

**Milestones:**
- Day 1: Structured logging setup
- Day 2: Log rotation, correlation IDs

**Deliverable:** JSON structured logging

### Phase 7: Web Interface (Week 3)
**Duration:** 1 day

**Milestones:**
- Day 1: Simplify onboarding page, remove unnecessary features

**Deliverable:** Minimal onboarding interface

### Testing & Polish (Week 4)
**Duration:** 5 days

**Milestones:**
- Day 1-2: Integration testing
- Day 3: Hardware testing on Pi
- Day 4: Performance testing and optimization
- Day 5: Documentation and migration guide

**Deliverable:** Production-ready system

**Total Timeline:** 3-4 weeks

---

## Success Criteria

### Functional Requirements

✅ **Core Functionality:**
- [ ] Sensor reading works (all sensors)
- [ ] Camera capture works (5MP)
- [ ] Data upload works (sensor + images)
- [ ] Command processing works (pump, light)
- [ ] Onboarding works (WiFi credentials)

✅ **Async Architecture:**
- [ ] All operations are async
- [ ] Concurrent operations work
- [ ] Proper task management
- [ ] Graceful shutdown

✅ **Data Queue:**
- [ ] Offline operation works (1 day capacity)
- [ ] Queue persists across restarts
- [ ] Automatic cleanup works
- [ ] Upload processor works

✅ **Error Handling:**
- [ ] Exponential backoff works
- [ ] Circuit breaker works
- [ ] Graceful degradation works
- [ ] Recovery works

✅ **Configuration:**
- [ ] Hot-reload works (no restart)
- [ ] Validation works
- [ ] Invalid configs rejected

✅ **Camera:**
- [ ] Full 5MP captures
- [ ] Persistent service (no init overhead)
- [ ] EXIF metadata included
- [ ] Configurable quality

### Performance Requirements

✅ **Timing:**
- [ ] Sensor reading: <5s
- [ ] Camera capture: <2s (5MP)
- [ ] Sensor upload: <2s
- [ ] Image upload: <10s (5MP)
- [ ] Startup: <10s

✅ **Resource Usage:**
- [ ] Memory: <200MB average
- [ ] CPU: <20% average
- [ ] Disk: <500MB (queue + logs)

✅ **Reliability:**
- [ ] No crashes in 24h test
- [ ] No memory leaks
- [ ] Queue doesn't overflow
- [ ] Handles network outages

### Quality Requirements

✅ **Code Quality:**
- [ ] 80%+ test coverage
- [ ] No critical bugs
- [ ] Clean code (passes linting)
- [ ] Type hints added

✅ **Documentation:**
- [ ] README updated
- [ ] API documentation complete
- [ ] Migration guide complete
- [ ] Troubleshooting guide updated

✅ **External API Parity:**
- [ ] Sensor data format unchanged
- [ ] Camera upload format unchanged
- [ ] Command format unchanged
- [ ] Backend compatibility verified

---

## Risk Assessment

### High Risk

**1. Async Migration Complexity**
- **Risk:** Async conversion may introduce subtle bugs
- **Mitigation:** Comprehensive testing, gradual rollout
- **Contingency:** Keep synchronous version as fallback

**2. Queue Database Corruption**
- **Risk:** SQLite corruption could lose queued data
- **Mitigation:** Regular backups, WAL mode, proper shutdown
- **Contingency:** Rebuild queue from scratch (data loss acceptable)

### Medium Risk

**3. Camera Performance**
- **Risk:** 5MP captures may be slower than expected
- **Mitigation:** Performance testing, optimization
- **Contingency:** Make resolution configurable, allow lower resolution

**4. Memory Usage**
- **Risk:** Queue + camera buffers may use too much memory
- **Mitigation:** Monitor memory, optimize buffers
- **Contingency:** Reduce queue size, reduce camera buffers

**5. Configuration Complexity**
- **Risk:** More config options = more confusion
- **Mitigation:** Good defaults, validation, documentation
- **Contingency:** Provide simple and advanced config modes

### Low Risk

**6. Dependency Issues**
- **Risk:** New dependencies may have conflicts
- **Mitigation:** Pin versions, test thoroughly
- **Contingency:** Use virtual environment, isolate dependencies

**7. Migration Issues**
- **Risk:** Users may have trouble migrating
- **Mitigation:** Automatic migration script, clear guide
- **Contingency:** Provide manual migration steps, support

---

## Rollback Plan

### Immediate Rollback (Emergency)

If critical issues occur in production:

```bash
# 1. Stop service
sudo systemctl stop growmate

# 2. Restore backup config
sudo cp /etc/growmate/config.yaml.backup /etc/growmate/config.yaml

# 3. Checkout previous version
cd /opt/growmate
git checkout v1.0  # Last stable version

# 4. Restart service
sudo systemctl start growmate

# 5. Verify
sudo systemctl status growmate
sudo journalctl -u growmate -f
```

**Time to Rollback:** <5 minutes

### Gradual Rollback (Planned)

If issues are discovered but not critical:

1. **Disable New Features**
   - Set feature flags to false in config
   - Disable queue: `queue.enabled: false`
   - Disable hot-reload: `features.hot_reload: false`

2. **Monitor and Debug**
   - Collect logs and diagnostics
   - Identify root cause
   - Fix and test

3. **Re-enable Features**
   - Enable one feature at a time
   - Monitor for issues
   - Proceed if stable

### Data Recovery

**Queue Data:**
- Queue database at `/var/lib/growmate/queue.db`
- Backup before migration: `cp queue.db queue.db.backup`
- Restore if needed: `cp queue.db.backup queue.db`

**Configuration:**
- Config at `/etc/growmate/config.yaml`
- Backup before migration: `cp config.yaml config.yaml.backup`
- Restore if needed: `cp config.yaml.backup config.yaml`

**Logs:**
- Logs at `/var/log/growmate/`
- Backup before migration: `tar -czf logs-backup.tar.gz /var/log/growmate/`
- Restore if needed: `tar -xzf logs-backup.tar.gz -C /`

---

## Next Steps

### Immediate Actions

1. **Review and Approve Plan**
   - Review this plan thoroughly
   - Approve or request changes
   - Confirm priorities and timeline

2. **Setup Development Environment**
   - Clone repository
   - Create feature branch: `feature/rpi-optimization`
   - Setup virtual environment
   - Install dependencies

3. **Begin Phase 1**
   - Start with async architecture
   - Create new main.py structure
   - Implement event loop and task management
   - Write tests

### Development Workflow

1. **Branch Strategy**
   - Main branch: `main` (stable)
   - Development branch: `develop` (integration)
   - Feature branches: `feature/phase-N-description`

2. **Commit Strategy**
   - Commit frequently with clear messages
   - Reference phase and task in commits
   - Tag milestones: `v2.0-phase1`, `v2.0-phase2`, etc.

3. **Testing Strategy**
   - Write tests before implementation (TDD)
   - Run tests on every commit
   - Integration tests on every phase completion

4. **Review Strategy**
   - Self-review before commit
   - Code review for major changes
   - Testing review for critical paths

---

## Conclusion

This plan completely overhauls the GrowMate RPI implementation to remove all ESP32 constraints and optimize for Raspberry Pi hardware. The result will be a modern, robust, high-performance plant monitoring system that leverages the full capabilities of the Raspberry Pi while maintaining external API compatibility.

**Key Benefits:**
- ✅ Full 5MP camera (vs 800×600)
- ✅ 1-day offline operation (vs none)
- ✅ Modern async architecture (vs synchronous loop)
- ✅ Robust error handling (vs simple retry)
- ✅ Hot-reload configuration (vs restart required)
- ✅ Structured logging (vs text logs)
- ✅ Better resource utilization (512MB RAM vs 520KB patterns)
- ✅ Simplified web interface (WiFi only)

**Timeline:** 3-4 weeks  
**Risk Level:** Medium (mitigated with testing and rollback plan)  
**External API Impact:** None (full compatibility maintained)

**Ready to proceed with implementation!**

