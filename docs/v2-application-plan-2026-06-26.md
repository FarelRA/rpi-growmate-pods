# GrowMate V2 — Application Implementation Plan

**Date:** 2026-06-26  
**Status:** Planning — ready for execution  
**Approach:** Build the V2 device agent on a **local-first foundation** — every V2 feature (hardware, API, camera, network) is wrapped in local resilience patterns (offline queue, circuit breaker, retry, config, health monitoring) that make the device self-sufficient even when the cloud is unreachable. Where the V2 handoff chose simplicity, we improve with battle-tested local-first infrastructure.  

---

## Related Documents & Cross-References

This plan references the following files. Use these links to navigate the full context of each change.

### Source Documents (Read First)

| File | Role |
|------|------|
| `docs/device-handoff-2026-06-25.md` | **Authoritative V2 spec** — hardware pinout, API contracts, agent loop pseudocode, systemd spec, provisioning steps, troubleshooting table, version comparison |
| `docs/device-v2-notes-2026-06-27.md` | **Setup guide** — human-readable provisioning steps, hardware reference, pinout reference, ADC mapping table, camera config, troubleshooting |

### Current Codebase (Files Being Modified)

| File | Description |
|------|-------------|
| `src/sensors.py` | ADS1115 + DHT22 reading, calibration — **Phase 1** rewrites ADC channels, adds ACS712, hardcodes formulas |
| `src/actuators.py` | GPIO relay control, command processing — **Phase 1** rewrites GPIO pins, adds fertilizer/pesticide, removes light |
| `src/api_client.py` | HTTP client, circuit breaker, retry — **Phase 2** switches to V2 endpoints + x-api-key auth |
| `src/main.py` | App entry point, APScheduler jobs — **Phase 2/4** removes camera job, adds stream reg; AP mode onboarding KEPT AND IMPROVED (async, scan button restored, WiFi auto-connect after onboarding) |
| `src/utils.py` | Constants, helpers — **Phase 2** updates FIRMWARE_VERSION, interval defaults, GPIO constants |
| `src/config_manager.py` | YAML config, provisioning — **Phase 4** adds env var overrides, V2 defaults |
| `src/config_validator.py` | Pydantic schema — **Phase 4** updates V2 validation rules |
| `src/camera_service.py` | PiCamera2 still captures — **Phase 3** rewrites as rpicam-vid process manager |
| `systemd/growmate.service` | Systemd unit — **Phase 4** V2 env vars, start.sh path, pi user |
| `scripts/install.sh` | Automated installer — **Phase 5** V2 deps, AP mode kept (hostapd + dnsmasq), Tailscale step |
| `README.md` | Project readme — **Phase 5** V2 setup instructions |
| `requirements.txt` | Python deps — **Phase 3/5** removes picamera2/piexif; keeps flask/werkzeug for AP mode onboarding |

### Current Codebase (Files Being Kept Unchanged)

| File | Description |
|------|-------------|
| `src/queue_manager.py` | SQLite offline queue (24h, WAL, FIFO) — kept as-is |
| `src/upload_processor.py` | Continuous queue drain — kept as-is |
| `src/circuit_breaker.py` | Per-endpoint circuit breaker — kept as-is |
| `src/retry_handler.py` | Exponential backoff + jitter — kept as-is |
| `src/config_watcher.py` | Hot-reload via watchdog — kept as-is |
| `src/logging_config.py` | Structured JSON logging with correlation IDs — kept as-is |
| `src/health_monitor.py` | 5-minute health checks — kept as-is |

### Current Codebase (Files Being Removed)

*Note: `config/config.yaml.example` was ultimately retained and expanded to a 409-line V2 reference config. The V1 test scripts listed below were never found in the repo — they existed only in the plan.*

| File | Phase | Reason |
|------|-------|--------|
| `scripts/test_main_integration.py` | P5 | Tests old main.py |
| `scripts/test_service_deployment.py` | P5 | Tests old service |
| `scripts/test_system_integration.py` | P5 | Tests old e2e flow |
| `scripts/test_core_components.py` | P5 | Tests old constants |
| `scripts/test_failure_recovery.py` | P5 | Tests old patterns |
| `scripts/test_documentation_validation.py` | P5 | Tests old docs |
| `scripts/monitor_performance.py` | P5 | Not V2-relevant |

### Current Codebase (Files Kept — AP Mode Onboarding)

| File | Role |
|------|------|
| *(AP mode files kept — see "Kept" section below)* | | |

### New Files Being Created

| File | Phase | Description |
|------|-------|-------------|
| `start.sh` | P3 | Orchestrates Tailscale → rpicam-vid → stream registration → main.py |
| `docs/v2-application-plan-2026-06-26.md` | — | This plan |

### Supporting Docs (Reference)

| File | Relevant To |
|------|-------------|
| `docs/api-2026-06-27.md` | Contains V2 API contract section added from handoff; use for endpoint formats |
| `docs/hardware-2026-06-26.md` | Contains V2 hardware additions section; use for component specs |
| `docs/wiring-2026-06-26.md` | Contains V2 wiring diagrams for relay module, limit switches, ACS712, ADS1115 remapping |
| `docs/troubleshooting-2026-06-27.md` | Contains V2 troubleshooting for rpicam-vid, Tailscale, sensors, relays, service |
| `docs/configuration-2026-06-27.md` | Contains V2 config section (env vars vs YAML comparison) |
| `docs/plan-port-2026-06-27.md` | Original port plan from ESP32 — superseded by this plan |
| `docs/plan-optimize-2026-06-27.md` | Optimization plan for V1 — superseded by this plan |

---

## Table of Contents

- [Guiding Principles](#guiding-principles)
- [Gap Analysis](#gap-analysis)
- [Architecture Overview](#architecture-overview)
- [Phase 1: Hardware Adaptation](#phase-1-hardware-adaptation)
- [Phase 2: API V2 Migration](#phase-2-api-v2-migration)
- [Phase 3: Camera Replacement](#phase-3-camera-replacement)
- [Phase 4: Network & Config Overhaul](#phase-4-network--config-overhaul)
- [Phase 5: Cleanup & Verification](#phase-5-cleanup--verification)
- [Detailed File Inventory](#detailed-file-inventory)
- [Verification Gates](#verification-gates)

---

## Guiding Principles

1. **The V2 spec is the target; local-first is the foundation.** Every behavioral requirement from `docs/device-handoff-2026-06-25.md` must be matched exactly. The local-first infrastructure (queue, circuit breaker, retry, config, health monitor, logging) is how we wrap those requirements so the device works reliably without constant cloud connectivity.

2. **Improve, don't just keep.** The local-first features from V1 are not baggage to carry forward unchanged — they must be adapted and improved for V2's specific needs: V2 payload formats, V2 endpoints, V2 sensors/actuators, V2 camera, V2 network. Every component is re-evaluated for V2 fit and upgraded accordingly.

3. **Add new local-first patterns where V2 is thin.** The V2 handoff chose simplicity (no queue, no retry, no config, no health checks, no camera watchdog). We overlay local-first resilience on each of those points: queue sensor data, retry with circuit breaker, config with env var overrides, health monitor aware of V2 hardware, watchdog that restarts rpicam-vid if it crashes.

4. **V2 hardware accuracy is absolute.** GPIO pins, ADC channels, sensor formulas, actuator behaviors, limit switch logic, ACS712 calibration — every electrical detail must match the handoff spec exactly. There is no "keep V1" for pin assignments.

5. **Incremental, verifiable phases** — each phase is independently testable. No phase should take longer than 2–3 hours.

6. **No dead code paths** — if V2 removes a feature (grow light, camera upload), remove its code entirely. Don't leave it disabled with a feature flag. AP mode onboarding is kept and improved for first-time WiFi setup and recovery.

---

## Gap Analysis

The V2 handoff specifies behavior. The local-first foundation is how we implement that behavior reliably. Each row shows the V2 requirement, the local-first infra that wraps it, and the V2-specific improvement.

| Aspect | V2 Requirement (Handoff) | Local-First Foundation | V2 Improvement |
|--------|-------------------------|----------------------|----------------|
| **ADS1115 channels** | ch0=ACS712, ch1=light, ch2=water, ch3=soil | ASA `SensorReader` reads in thread pool, wraps failures, feeds health monitor | **New**: local sensor health tracking — track consecutive ADC/DHT22 failures per channel, report degradation before total failure |
| **Actuator GPIOs** | pump=GPIO10, fertilizer=GPIO17, pesticide=GPIO27; simultaneous activation | ASA `ActuatorController` wraps GPIO in `OutputDevice`, `asyncio.Lock` prevents race conditions | **New**: relay state journal — log every relay state transition with timestamp; report in health monitor |
| **Limit switches** | GPIO20 (tank NC), GPIO21 (drawer NC); internal pull-up | Read in main loop, included in `currentState` payload | **New**: software debounce — 50ms settling delay + 3-of-5 sampling to reject contact bounce |
| **Battery monitoring** | ACS712 on ch0, 185mV/A, bidirectional; server-side coulomb counting | Read every 60s, included in `currentState` | **New**: local coulomb counter — accumulate mAh locally; serve as fallback SoC estimate when cloud unreachable; combine with server estimate when connected |
| **Grow light** | Removed; `lightEnabled` always `false` | N/A | **Removed** entirely — no hidden feature flag, no vestigial code paths |
| **Camera** | rpicam-vid live H.264 TCP stream; no still captures | `CameraService` wraps as subprocess manager | **New**: camera watchdog — health monitor checks rpicam-vid PID every 30s; auto-restart on crash; log crash count |
| **Camera uploads** | None — replaced by live stream | Remove `image_queue` table; remove `upload_processor` image path; remove camera circuit breaker | **Simplified**: sensor-only queue = fewer tables, less contention, simpler stats |
| **API endpoints** | Fixed `https://growmate.bond/api/v2/sensors`, `/api/v2/stream/register` | Circuit breaker per endpoint; retry handler with exponential backoff | **New**: stream registration retry — if register fails at startup, retry with backoff (not fire-and-forget); store last successful stream URL in local state |
| **API auth** | `x-api-key: <DEVICE_API_KEY>` on every request | Env var `DEVICE_API_KEY` loaded at startup, validated by config manager | **Improved**: validate API key format (non-empty, reasonable length) at config load, not at runtime |
| **Command kinds** | `pump`, `fertilizer`, `pesticide` (durationMs); `light` ignored; simultaneous activation | Processed by `ActuatorController.process_commands()`; queued via `QueueManager` if offline | **Improved**: command ack tracking — log which commands were received vs executed; replay pending commands from queue on reconnect |
| **currentState fields** | Expanded: `fertilizerEnabled`, `pesticideEnabled`, `tankSwitchOpen`, `drawerSwitchOpen`, `batteryCurrent` | Built by `SensorReader.get_current_state()`, combined with `ActuatorController` state | **Improved**: state reconciliation — verify GPIO reads match expected states after command execution; log mismatch warnings |
| **Sensor kinds** | All 5 required every POST: `soil`, `light`, `water`, `temperature`, `air` | Queue enforces payload completeness before enqueue | **New**: partial-fail sensor report — if a sensor fails (e.g. DHT22 CRC error), include `null` + error flag so server knows device is alive but that sensor degraded |
| **Firmware version** | `"2.0.0"` | Stored in `utils.py`, sent in every payload | **Improved**: read from file `/etc/growmate/firmware_version` (easier to update without code change); fallback to compiled constant |
| **Mappings** | Hardcoded formulas: soil inverted, water/light proportional | Applied in `SensorReader` calibration methods | **Improved**: publish formulas in health monitor output (self-documenting); logged at startup |
| **Report interval** | 60s POST interval | APScheduler `IntervalTrigger` keeps timing even if a POST hangs | **Improved**: configurable via YAML (default 60s); hot-reloadable via `config_watcher` |
| **Temperature range** | -40 to 125 | Validated by payload builder; no clamping | **Improved**: range outlier logging — log warning if temperature outside -40–125 but still send the value |
| **Network** | Tailscale VPN + AP mode fallback | `NetworkManager` handles AP mode setup; Tailscale for day-to-day; AP mode for first-time setup and recovery | **Kept**: AP mode onboarding for first-time WiFi setup; Tailscale health check in health monitor |
| **Config secrets** | Env vars `DEVICE_API_KEY`, `DEVICE_ID` | `ConfigManager` checks env vars first, falls back to YAML | **Improved**: env var override for any YAML key (not just secrets); hot-reload still works for non-secret changes |
| **Onboarding portal** | Flask web portal for WiFi credential entry | `onboarding_portal.py` serves during AP mode; calls `update_from_onboarding()` to save config | **Kept**: Minimal web interface survives into V2 for first-time setup and recovery |
| **Offline queue** | None in V2 spec | **Added**: SQLite queue (sensor data only, no images) with 24h capacity | **Improved**: image queue removed; sensor-only queue = simpler schema, fewer tables, less I/O |
| **Circuit breaker** | None in V2 spec | **Added**: per-endpoint (sensors, stream register) CLOSED/OPEN/HALF_OPEN | **Improved**: V2-specific timeouts (30s sensors, 10s stream register) |
| **Retry handler** | None in V2 spec | **Added**: exponential backoff 1–32s, 25% jitter, max 6 attempts | **Improved**: V2-specific error categorization (x-api-key rejection = permanent, 503 = transient) |
| **Config hot-reload** | None in V2 spec | **Added**: watchdog monitors YAML file; applies interval/camera/retry changes without restart | **Improved**: env var changes still require service restart (but detected and logged at startup) |
| **Health monitor** | None in V2 spec | **Added**: 5-minute health checks; reports sensor health, queue depth, circuit breaker stats, camera PID, battery SoC | **New**: V2-specific metrics (ACS712 current, limit switch state, camera crash count, Tailscale status) |
| **Structured logging** | None in V2 spec | **Added**: JSON to journald with correlation IDs, rotating file fallback (10MB, 5 backups) | **Improved**: per-module log levels, hot-reloadable |

---

## Architecture Overview (After V2)

```
                       ┌──────────────────────────────────────────────────────┐
                       │               TAILSCALE VPN TUNNEL                    │
                       │  (day-to-day connectivity)                           │
                       └───────────────────────┬──────────────────────────────┘
                                               │
            ┌──────────────────────────────────┼──────────────────────────────┐
            │  systemd growmate.service        │  Env: DEVICE_API_KEY,        │
            │  (ExecStartPre: tailscale status) │        DEVICE_ID             │
            └──────────────────────────────────┴──────────────────────────────┘
                                               │
                                      ┌────────▼─────────┐
                                      │  start.sh         │
                                      │  (orchestrator)   │
                                      └────────┬─────────┘
                                               │
            ┌──────────────────────────────────┼──────────────────────────────┐
            │  AP MODE (First-time / recovery) │                               │
            │  ┌────────────────────────┐      │                               │
            │  │  hostapd + dnsmasq     │      │                               │
            │  │  GrowMate-XXXX AP      │      │                               │
            │  └───────────┬────────────┘      │                               │
            │              │                    │                               │
            │  ┌───────────▼────────────┐      │                               │
            │  │  Onboarding Portal     │      │                               │
            │  │  (Flask, port 80)      │      │                               │
            │  │  WiFi cred entry       │      │                               │
            │  └────────────────────────┘      │                               │
            └──────────────────────────────────┘                               │
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              │              BACKGROUND       │          FOREGROUND           │
              │                               │                               │
              │  ┌──────────────────────┐     │  ┌─────────────────────────┐  │
              │  │    rpicam-vid        │     │  │    main.py              │  │
              │  │  (H.264 TCP daemon)  │     │  │  (async event loop)     │  │
              │  │  port 8554           │     │  └──────────┬──────────────┘  │
              │  └──────────────────────┘     │             │                  │
              └───────────────────────────────┴─────────────┼──────────────────┘
                                                            │
                              ┌─────────────────────────────┼─────────────────────┐
                              │       LOCAL-FIRST FOUNDATION LAYER               │
                              │                                                     │
                              │  ┌──────────────┐  ┌──────────────────┐           │
                              │  │ V2 Hardware  │  │  V2 API Client   │           │
                              │  │ ──────────── │  │ ─────────────── │           │
                              │  │ SensorReader │  │ APIClient        │           │
                              │  │ • V2 ADC map │  │ • v2 endpoints   │           │
                              │  │ • ACS712     │  │ • x-api-key auth │           │
                              │  │ • DHT22      │  │ • stream reg     │           │
                              │  │ • limit sw.  │  │ • circuit brkr   │           │
                              │  │ • health     │  │ • retry handler  │           │
                              │  └──────┬───────┘  └────────┬─────────┘           │
                              │         │                    │                     │
                              │  ┌──────▼────────────────────▼─────────┐          │
                              │  │     Offline Queue (SQLite)          │          │
                              │  │  • sensor data only (no images)    │          │
                              │  │  • 24h FIFO, WAL mode              │          │
                              │  │  • UploadProcessor drains          │          │
                              │  └────────────────────────────────────┘          │
                              │                                                     │
                              │  ┌──────────────┐  ┌──────────────────┐           │
                              │  │  Actuators   │  │  Health Monitor  │           │
                              │  │ • V2 GPIOs   │  │ • V2 metrics     │           │
                              │  │ • simultan.  │  │ • camera watchd. │           │
                              │  │ • no light   │  │ • queue depth    │           │
                              │  │ • state jour.│  │ • circuit brkrs  │           │
                              │  └──────────────┘  └──────────────────┘           │
                              │                                                     │
                              │  ┌────────────────────────────────────┐            │
                              │  │  Config (YAML + env var overrides) │            │
                              │  │  • hot-reload via config_watcher   │            │
                              │  │  • Pydantic validation             │            │
                              │  └────────────────────────────────────┘            │
                              │                                                     │
                              │  ┌────────────────────────────────────┐            │
                              │  │  Structured Logging (JSON/journald) │            │
                              │  │  • correlation IDs across requests │            │
                              │  │  • per-module levels, rotation     │            │
                              │  └────────────────────────────────────┘            │
                              └─────────────────────────────────────────────────────┘
```

### Local-First Foundation Components

| Layer | Component | File | V2-Specific Adaptation |
|-------|-----------|------|------------------------|
| **Core loop** | Async event loop + APScheduler | `main.py` | 60s sensor interval (up from 15s); no camera capture job; stream registration at startup |
| **V2 Hardware** | SensorReader (V2 channels + ACS712 + limit switches) | `sensors.py` | ch0=ACS712, ch3=soil; hardcoded formulas; local sensor health tracking per channel; software debounce on switches; 50ms settling |
| **V2 Hardware** | ActuatorController (V2 GPIOs, simultaneous activation) | `actuators.py` | Pump=10, fertilizer=17, pesticide=27; no light; relay state journal; command ack tracking |
| **V2 Network** | Tailscale (day-to-day) + AP mode (setup/recovery) | `network_manager` / `start.sh` / health_monitor | AP mode for first-time WiFi setup; Tailscale for day-to-day; health monitor tracks both |
| **V2 API** | APIClient (v2 endpoints, x-api-key, stream register) | `api_client.py` | Fixed URLs; circuit breaker per endpoint; stream reg retry with backoff; no camera upload |
| **V2 API** | QueueManager + UploadProcessor (sensor-only) | `queue_manager.py` + `upload_processor.py` | image_queue removed; sensor payload in V2 format; 24h FIFO |
| **V2 Config** | ConfigManager (env var overrides + YAML + hot-reload) | `config_manager.py` + `config_validator.py` + `config_watcher.py` | DEVICE_API_KEY / DEVICE_ID from env; everything else in YAML; hot-reload still works |
| **V2 Camera** | CameraService (rpicam-vid process manager + watchdog) | `camera_service.py` | subprocess.Popen; watchdog restarts on crash; health monitor tracks PID + crash count |
| **V2 Resilience** | CircuitBreaker (per-endpoint) | `circuit_breaker.py` | Sensors endpoint (30s timeout); stream register endpoint (10s timeout); V2 error categories |
| **V2 Resilience** | RetryHandler (exponential backoff + jitter) | `retry_handler.py` | 6 attempts, 1–32s, 25% jitter; permanent error if x-api-key rejected (4xx) |
| **V2 Observability** | HealthMonitor (V2 metrics) | `health_monitor.py` | ACS712 current, limit switch state, camera PID + crash count, Tailscale IP + status, queue depth, circuit breaker stats |
| **V2 Observability** | Structured JSON logging | `logging_config.py` | Correlation IDs across sensor POST → command response → actuator execution trace |
| **V2 Power** | Local coulomb counter | `sensors.py` (ACS712) | Accumulate mAh locally; serve as fallback SoC when cloud unreachable; combine with server estimate when connected |

### What's Removed

| Item | Reason |
|------|--------|
| Still camera capture (picamera2 + piexif) | Replaced by rpicam-vid live H.264 stream |
| Camera JPEG upload + image queue | Replaced by live stream; sensor-only queue is simpler |
| Grow light actuator | V2 has no grow light; GPIO 22 is unused |
| Old test scripts (except test_network_onboarding) | Test deprecated V1 architecture and components |

### What's Kept (AP Mode Onboarding)

| Item | Role |
|------|------|
| AP mode (hostapd + dnsmasq) | First-time WiFi setup and recovery fallback |
| WiFi onboarding portal (Flask) | Web UI for entering WiFi credentials |
| Flask, templates, static assets | Served during AP mode for credential entry |
| NetworkManager class | AP mode control and WiFi connection management |

---

## Phase 1: Hardware Adaptation

**Goal:** Update `src/sensors.py` and `src/actuators.py` for the V2 pinout, sensors, and actuators.

**References:**
- Handoff spec §§1, 5.5, 5.6, 5.7 (`docs/device-handoff-2026-06-25.md`)
- V2 pinout diagram (`docs/device-v2-notes-2026-06-27.md#pinout`)
- ADC percentage mapping table (`docs/device-v2-notes-2026-06-27.md#adc--percentage-mapping`)
- V2 hardware additions section (`docs/hardware-2026-06-26.md#v2-hardware-additions`)
- V2 wiring diagrams (`docs/wiring-2026-06-26.md#v2-wiring-changes`)

### sensors.py — Changes

1. **ADS1115 channel remapping:**
   ```python
   # V2 mapping
   ACS712_CHANNEL = 0    # ch0: battery current
   LIGHT_CHANNEL = 1     # ch1: light (unchanged)
   WATER_CHANNEL = 2     # ch2: water (unchanged)
   SOIL_CHANNEL = 3      # ch3: soil (moved from ch0)
   ```

2. **Add ACS712 battery current sensor:**
   ```python
   def read_battery_current(self) -> Optional[Dict]:
       # Read ch0, convert voltage to mA
       # ACS712: (adc_V - 2.5) / 0.185 * 1000
       # Positive = charging, negative = discharging
       raw = self.read_adc_averaged(self.acs712_channel)
       voltage = raw / 65535 * 4.096  # Gain=1, ±4.096V
       current_ma = (voltage - 2.5) / 0.185 * 1000
       return int(current_ma)
   ```

3. **Hardcode ADC → percentage formulas** (remove config-driven calibration):
   ```python
   def calibrate_soil(self, raw: int) -> int:
       mv = raw / 65535 * 4096
       return max(0, min(100, 100 - (mv / 4096 * 100)))  # inverted

   def calibrate_water(self, raw: int) -> int:
       mv = raw / 65535 * 4096
       return max(0, min(100, mv / 4096 * 100))  # proportional

   def calibrate_light(self, raw: int) -> int:
       mv = raw / 65535 * 4096
       return max(0, min(100, mv / 4096 * 100))  # proportional
   ```

4. **Add limit switch reading:**
   ```python
   TANK_SWITCH_GPIO = 20
   DRAWER_SWITCH_GPIO = 21
   # NC: LOW = closed (normal), HIGH = open (alarm)
   # Use internal pull-up: PUD_UP
   def read_limit_switches(self) -> dict:
       return {
           "tankSwitchOpen": GPIO.input(TANK_SWITCH_GPIO) == GPIO.HIGH,
           "drawerSwitchOpen": GPIO.input(DRAWER_SWITCH_GPIO) == GPIO.HIGH,
       }
   ```

5. **Add `currentState` builder** combining actuator states + limit switches + battery current:
   ```python
   def get_current_state(self) -> dict:
       return {
           "pumpEnabled": GPIO.input(PUMP_GPIO) == GPIO.HIGH,
           "lightEnabled": False,  # V2 has no grow light
           "fertilizerEnabled": GPIO.input(FERTILIZER_GPIO) == GPIO.HIGH,
           "pesticideEnabled": GPIO.input(PESTICIDE_GPIO) == GPIO.HIGH,
           "tankSwitchOpen": GPIO.input(TANK_SWITCH_GPIO) == GPIO.HIGH,
           "drawerSwitchOpen": GPIO.input(DRAWER_SWITCH_GPIO) == GPIO.HIGH,
           "batteryCurrent": self.read_battery_current(),
       }
   ```

6. **Require all 5 sensor kinds:** Every POST must include `soil`, `light`, `water`, `temperature`, `air`. If a sensor fails, log error but still include with `null` value or skip — server side validates.

7. **Temperature range:** Allow -40 to 125 (remove V1's 0–100 clamp).

8. **Expand DHT22 value type:** Return `float` instead of `int(round(...))`:
   ```python
   'value': temperature  # float, not int
   ```

9. **Remove async wrappers** (`async_read_all_sensors` etc.) if keeping synchronous reads in thread pool. Actually, the async wrappers should stay since we're keeping the async architecture. But we should update them to work with V2 sensors. **Keep async wrappers** but update internals.

10. **Remove config dependency:** `SensorReader.__init__` should not require config dict. Pass only what's needed, or use env defaults.

### actuators.py — Changes

1. **GPIO remapping:**
   ```python
   FERTILIZER_GPIO = 17   # Relay 1 (was pump in V1)
   PESTICIDE_GPIO = 27    # Relay 2 (was light in V1)
   RELAY3_GPIO = 22       # Not connected (unused)
   PUMP_GPIO = 10         # Relay 4 (moved from GPIO 17)
   ```

2. **Add limit switch GPIOs** (for reading, not actuation):
   ```python
   TANK_SWITCH_GPIO = 20   # NC, internal pull-up
   DRAWER_SWITCH_GPIO = 21 # NC, internal pull-up
   ```

3. **Replace `process_commands` for V2:**
   - Command kinds: `pump`, `fertilizer`, `pesticide` (all durationMs)
   - `light` commands are **ignored** (logged and skipped)
   - **Simultaneous activation:** If multiple durationMs values differ, hold all relays for the maximum duration
   - If fertilizer or pesticide is commanded, pump will ALSO be in the same response — actuate both simultaneously (pump carries chemical through valve)
   - If only pump commanded = plain watering
   - After execution, next POST's currentState must reflect actual relay states

4. **Implementation of simultaneous activation:**
   ```python
   async def process_commands(self, commands: list) -> None:
       if not commands:
           return
       
       # Filter light commands (V2 ignores them)
       relevant = [c for c in commands if c["kind"] in ("pump", "fertilizer", "pesticide")]
       if not relevant:
           return
       
       # Validate all have durationMs
       pins = {"pump": PUMP_GPIO, "fertilizer": FERTILIZER_GPIO, "pesticide": PESTICIDE_GPIO}
       max_ms = max(c.get("durationMs", 0) for c in relevant)
       
       # Set all commanded pins HIGH simultaneously
       for cmd in relevant:
           gpio = pins[cmd["kind"]]
           GPIO.output(gpio, GPIO.HIGH)
       
       # Wait for max duration
       await asyncio.sleep(max_ms / 1000)
       
       # Set all LOW simultaneously
       for cmd in relevant:
           gpio = pins[cmd["kind"]]
           GPIO.output(gpio, GPIO.LOW)
   ```

5. **Remove grow light:** `light.is_active`, `set_light`, `lightEnabled` all removed. `lightEnabled` is always `false` in currentState.

6. **Switch to RPi.GPIO** (consistent with handoff spec). Keep `gpiozero` as alternative if preferred — either is acceptable per handoff.

7. **Remove pump housekeeping** (async loop checking timeout) — V2 uses synchronous sleep-based activation instead. The housekeeping loop is no longer needed because we block for the full duration.

### Files Affected

| File | Action |
|------|--------|
| `src/sensors.py` | Rewrite channels, add ACS712, hardcode formulas, add limit switches, enforce 5 sensors |
| `src/actuators.py` | Rewrite GPIOs, remove light, add fertilizer/pesticide, simultaneous activation, remove housekeeping |

### Local-First Improvements (Beyond V2 Spec)

1. **Per-channel sensor health tracking** — each ADC channel and DHT22 has a health counter; after N consecutive failures, mark as degraded in health monitor (vs V2 which would silently lose that sensor)
2. **Limit switch software debounce** — 50ms settling delay + 3-of-5 majority vote to reject contact bounce (vs V2 which reads raw GPIO once)
3. **Relay state journal** — every `GPIO.output()` call is logged with timestamp, expected state, and which command triggered it (vs V2 which just sets pins)
4. **State reconciliation** — after command execution, re-read GPIOs and verify they match; log warning if mismatch (vs V2 which assumes GPIO.write always succeeds)

### Verification

- `SensorReader` initializes ADC on ch0-ch3, reads ACS712 on ch0
- `read_battery_current()` returns positive mA when charging, negative when discharging
- `get_current_state()` reports correct limit switch states (LOW = closed)
- `execute_commands({"pump": 5000, "fertilizer": 8000})` activates both pins for 8000ms max
- `light` commands are logged and skipped
- All 5 sensor kinds always present in returned list
- Temperature returns float, -40 to 125 range
- **Local-first**: if DHT22 fails 3 times in a row, health monitor reports "DHT22_DEGRADED" instead of crashing
- **Local-first**: limit switch debounce rejects <50ms glitches (test with 10ms pulse → ignored)

---

## Phase 2: API V2 Migration

**Goal:** Update API client and main loop for V2 endpoints, auth, and command flow.

**References:**
- Handoff spec §2 (API Contracts), §2.1 (Sensor Report), §2.2 (Stream Registration), §2.3 (Auth Pattern) (`docs/device-handoff-2026-06-25.md`)
- V2 API section in `docs/api-2026-06-27.md` for endpoint formats and validation rules
- V2 config env vars vs YAML (`docs/configuration-2026-06-27.md#v2-configuration-device-agent`)

### api_client.py — Changes

1. **V2 endpoints:**
   ```python
   SENSOR_URL = "https://growmate.bond/api/v2/sensors"
   STREAM_REGISTER_URL = "https://growmate.bond/api/v2/stream/register"
   ```

2. **x-api-key auth:**
   ```python
   headers = {
       "Content-Type": "application/json",
       "x-api-key": os.environ.get("DEVICE_API_KEY", ""),
       "X-Correlation-Id": get_correlation_id() or "none",
   }
   ```

3. **Update payload format** in `upload_sensor_data()`:
   ```python
   payload = {
       "deviceId": self.device_id,
       "firmwareVersion": "2.0.0",
       "currentState": current_state,  # expanded V2 fields
       "sensors": sensors,             # always 5 sensor kinds
   }
   ```

4. **Update response parsing:** Expect V2 response format:
   ```python
   # Response 200:
   # { "success": true, "updated": 5, "commands": [...] }
   data = await response.json()
   commands = data.get("commands", [])
   ```

5. **Add `register_stream()` method:**
   ```python
   async def register_stream(self, stream_url: str) -> bool:
       payload = {
           "deviceId": self.device_id,
           "streamUrl": stream_url,
       }
       async with self.session.post(
           STREAM_REGISTER_URL,
           json=payload,
           headers={"x-api-key": ..., "Content-Type": "application/json"},
       ) as resp:
           data = await resp.json()
           return data.get("success", False)
   ```

6. **Remove camera upload:** Delete `upload_camera_image()` method entirely. Remove the camera circuit breaker. Remove camera URL from config.

7. **Device ID:** Read from env var `DEVICE_ID` instead of config YAML:
   ```python
   self.device_id = os.environ.get("DEVICE_ID") or config.get("device", {}).get("id", "unknown")
   ```

8. **Firmware version constant:** Update to `"2.0.0"`.

### main.py (main.py) — Changes

1. **Update command processing** to call V2-aware `actuators.process_commands()`.

2. **currentState always sent** in every sensor POST (was optional before, now always sent).

3. **currentState must reflect actual states AFTER commands executed.** Sequence:
   ```
   POST sensors + currentState (pre-execution)
   ← receive commands
   execute commands (hardware changes)
   next POST: sensors + currentState (post-execution, reflects changes)
   ```

4. **Remove camera capture job** from APScheduler (no still images; camera is rpicam-vid daemon now).

5. **Add stream registration** at startup (after queue initialized but before scheduler starts).

6. **Update failure thresholds** — V2 keeps AP mode fallback. `failure_monitor_job` tears down components, re-enters AP mode for WiFi reconfiguration, and resumes after provisioning completes. This provides a recovery path when Tailscale or cloud connectivity fails permanently.

7. **Update constants:** `FIRMWARE_VERSION = "2.0.0"`, `SENSOR_INTERVAL_SECONDS = 60`.

8. **Keep imports** of `network_manager`, `onboarding_portal` (AP mode onboarding kept); `config_watcher`, `health_monitor` remain as local-first infrastructure.

### utils.py — Changes

1. `FIRMWARE_VERSION = "2.0.0"`
2. `SENSOR_INTERVAL_SECONDS = 60`
3. Remove `CAMERA_INTERVAL_SECONDS` (no more camera capture job)
4. Remove `API_TIMEOUT_CAMERA`
5. Update GPIO constants
6. Add `DEVICE_API_KEY` / `DEVICE_ID` env var helpers

### Files Affected

| File | Action |
|------|--------|
| `src/api_client.py` | V2 endpoints, x-api-key, stream register, remove camera upload |
| `src/main.py` | Update command flow, remove camera job, add stream reg at startup; keep and improve onboarding path (async AP mode, WiFi scan, auto-connect) |
| `src/utils.py` | Update constants, add env var helpers |

### Local-First Improvements (Beyond V2 Spec)

1. **Stream registration retry** — V2 tries once at startup. We retry with backoff (1s, 2s, 4s, 8s, max 60s) until success or agent shutdown. The health monitor tracks registration state as CONNECTED / CONNECTING / FAILED.
2. **Command ack tracking** — every command received from the server is logged with a sequence ID; responses that don't get executed (e.g. actuator hardware failure) are flagged. V2 has no such tracking.
3. **Queue resilience for POST failures** — if `POST /api/v2/sensors` fails (network down, server 5xx), the payload goes to the SQLite queue instead of being dropped. UploadProcessor drains it when connectivity returns. V2 drops the data silently.
4. **Sensor-only queue simplification** — the image_queue table is removed entirely. This reduces DB file size, eliminates a contention point in UploadProcessor, and simplifies health monitor stats.

### Verification

- `POST /api/v2/sensors` with x-api-key returns `{"success": true, "commands": [...]}`
- Register stream returns `{"success": true}`
- **Local-first**: if POST fails, payload is in `sensor_queue` table (check with `sqlite3 /var/lib/growmate/queue.db "SELECT COUNT(*) FROM sensor_queue"`)
- **Local-first**: circuit breaker opens after 5 consecutive POST failures; health monitor reports "SENSOR_API_OPEN"
- **Local-first**: stream registration retries on failure (check logs for "Stream registration failed, retrying in Ns")
- Camera upload code paths are gone (image_queue table does not exist)
- 60s default interval
- `"2.0.0"` firmware version in payload
- currentState includes all V2 fields (fertilizerEnabled, pesticideEnabled, tankSwitchOpen, drawerSwitchOpen, batteryCurrent)
- `light` commands logged and skipped
- chemical+pump commands executed simultaneously

---

## Phase 3: Camera Replacement

**Goal:** Replace picamera2 still captures with rpicam-vid live H.264 stream.

**References:**
- Handoff spec §3 (Camera Streaming), §3.1 (rpicam-vid Configuration), §3.2 (Pipeline), §3.3 (NAL Unit Protocol) (`docs/device-handoff-2026-06-25.md`)
- Camera streaming section in `docs/device-v2-notes-2026-06-27.md#camera-streaming`
- V2 camera changes in `docs/hardware-2026-06-26.md#v2-camera-changes`

### camera_service.py — Rewrite

Remove the picamera2/Picamera2 implementation. Replace with:

```python
class CameraService:
    """Manages rpicam-vid process for live H.264 streaming."""

    def __init__(self, config: Optional[dict] = None):
        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self.config = config or {}

    def start_stream(self) -> bool:
        """Start rpicam-vid as background process."""
        cmd = [
            "rpicam-vid", "-t", "0", "--inline", "--listen",
            "-o", "tcp://0.0.0.0:8554",
            "--width", "640", "--height", "480",
            "--framerate", "15",
            "--bitrate", "1000000",
            "--profile", "baseline",
            "--level", "3.1",
            "--denoise", "cdn_off",
        ]
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.running = True
        return True

    def stop_stream(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.running = False

    def get_stream_url(self, tailscale_ip: str) -> str:
        return f"tcp://{tailscale_ip}:8554"

    def cleanup(self):
        self.stop_stream()
```

Remove all picamera2 methods: `capture_jpeg`, `async_capture_jpeg`, `async_update_config`, EXIF handling, etc.

### start.sh — Created at `scripts/start.sh`

Now lives in the scripts directory:

```bash
#!/bin/bash
# GrowMate V2 Startup Script
# Orchestrates: Tailscale → rpicam-vid → stream registration → main.py
set -e

PROJECT_DIR="/home/grow/growmate"

echo "[start.sh] Checking Tailscale..."
tailscale status || tailscale up

echo "[start.sh] Starting camera stream..."
rpicam-vid -t 0 --inline --listen \
  -o tcp://0.0.0.0:8554 \
  --width 640 --height 480 --framerate 15 \
  --bitrate 1000000 --profile baseline --level 3.1 \
  --denoise cdn_off &
RPICAM_PID=$!
sleep 2

echo "[start.sh] Registering stream..."
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "127.0.0.1")
curl -s -X POST "https://growmate.bond/api/v2/stream/register" \
  -H "x-api-key: $DEVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"deviceId\": \"$DEVICE_ID\", \"streamUrl\": \"tcp://$TAILSCALE_IP:8554\"}" \
  -o /dev/null -w "%{http_code}" || echo "Stream registration failed"

echo "[start.sh] Starting agent..."
cd "$PROJECT_DIR"
exec python3 main.py
```

### requirements.txt — Update

Remove:
- `picamera2>=0.3.12`
- `piexif>=1.1.3`

Keep `flask>=2.3.0` and `werkzeug>=2.3.0` for AP mode onboarding portal.

### Files Affected

| File | Action |
|------|--------|
| `src/camera_service.py` | Rewrite as rpicam-vid process manager |
| `start.sh` | **New** — startup orchestration |
| `requirements.txt` | Remove picamera2, piexif; keep flask, werkzeug for AP mode onboarding |

### Local-First Improvements (Beyond V2 Spec)

1. **Camera watchdog** — health monitor checks `CameraService.process.pid` every 30s via `os.kill(pid, 0)`. If the process is dead, it restarts rpicam-vid and re-registers the stream. V2 has no recovery if rpicam-vid crashes between 60s POST intervals.
2. **Crash counter** — each camera restart increments a counter exposed in health monitor metrics. If crashes exceed 5 in 1 hour, health monitor reports UNHEALTHY (vs V2 which has no awareness).
3. **Stream registration retry** — if the camera restarts, the stream URL might change (Tailscale IP is stable, but port could conflict). The watchdog re-registers automatically.

### Verification

- `CameraService.start_stream()` launches rpicam-vid, process appears in `ps aux`
- `stop_stream()` terminates it cleanly
- **Local-first**: `kill -9 <rpicam-vid-pid>` → health monitor detects death within 30s → `start_stream()` called → process is back
- **Local-first**: 5+ crashes in 1h → health monitor state is UNHEALTHY
- `get_stream_url()` returns `tcp://<ip>:8554`
- Server can connect to `tcp://<Tailscale IP>:8554` and receive H.264
- No picamera2 import anywhere in codebase
- `start.sh` starts daemon, registers stream, then execs main.py

---

## Phase 4: Network & Config Overhaul

**Goal:** Keep and improve AP mode/onboarding portal, add Tailscale support, update config manager for V2.

**References:**
- Handoff spec §6 (systemd Service Specification), §7 (Device Provisioning Steps for docs/device-v2-notes-2026-06-27.md) (`docs/device-handoff-2026-06-25.md`)
- V2 systemd service in `docs/device-v2-notes-2026-06-27.md#systemd-service`
- V2 connectivity (Tailscale) in `docs/hardware-2026-06-26.md#v2-connectivity`
- V2 vs V1 config comparison in `docs/configuration-2026-06-27.md#v2-vs-v1-configuration`

### Files to Keep (AP Mode Onboarding)

The following V1 onboarding files are **kept** for V2. AP mode provides first-time WiFi setup and recovery fallback while Tailscale handles day-to-day connectivity.

| File | Role |
|------|------|
| `src/network_manager.py` | AP mode control, WiFi connection management |
| `src/onboarding_portal.py` | Flask web server for WiFi credential entry |
| `templates/index.html` | Onboarding UI |
| `templates/success.html` | Onboarding UI |
| `static/style.css` | Onboarding UI |
| `static/js/setup.js` | Onboarding UI |
| `config/hostapd.conf.template` | AP mode hostapd config |
| `config/dnsmasq.conf.template` | AP mode DNS/DHCP config |

### config_manager.py — Changes

1. **Add env var overrides:** Values from environment variables take precedence over YAML:
   ```python
   def _get_env_override(self, key: str) -> Optional[str]:
       env_map = {
           "device.id": "DEVICE_ID",
           "api.api_key": "DEVICE_API_KEY",
       }
       if key in env_map:
           return os.environ.get(env_map[key])
       return None
   ```

2. **Update YAML defaults** for V2:
   - `intervals.sensor_reading: 60`
   - `network.provisioned: false` (onboarding runs on first boot)
   - Remove `camera` section (no still captures)
   - Remove `circuit_breaker` if staying with V2 defaults (but we're keeping circuit breaker, so keep it)

3. **Keep provisioning check:** `is_provisioned()` is preserved for AP mode onboarding. Returns `True` only when `network.provisioned` is set AND `network.wifi_ssid` is non-empty.

4. **Keep `update_from_onboarding()`** — still used by the AP mode onboarding portal to save WiFi credentials after first-time setup.

### config_validator.py — Changes

1. Update camera validation to reflect no still camera config.
2. Remove network/AP mode validation.
3. Add validation for any new V2-specific config keys.

### config_watcher.py — Keep

No changes needed — hot-reload still works.

### systemd/growmate.service — Changes

```ini
[Unit]
Description=GrowMate V2 Agent
After=network-online.target
Wants=network-online.target

[Service]
ExecStartPre=/usr/bin/tailscale status
ExecStart=/home/grow/growmate/start.sh
Restart=always
RestartSec=10
User=grow
Environment=DEVICE_API_KEY=<set-during-provisioning>
Environment=DEVICE_ID=<set-during-provisioning>

[Install]
WantedBy=multi-user.target
```

Changes from V1 service:
- `ExecStart` → `/home/grow/growmate/start.sh`
- `WorkingDirectory` → `/home/grow/growmate`
- `User` → `pi` (not root)
- Add `ExecStartPre` for Tailscale check
- Add `Environment` for API key and device ID
- Remove `PYTHONUNBUFFERED`
- Remove onboarding service references

### main.py — Onboarding Path (Kept)

The `run()` method retains the provisioning check for first-time setup and recovery:

```python
def run(self):
    self.load_configuration()
    if not self.config_manager.is_provisioned():
        logger.info("Device not provisioned, entering onboarding mode")
        self.enter_onboarding_mode()
        self.load_configuration()
    return asyncio.run(self.run_async())
```

The `failure_monitor_job` also retains the onboarding fallback — after `FAILURE_THRESHOLD` consecutive failures, it tears down components, re-enters AP mode, and retries after provisioning completes.

### Files Affected

| File | Action |
|------|--------|
| `src/config_manager.py` | Add env var overrides, V2 defaults |
| `src/config_validator.py` | Update validation for V2 |
| `src/main.py` | Keep onboarding path (provisioning check + AP mode fallback) |
| `systemd/growmate.service` | V2 service definition |

### Files Kept (AP Mode Onboarding)

| File | Reason |
|------|--------|
| `src/network_manager.py` | AP mode for first-time WiFi setup and recovery |
| `src/onboarding_portal.py` | Flask web portal for credential entry |
| `templates/` | Onboarding UI templates |
| `static/` | Onboarding UI assets |
| `config/hostapd.conf.template` | AP mode hostapd config |
| `config/dnsmasq.conf.template` | AP mode DNS/DHCP config |

### Local-First Improvements (Beyond V2 Spec)

1. **Tailscale health check** — health monitor calls `tailscale status` every 5 minutes and parses the output. Reports Tailscale IP, connection state, and uptime. V2 has no runtime Tailscale monitoring after `start.sh`.
2. **Env var override for any YAML key** — the override pattern (`_get_env_override`) allows any config key to be set via env vars, not just `DEVICE_API_KEY` and `DEVICE_ID`. This enables containerized/automated deployments without YAML files. V2 only supports the two secrets as env vars.
3. **Config validation for V2** — `config_validator.py` enforces that `sensor_reading` interval is >= 10s, `DEVICE_API_KEY` is non-empty, `DEVICE_ID` matches expected format. V2 has no config validation at all.

### Verification

- `network_manager` and `onboarding_portal` imported in `main.py` for AP mode onboarding
- `DEVICE_API_KEY` and `DEVICE_ID` from env override YAML values
- `is_provisioned()` returns provisioning state from config (preserved for AP mode)
- Service starts as `pi` user, calls `start.sh`
- AP mode files kept: `config/hostapd.conf.template`, `config/dnsmasq.conf.template`, templates/, static/
- **Local-first**: `tailscale status` fails → health monitor reports "TAILSCALE_DISCONNECTED" (does not crash)
- **Local-first**: health monitor publishes Tailscale IP every 5 minutes in structured log

---

## Phase 5: Cleanup & Verification

**Goal:** Remove all dead code, update install/test scripts, update README, final verification.

**References:**
- Handoff spec §9 (Verification Checklist) (`docs/device-handoff-2026-06-25.md`)
- V2 provisioning steps in `docs/device-v2-notes-2026-06-27.md#provisioning-steps` (the install.sh should mirror this)
- V2 troubleshooting table in `docs/troubleshooting-2026-06-27.md#v2-specific-troubleshooting`
- Version comparison table in `docs/device-v2-notes-2026-06-27.md#version-comparison`

### Files to Delete (already absent — listed in plan but never existed in repo)

| File | Reason |
|------|--------|
| `scripts/test_main_integration.py` | Tests old main.py architecture |
| `scripts/test_service_deployment.py` | Tests old service + install |
| `scripts/test_system_integration.py` | Tests old end-to-end flow |
| `scripts/test_core_components.py` | Tests old constants/patterns |
| `scripts/test_failure_recovery.py` | Tests old failure patterns |
| `scripts/test_documentation_validation.py` | Tests old docs/schema |
| `scripts/monitor_performance.py` | Not relevant to V2 |

### Files to Update

1. **`scripts/test_hardware.py`** — **Deleted** (was V1 hardware diagnostic, not a proper test; replaced by `tests/test_sensors.py`, `tests/test_actuators.py`, etc.)

2. **`scripts/test_network_onboarding.py`** — **Deleted** (was V1 onboarding test; replaced by `tests/test_network_manager.py`, `tests/test_onboarding_portal.py`)

3. **`scripts/install.sh`** — Updated for V2:
   - Keep hostapd/dnsmasq/AP mode steps (used for first-time setup and recovery)
   - Keep Flask/templates/static copy (served during AP mode)
   - Add rpicam-apps to system deps
   - Add Tailscale install step (`curl -fsSL https://tailscale.com/install.sh | sh`)
   - Copy `main.py` and `scripts/start.sh` to `/home/grow/growmate/`
   - Set `chmod +x /home/grow/growmate/*.sh`
   - Update display messages for V2 (AP mode for first-time setup, Tailscale for day-to-day)
   - **Keep interactive config.yaml creation** (V2 uses YAML config as primary, env vars as overrides)

3. **`README.md`** — Rewrite for V2:
   - Hardware BOM updated (add ACS712, limit switches, 3-ch relay, 12V battery)
   - V2 pinout table
   - Tailscale setup instructions
   - Environment variable configuration (`DEVICE_API_KEY`, `DEVICE_ID`)
   - AP mode active on first boot; Flask portal serves WiFi setup UI
   - Camera: rpicam-vid live stream (no still captures)
   - API: V2 endpoints, x-api-key auth
   - Link to `docs/device-v2-notes-2026-06-27.md` for full setup guide

4. **`requirements.txt`** — Final cleanup:
   ```txt
   aiohttp>=3.8.0
   APScheduler>=3.10.0
   RPi.GPIO>=0.7.1
   gpiozero>=1.6.2
   adafruit-circuitpython-ads1x15>=2.2.21
   adafruit-blinka>=8.20.0
   adafruit-circuitpython-dht>=3.7.9
   flask>=2.3.0           # AP mode onboarding portal
   werkzeug>=2.3.0        # AP mode onboarding portal
   pyyaml>=6.0
   pydantic>=2.0.0
   watchdog>=3.0.0
   psutil>=5.9.0
   python-systemd>=234
   python-json-logger>=2.0.0
   ```

### Final Verification Checklist

- [ ] `main.py` starts and reads all 5 sensors + ACS712 + limit switches
- [ ] `POST /api/v2/sensors` returns commands which are executed on V2 GPIO relays
- [ ] `start.sh` brings up Tailscale, starts rpicam-vid, registers stream, then `exec`s main.py
- [ ] `growmate.service` starts on boot, restarts on failure, logs to journald
- [ ] Light commands are ignored; fertilizer/pesticide+pump simultaneous activation works
- [ ] No picamera2 or piexif in requirements.txt or imports (flask/werkzeug kept for AP mode onboarding portal)
- [x] network_manager, onboarding_portal, templates, static, hostapd, dnsmasq preserved (AP mode kept)
- [ ] Offline queue, circuit breaker, retry handler, hot-reload config still function
- [ ] Live stream visible in browser dashboard
- [ ] Recordings appear after 60 seconds in dashboard History panel

---

## Cross-Reference Summary

| Section | References |
|---------|------------|
| Gap Analysis | `docs/device-handoff-2026-06-25.md` §§1–8, `docs/device-v2-notes-2026-06-27.md` |
| Architecture Overview | `src/main.py`, `src/api_client.py`, `src/queue_manager.py`, `src/camera_service.py` |
| Phase 1 (Hardware) | `docs/device-handoff-2026-06-25.md` §§1, 5.5–5.7; `docs/device-v2-notes-2026-06-27.md#pinout`; `docs/hardware-2026-06-26.md#v2-hardware-additions`; `docs/wiring-2026-06-26.md#v2-wiring-changes` |
| Phase 2 (API) | `docs/device-handoff-2026-06-25.md` §2; `docs/api-2026-06-27.md#v2-api-device-agent`; `docs/configuration-2026-06-27.md#v2-configuration-device-agent` |
| Phase 3 (Camera) | `docs/device-handoff-2026-06-25.md` §3; `docs/device-v2-notes-2026-06-27.md#camera-streaming`; `docs/hardware-2026-06-26.md#v2-camera-changes` |
| Phase 4 (Network) | `docs/device-handoff-2026-06-25.md` §§6, 7; `docs/device-v2-notes-2026-06-27.md#systemd-service`; `docs/hardware-2026-06-26.md#v2-connectivity` |
| Phase 5 (Cleanup) | `docs/device-handoff-2026-06-25.md` §9; `docs/device-v2-notes-2026-06-27.md#provisioning-steps`; `docs/troubleshooting-2026-06-27.md#v2-specific-troubleshooting` |
| Verification Gates | `docs/device-v2-notes-2026-06-27.md#verify`; `docs/device-handoff-2026-06-25.md` §9 |

---

## Detailed File Inventory

### Files to Create (2)

| File | Phase |
|------|-------|
| `start.sh` | P3 |
| `docs/v2-application-plan-2026-06-26.md` | (this file) |

### Files to Create (2)

| File | Phase | Description |
|------|-------|-------------|
| `start.sh` | P3 | Orchestrates Tailscale → rpicam-vid → stream registration → main.py |
| `docs/v2-application-plan-2026-06-26.md` | — | This plan |

### Files to Modify (14)

| File | Phase | Change Summary | Local-First Addition |
|------|-------|----------------|----------------------|
| `src/sensors.py` | P1 | V2 channels, ACS712, limit switches, hardcoded formulas, 5 required kinds | Per-channel sensor health tracking; limit switch debounce (50ms + 3-of-5); local coulomb counter for ACS712 |
| `src/actuators.py` | P1 | V2 GPIOs, fertilizer/pesticide, no light, simultaneous activation | Relay state journal (log every transition); state reconciliation after execution |
| `src/api_client.py` | P2 | V2 endpoints, x-api-key, stream register, remove camera upload | Stream registration retry with backoff; V2-specific circuit breaker timeouts |
| `src/main.py` | P2/P4 | Remove camera job, add stream reg; keep and improve onboarding path | Async AP mode; WiFi scan in portal; auto-connect after onboarding; failure_monitor re-enters onboarding for recovery |
| `src/utils.py` | P2 | Update FIRMWARE_VERSION, SENSOR_INTERVAL, GPIO constants | Add firmware version file path constant |
| `src/queue_manager.py` | P2 | **Simplified**: remove `image_queue` table and all image methods | Sensor-only queue = less I/O, simpler health stats, smaller DB file |
| `src/upload_processor.py` | P2 | Remove image processing path; update payload to V2 format | Circuit breaker awareness (pause when circuit open) |
| `src/health_monitor.py` | P2/P4 | V2-specific metrics | ACS712 current + SoC, limit switch states, camera PID + crash count, Tailscale IP + status, per-channel sensor health, stream registration state |
| `src/config_manager.py` | P4 | Env var overrides, V2 defaults, remove provisioning | Any YAML key overridable via `GROWMATE_<KEY>` env var; firmware version from file |
| `src/config_validator.py` | P4 | V2 schema updates, remove camera/network validation | Validate `DEVICE_API_KEY` non-empty, `DEVICE_ID` format, interval >= 10s |
| `src/camera_service.py` | P3 | Rewrite as rpicam-vid process manager | Watchdog PID check; auto-restart on crash; crash counter |
| `systemd/growmate.service` | P4 | V2 service with env vars, start.sh, pi user | N/A (systemd level) |
| `scripts/install.sh` | P5 | Keep AP mode (hostapd + dnsmasq), add Tailscale, update paths | Install to `/home/grow/growmate/`; `chmod +x *.sh` |
| `README.md` | P5 | V2 setup, Tailscale, env vars, AP mode onboarding | Document local-first features (queue, circuit breaker, health monitor, hot-reload) |

### Files to Remove (7 — never existed; listed in plan but not in repo)

| File | Phase | Reason |
|------|-------|--------|
| `scripts/test_main_integration.py` | P5 | Tests old main.py |
| `scripts/test_service_deployment.py` | P5 | Tests old service |
| `scripts/test_system_integration.py` | P5 | Tests old e2e flow |
| `scripts/test_core_components.py` | P5 | Tests old constants |
| `scripts/test_failure_recovery.py` | P5 | Tests old patterns |
| `scripts/test_documentation_validation.py` | P5 | Tests old docs |
| `scripts/monitor_performance.py` | P5 | Not V2-relevant |

### Files Kept (AP Mode Onboarding) — Actually Deleted

The following V1 test scripts in `scripts/` were **removed** during V2 migration; their coverage was replaced by proper tests in `tests/`:

| File | Replaced By |
|------|-------------|
| `scripts/test_hardware.py` | `tests/test_sensors.py`, `tests/test_actuators.py` |
| `scripts/test_network_onboarding.py` | `tests/test_network_manager.py`, `tests/test_onboarding_portal.py` |

### Files Kept (AP Mode Onboarding — Locally First, Not Tailscale-Only)

The handoff spec proposed Tailscale-only connectivity. The actual implementation **kept V1's AP mode system** as a first-time setup and recovery mechanism, and **added Tailscale** for day-to-day connectivity:

| File | Role |
|------|------|
| `src/network_manager.py` | AP mode start/stop, WiFi scan, connection management |
| `src/onboarding_portal.py` | Flask web server for WiFi credential entry |
| `templates/index.html` | Onboarding UI |
| `templates/success.html` | Onboarding UI |
| `static/style.css` | Onboarding UI |
| `static/js/setup.js` | Onboarding UI |
| `config/hostapd.conf.template` | AP mode hostapd config |
| `config/dnsmasq.conf.template` | AP mode DNS/DHCP config |

### Files to Keep (Local-First Foundation, Adapted for V2)

| File | Action | V2-Specific Adaptation |
|------|--------|------------------------|
| `src/queue_manager.py` | **Modify** | Remove `image_queue` table and all image-related methods (`enqueue_image`, `async_enqueue_image`, mark_image_*). Keep sensor queue only. Simplify schema. |
| `src/upload_processor.py` | **Modify** | Remove image processing path. Only drain sensor queue. Update payload format to V2. Add circuit breaker awareness (don't upload while circuit is open). |
| `src/circuit_breaker.py` | **Keep** | No code changes needed. V2 adds a third instance for stream registration endpoint. |
| `src/retry_handler.py` | **Keep** | No code changes needed. Configurable per-call timeout already supported. |
| `src/config_watcher.py` | **Keep** | No code changes needed. Hot-reload still works for YAML changes. |
| `src/logging_config.py` | **Keep** | No code changes needed. Correlation IDs still work across V2 flows. |
| `src/health_monitor.py` | **Modify** | Add V2-specific metrics: ACS712 current, limit switch states, camera PID + crash count, Tailscale IP + status, per-channel sensor health. |
| `LICENSE` | Keep | Unchanged |
| `.gitignore` | Keep | Unchanged |

---

## Verification Gates

| Gate | Phase | V2 Match Test | Local-First Test |
|------|-------|---------------|------------------|
| **G1** | P1 | `SensorReader` returns 5 sensor kinds with V2 ADC mapping (ch0=ACS712, ch3=soil). Temperature is float, -40–125 range. | 3 consecutive DHT22 failures → health monitor shows "DHT22_DEGRADED". No crash. |
| **G2** | P1 | `process_commands([{"kind":"pump"},{"kind":"fertilizer"}])` activates pump=10 + fertilizer=17 for max(durationMs). Light commands ignored. | Relay state journal logs every transition. State reconciliation warns on GPIO mismatch. Limit switch debounce rejects <50ms pulses. |
| **G3** | P2 | `POST /api/v2/sensors` with `x-api-key` returns commands. `POST /api/v2/stream/register` returns `{"success":true}`. | POST failure → payload goes to `sensor_queue` table. Circuit breaker opens after 5 failures. Stream registration retries on failure. |
| **G4** | P2 | `main.py` has no camera capture job. Imports `network_manager` and `onboarding_portal` for AP mode onboarding. | Queue has no `image_queue` table. UploadProcessor has no image path. |
| **G5** | P3 | `rpicam-vid` starts from `start.sh`. Stream register succeeds. Verifiable in browser dashboard. | Kill rpicam-vid → health monitor restarts it within 30s. 5+ crashes in 1h → UNHEALTHY. |
| **G6** | P3 | `grep -r "picamera2\|piexif\|raspistill\|raspivid" src/` returns nothing. | Camera crash counter exposed in health monitor metrics. |
| **G7** | P4 | Network manager + onboarding portal present; AP mode starts on unprovisioned boot. | `tailscale status` failure → health monitor reports "TAILSCALE_DISCONNECTED". No crash. Device still serves AP mode for recovery. |
| **G8** | P4 | Service file has `Environment=DEVICE_API_KEY`, `Environment=DEVICE_ID`, `ExecStart=...start.sh`, `User=grow`. | Health monitor publishes Tailscale IP every 5 min. Any YAML key overridable via env var `GROWMATE_<KEY>`. `Failure monitor re-enters onboarding on excessive failures.` |
| **G9** | P5 | `test_hardware.py` tests V2 pins (pump=10, fertilizer=17, pesticide=27), all 4 ADC channels, ACS712, limit switches. | Tests also verify debounce behavior, health monitor output format, circuit breaker state transitions. |
| **G10** | P5 | `pip install -r requirements.txt` succeeds. No picamera2/piexif (flask/werkzeug kept for AP mode onboarding). | `sqlite3 /var/lib/growmate/queue.db ".tables"` shows only `sensor_queue` and `queue_metadata` (no image_queue). |

---

## Execution Order

```
Phase 1 (Hardware) ──────────┐
                              ├── Phase 2 (API) needs P1 for sensor/actuator API
Phase 3 (Camera)   ──────────┤
                              │
Phase 2 (API)      ──────────┼── Phase 4 (Network) needs P2 for imports removed
                              │
Phase 4 (Network)  ──────────┼── Phase 5 (Cleanup) needs everything else done
                              │
Phase 5 (Cleanup)  ──────────┘
```

**Parallel work:** P1 and P3 can run concurrently (they touch different files). P2 can start after P1's sensor/actuator API is stable (but they don't overlap on files, so they can mostly run in parallel with awareness). P4 waits for P2. P5 waits for all.
