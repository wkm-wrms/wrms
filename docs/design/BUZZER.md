# BUZZER.md — Functional Specification: Hardware Buzzer Module

**Feature:** ESP32-C3-based hardware audio/visual alerter, integrated with WRMS via a dedicated public API.
**Status:** In progress — server API done, firmware scaffold done, field testing pending.
**Last updated:** 2026-03-31
**Target hardware:** ESP32-C3 DevKitC-1

---

## 1. Concept Overview

The buzzer is a standalone IoT device that connects to the WRMS server over WiFi and generates
audio/visual alerts at race-critical moments (flight start, end-of-flight warning, countdown).
It acts as a physical complement to the dashboard's TTS and sound system — audible even without
speakers, and usable simultaneously with the main panel.

Multiple buzzers can connect to the same endpoint (e.g. one per side of the track).

---

## 2. Hardware

### 2.1 Bill of Materials

| Component | Details | Role |
|---|---|---|
| ESP32-C3 DevKitC-1 | RISC-V, single-core 160 MHz, WiFi + BT | Main controller |
| Active buzzer | 3.3–5 V, e.g. TMB12A05 or equivalent | Audio alerts |
| NPN transistor or MOSFET (optional) | e.g. 2N2222 / 2N7000 | Buzzer driver if >40 mA |
| USB-C cable | For programming and power | — |

**Optional — external RGB LED variant** (set `LED_USE_ONBOARD_SINGLE=0` in `led_rgb.h`):

| Component | Details | Role |
|---|---|---|
| RGB LED — common cathode | 5 mm, or separate R/G/B LEDs | State indicator |
| Resistors — 3 × 100 Ω | Through-hole or 0805 SMD | LED current limiting |

> **Note on buzzer current:** ESP32-C3 GPIO is rated 40 mA max per pin. Most active buzzers
> draw 20–40 mA at 3.3 V and can be driven directly from GPIO. If your buzzer requires more
> current or runs on 5 V, add an NPN transistor (base via 1 kΩ to GPIO, collector to buzzer+,
> emitter to GND, buzzer− to 5 V rail).

---

### 2.2 LED Backend Configuration

The firmware supports two LED backends, selected at compile time in `main/led_rgb.h`:

```c
#define LED_USE_ONBOARD_SINGLE  1   // 1 = onboard LED (default), 0 = external RGB
```

#### Option A — Onboard LED (default, `LED_USE_ONBOARD_SINGLE=1`)

Uses the built-in blue LED on GPIO8 of the ESP32-C3 DevKitC-1. No external components required.

| State | Blink pattern | Meaning |
|---|---|---|
| Connected, API OK | **off** (LED off) | Normal operation |
| Disconnected / portal | **fast blink** 200 ms on/off | No WiFi |
| WiFi OK, API down | **slow blink** 800 ms on/off | API unreachable |
| Alarm fires | **brief flash** (80 ms off) | Alert triggered |

#### Option B — External RGB LED (`LED_USE_ONBOARD_SINGLE=0`)

Three-colour external LED on GPIO6/7/8.

| State | Colour | Meaning |
|---|---|---|
| Disconnected / portal | **Red** solid | No WiFi |
| Connected, API OK | **Green** solid | Normal operation |
| WiFi OK, API down | **Yellow** solid | API unreachable |
| Alarm fires | brief flash of current colour | Alert triggered |

---

### 2.3 GPIO Assignment

| GPIO | Signal | Notes |
|---|---|---|
| **5** | Buzzer | Active buzzer positive terminal (HIGH = on) |
| **8** | Onboard LED | Built-in blue LED — Option A only |
| **6** | LED Red | External RGB — Option B only, via 100 Ω |
| **7** | LED Green | External RGB — Option B only, via 100 Ω |
| **8** | LED Blue | External RGB — Option B only, via 100 Ω |
| GND | Common ground | Buzzer −, LED cathode |

> **Note:** GPIO8 is shared between the onboard LED and the external RGB Blue channel.
> Do not connect an external LED on GPIO8 when using Option A.

Pins chosen to avoid ESP32-C3 reserved signals:

| GPIO | Reason to avoid |
|---|---|
| 2 | Strapping pin — affects boot mode |
| 9 | BOOT button on DevKitC-1 |
| 18, 19 | USB D−/D+ (used by USB-Serial on DevKitC-1) |

---

### 2.4 Wiring Diagram

#### Option A — Onboard LED (no external components)

```
ESP32-C3 DevKitC-1
┌──────────────────────────────────────────────────┐
│                                                  │
│  GPIO5 ────────────────────────── [BUZZER +]     │
│  GND   ────────────────────────── [BUZZER −]     │
│                                                  │
│  GPIO8 ── onboard blue LED (built-in, no wiring) │
│                                                  │
│  USB-C ── PC (flash / power)                     │
└──────────────────────────────────────────────────┘
```

**Active buzzer polarity:**
```
[BUZZER]
  +  →  GPIO5  (HIGH = on)
  −  →  GND
```

#### Option B — External RGB LED

```
ESP32-C3 DevKitC-1
┌──────────────────────────────────────────────────┐
│                                                  │
│  GPIO5 ────────────────────────── [BUZZER +]     │
│  GND   ────────────────────────── [BUZZER −]     │
│                                                  │
│  GPIO6 ──[100Ω]── R anode  ┐                    │
│  GPIO7 ──[100Ω]── G anode  ├─ RGB LED            │
│  GPIO8 ──[100Ω]── B anode  │  (common cathode)   │
│  GND   ────────── cathode  ┘                    │
│                                                  │
│  USB-C ── PC (flash / power)                     │
└──────────────────────────────────────────────────┘
```

**RGB LED (common cathode):**
```
R anode  →  [100Ω]  →  GPIO6
G anode  →  [100Ω]  →  GPIO7
B anode  →  [100Ω]  →  GPIO8
cathode  →  GND
```

Yellow (API unreachable) is produced by driving GPIO6 (Red) + GPIO7 (Green) simultaneously.

---

### 2.5 Power

The device is powered via USB-C (5 V from the DevKitC-1 board, 3.3 V regulated on-board).
No external power supply is required for the reference build.

For a standalone (no PC) deployment, use any USB-C power bank or a 5 V USB adapter.

---

## 3. Device States

### 3.1 DISCONNECTED (AP / Captive Portal mode)

**Trigger:** No known WiFi network reachable on startup, or API endpoint unreachable.

**Behaviour:**
- ESP32 starts in AP+STA mode (simultaneous Access Point and Station).
- AP name: `WKM-Buzzer-XXYYZZ` where `XXYYZZ` are the last 3 bytes of the device's base MAC address in uppercase hex (e.g. `WKM-Buzzer-A1B2C3`). Unique per device — allows multiple buzzers to operate in the same location without SSID collision.
- DNS redirects all traffic to the captive portal IP (classic captive portal pattern).
- LED: **fast blink** (onboard) / **Red solid** (external RGB). See section 2.2.
- In the background: continuously scans for known networks and attempts connection.
  If a known network appears, attempts login without interrupting the portal.

**Captive portal UI (simple HTML page served by ESP32):**
1. List of discovered SSIDs (refreshable).
2. Password field for selected SSID.
3. API endpoint URL (e.g. `http://192.168.1.10:8000/api/buzzer`).
4. Timezone selector (POSIX string, e.g. `CET-1CEST,M3.5.0,M10.5.0/3`).
5. "Connect" button.
6. **Diagnostics log** (shown if a previous connection attempt was made):
   - `WIFI_NOT_FOUND` — SSID not detected
   - `WIFI_AUTH_FAILED` — wrong password
   - `API_UNREACHABLE` — connected to WiFi but endpoint timed out
   - `API_INVALID_RESPONSE` — endpoint returned unexpected data
   - `NTP_FAILED` — time sync failed

**On "Connect" submit:**
1. Save SSID + password to NVS (non-volatile storage), appending to the known-networks list.
2. Save API URL and timezone to NVS.
3. Attempt WiFi connection.
4. On failure: signal error with buzzer (3 short beeps), show diagnostic log, stay in portal.
5. On success: proceed to CONNECTED state.

### 3.2 CONNECTED (Operational mode)

**Trigger:** Successfully connected to WiFi and received a valid response from the API endpoint.

**Behaviour:**
- LED: **off** (onboard) / **Green solid** (external RGB). See section 2.2.
- Polls `GET /api/buzzer` every **5 seconds** during FLIGHT phase,
  every **10 seconds** during PREP/IDLE (determined from response).
- Maintains a local queue of upcoming alarms (downloaded from API).
- Executes alarms at the scheduled UTC time (compared against NTP-synced clock).
- Executed alarm IDs are tracked in RAM to prevent duplicate firing on the next poll.
- If API becomes unreachable: LED turns **yellow**, keep executing already-queued alarms,
  retry every 5 seconds. If connection restored: back to green.
- If WiFi drops: attempt reconnection to known networks. LED red.

---

## 4. Network and Persistence

### 4.1 Known Networks (NVS)
Stored as a list of `{ssid, password}` pairs in NVS partition.
On startup:
1. Scan available networks.
2. Compare with known list.
3. Try to connect to first match.
4. If none found: start AP mode immediately, continue scanning in background.

### 4.2 Configuration (NVS)
```
api_url      — full URL of the buzzer endpoint
timezone     — POSIX timezone string
```

### 4.3 Time Sync (NTP)
- NTP server: `pool.ntp.org` (configurable in firmware).
- Sync on every WiFi connection establishment.
- Re-sync every 60 minutes to prevent drift.
- Timezone applied via `setenv("TZ", ...)` / `tzset()` (ESP-IDF standard pattern).

---

## 5. Alert Design

### 5.1 Design Decision: Lexicon vs. Raw Sequence

**Recommendation: Lexicon-based types, patterns owned by firmware.**

| Approach | Pros | Cons |
|---|---|---|
| **Lexicon** (server sends named type, firmware plays pattern) | Simple protocol, small payloads, patterns are stable UX | Firmware update needed to add new patterns |
| **Raw sequence** (server sends exact beep timings) | Full server control, no firmware updates | Complex protocol, large payloads, pattern design leaks into server code |

**Decision:** Use named types. The buzzer is a physical UX element — its patterns should be
consistent and recognisable to pilots, not variable per session. The server knows *what* event
is happening; the buzzer knows *how* to signal it.

Future option: add optional `override_sequence` field to the API response for special cases,
without breaking the normal lexicon flow.

### 5.2 Alarm Types and Patterns

| Type | Trigger | Pattern | Meaning |
|---|---|---|---|
| `PREP_START` | Preparation phase begins | 2 × short (100 ms on / 200 ms off) | Next group: to positions |
| `FLIGHT_START` | Flight phase begins | 1 × long (800 ms) | Go! |
| `FLIGHT_WARNING_30` | 30 s before flight end | 3 × short (100 ms on / 150 ms off) | 30 seconds left |
| `COUNTDOWN` | Seconds 10 → 1 before end | 1 × short (80 ms) per second (10 alarms, 1 s apart) | Countdown |
| `FLIGHT_END` | Flight phase ends | long–short–short (700 ms / 150 ms / 200 ms / 150 ms / 200 ms) | Stop flying |
| `SESSION_END` | Session finished | 3 × long (600 ms on / 400 ms off) | Session done |

LED during alarm execution: brief flash of the active colour (100 ms off → on → off).

### 5.3 Alarm Timing (Server-computed)

The server computes alarm fire times from the current heat state on every poll:

```
now = server UTC time
flight_ends_at = now + live_seconds_left          # when FLIGHT phase ends

FLIGHT_WARNING_30 → fire at: flight_ends_at − 30s  (if > now)
COUNTDOWN(10)     → fire at: flight_ends_at − 10s
COUNTDOWN(9)      → fire at: flight_ends_at − 9s
...
COUNTDOWN(1)      → fire at: flight_ends_at − 1s
FLIGHT_END        → fire at: flight_ends_at
```

Alarms already in the past (< now) are omitted from the response.
The look-ahead window is **120 seconds** — prevents the response from growing unbounded
when polled far in advance.

---

## 6. API Endpoint

### `GET /api/buzzer`

Public endpoint (no authentication). Returns upcoming alarms within the look-ahead window.

**Response — active session, FLIGHT phase:**
```json
{
  "status": "ok",
  "server_time": "2026-03-30T14:23:47.123Z",
  "phase": "FLIGHT",
  "poll_interval_sec": 5,
  "alarms": [
    {
      "id": "heat-3-WARNING_30",
      "fire_at": "2026-03-30T14:24:00.000Z",
      "type": "FLIGHT_WARNING_30"
    },
    {
      "id": "heat-3-COUNTDOWN-10",
      "fire_at": "2026-03-30T14:24:17.000Z",
      "type": "COUNTDOWN"
    }
  ]
}
```

**Response — no active session:**
```json
{
  "status": "ok",
  "server_time": "2026-03-30T14:23:47.123Z",
  "phase": "IDLE",
  "poll_interval_sec": 15,
  "alarms": []
}
```

**Alarm ID scheme:** `heat-{heat_number}-{type}[-{countdown_value}]`
The buzzer uses `id` to deduplicate — never fires the same `id` twice per session.

**Notes:**
- `poll_interval_sec` tells the buzzer how often to poll — server adapts this to phase.
- `server_time` is used by the buzzer to calculate drift correction (alarm `fire_at` minus
  `server_time` gives relative offset — more robust than relying solely on NTP alignment).

---

## 7. Session Parameters Extension

For MVP: alarm configuration is hardcoded in the server (defaults from section 5.2).
For future: add `buzzer_config` block to session, allowing per-session overrides:

```json
{
  "buzzer_enabled": true,
  "warning_at_seconds": 30,
  "countdown_from_seconds": 10
}
```

---

## 8. Gaps and Open Questions

| # | Item | Decision |
|---|---|---|
| 1 | **Alarm deduplication across sessions** | Buzzer clears executed-ID list on session change (detected via `phase == IDLE` after active) |
| 2 | **Buzzer loses connection mid-flight** | Execute already-queued alarms from local queue; retry API in background |
| 3 | **Multiple buzzers** | Fully supported — each polls independently; no server-side registration |
| 4 | **OTA firmware updates** | Out of scope for MVP; ESP-IDF OTA is feasible future addition |
| 5 | **Timezone only needed for display** | API returns UTC; timezone stored in NVS only for potential future display on OLED |
| 6 | **Captive portal HTTPS** | HTTP only (local network); no TLS needed on portal |
| 7 | **Active buzzer vs. passive** | Active buzzer (simple GPIO HIGH/LOW) assumed; passive buzzer would require PWM/LEDC |
| 8 | **RGB LED type** | Assumes 3 separate GPIO pins (R/G/B); common-anode variant needs inverted logic |

---

## 9. Files to Create / Modify

### Server (WRMS)

| File | Change |
|---|---|
| `code/routers/buzzer_api.py` | New — `GET /api/buzzer` endpoint |
| `code/routers/__init__.py` | Register new router |
| `code/tests/test_buzzer_api.py` | New — functional + regression tests |

### Firmware (ESP32)

```
buzzer/
  CMakeLists.txt               — top-level ESP-IDF project
  sdkconfig.defaults           — default Kconfig options
  partitions.csv               — NVS partition table
  main/
    CMakeLists.txt
    main.c                     — entry point, state machine
    wifi_manager.c / .h        — AP+STA, known-networks list, background scan
    captive_portal.c / .h      — DNS hijack + HTTP server for config UI
    nvs_config.c / .h          — read/write NVS (networks, api_url, timezone)
    ntp_sync.c / .h            — NTP initialisation and periodic re-sync
    api_client.c / .h          — HTTP GET /api/buzzer, JSON parsing (cJSON)
    alarm_scheduler.c / .h     — local alarm queue, dedup, fire logic
    buzzer_gpio.c / .h         — GPIO control, pattern playback (FreeRTOS task)
    led_rgb.c / .h             — RGB LED state machine (LEDC PWM or plain GPIO)
```

---

## 10. Implementation Phases

### Phase 1 — Server API (MVP)
1. Implement `GET /api/buzzer` with hardcoded alarm offsets.
2. Add tests.
3. Verify response format with a simple `curl` / Postman test.

### Phase 2 — ESP32 Firmware Core
1. Project scaffold (ESP-IDF, CMake, partitions).
2. NVS config read/write.
3. WiFi connection (known networks list).
4. NTP sync.
5. HTTP poll + JSON parse.
6. Alarm scheduler (FreeRTOS timer-based).
7. Buzzer GPIO patterns.
8. RGB LED states.

### Phase 3 — Captive Portal
1. AP mode + DNS hijack.
2. HTTP server with config form.
3. Network scan list.
4. Diagnostic log.
5. Background STA scan while portal active.

### Phase 4 — Integration & Field Testing
1. End-to-end test with real hardware.
2. Timing accuracy validation (alarm drift < 200 ms acceptable).
3. Reconnection scenario tests.
