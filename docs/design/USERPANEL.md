# USERPANEL.md — Functional Specification: Pilot Public View (Frontend 2)

**Feature:** `/pilot/{session_id}` — mobile-first public view accessible via QR code from the main dashboard.
**Status:** Proposed — pending implementation.
**Last updated:** 2026-03-30

---

## 1. Overview

The Pilot Public View is a read-only, login-free panel optimised for smartphones in portrait mode.
Pilots scan a QR code displayed on the main dashboard (`dashboard.html`) and immediately see the
live state of the training session: who is flying, who prepares next, and how much time remains.

**No audio.** No admin controls. No login.

---

## 2. URL and Access

| Property | Value |
|---|---|
| URL | `/pilot/{session_id}` |
| Auth required | No |
| Session token / QR token | Uses the plain `session_id` for now (QR-token per requirements is future work) |
| Accessible when | Session exists and `current_phase != 'FINISHED'` |
| Fallback when session ended | Shows "Sesja zakończona" screen — no redirect, no error |

---

## 3. QR Code on Dashboard

A QR code is permanently displayed in the **bottom-left corner** of `dashboard.html`.

- Generated client-side with a lightweight JS library (e.g. `qrcode.js` — no server dependency).
- Encodes the full URL: `https://<host>/pilot/<session_id>`.
- The session ID is fetched from the existing `/api/heat` poll response (which already contains `session_id`).
- Shown as soon as the session is active; hidden when there is no session data.
- Size: fixed ~120×120 px, semi-transparent background so it does not obscure pilot cards.

---

## 4. Data Source

The panel polls `GET /api/heat` every **3 seconds** — the same public endpoint used by `dashboard.html`.
No new API endpoint is needed for MVP.

`GET /api/session` is protected by `require_admin` and is not accessible without login.

Fields used:

| Field | Used for |
|---|---|
| `heat.status` | Status banner colour and label (PREP/FLIGHT/PAUSED/FINISHED) |
| `heat.heat_number` | Current heat number display |
| `heat.live_seconds_left` | Countdown timer (server-side calculated) |
| `heat.channels` | Current pilots: `pilot.name`, `vtx`, `is_digital`, `status` |
| `next_heat.channels` | Next group pilots |

---

## 5. Screens / States

### 5.1 No active session
```
┌─────────────────────┐
│     WKM RACE        │
│                     │
│   Brak aktywnej     │
│      sesji          │
│                     │
│  [odświeża co 5s]   │
└─────────────────────┘
```
- Polls every 5 s. Automatically transitions to active view when a session starts.

### 5.2 Session active — IDLE (not yet started)
```
┌─────────────────────┐
│     WKM RACE        │
│  ● Sesja aktywna    │
│                     │
│  Trening niedługo   │
│   się rozpocznie    │
│                     │
│  [odświeża co 5s]   │
└─────────────────────┘
```

### 5.3 Session active — PREP / FLIGHT (main view)
```
┌─────────────────────┐
│  ● PRZYGOTOWANIE    │  ← or LECI depending on phase
│      01:45          │  ← live countdown
├─────────────────────┤
│  AKTUALNY BIEG  #3  │
│  ┌───────────────┐  │
│  │ R1  NickA     │  │
│  │ R3  NickB     │  │
│  │ R6  NickC 🔵  │  │
│  │ R7  NickD 🔵  │  │
│  └───────────────┘  │
├─────────────────────┤
│  NASTĘPNA GRUPA     │
│  ┌───────────────┐  │
│  │ R1  NickE     │  │
│  │ R3  ——        │  │
│  │ R6  NickF 🔵  │  │  ← digital badge
│  │ R7  NickG 🔵  │  │
│  └───────────────┘  │  ← paused pilots shown with PAUZA label
└─────────────────────┘
```

Key UI elements:
- **Status banner** (top): phase label + live countdown. Colour: cyan for PREP, green for FLIGHT, yellow for PAUSED.
- **Current heat card**: heat number, list of R1/R3/R6/R7 slots with pilot names. Empty slots show "—".
- **Next group card**: same layout. If no next heat (last group), shows "Ostatnia grupa".
- **Digital badge**: small coloured dot (blue) next to names on digital channels.
- **Paused pilot**: name shown with strikethrough + small "PAUZA" badge (yellow), same style as other views.
- **No admin controls.** No buttons, no drag-and-drop, no session controls.

### 5.4 Session PAUSED
Same layout as 5.3, status banner shows "PAUZA" in yellow. Timer frozen.

### 5.5 Session FINISHED
```
┌─────────────────────┐
│     WKM RACE        │
│                     │
│  Sesja zakończona   │
│    Dziękujemy!      │
│                     │
└─────────────────────┘
```
No more polling once `current_phase == 'FINISHED'`.

---

## 6. Layout — Mobile Portrait

```
viewport: 100vw × 100dvh, no overflow
font: system-ui / Segoe UI
background: dark (#0a0a0a or #161616)
text: light (#eee)
```

Structure (flex column, full height):

```
┌── header (status + timer) ── flex: 0 0 auto ──────────┐
│   phase label  +  MM:SS                                │
├── current-heat card ── flex: 1 1 auto ────────────────┤
│   heat number + pilot rows                             │
├── next-heat card ── flex: 0 0 auto ───────────────────┤
│   pilot rows                                           │
├── footer ── flex: 0 0 auto ───────────────────────────┤
│   "Odświeżono: HH:MM:SS"                               │
└────────────────────────────────────────────────────────┘
```

Pilot row:
```
[channel label]  [pilot name]  [vtx badge?]  [PAUZA?]
R1               NickA
R7               NickD         DJI
R3               NickB                       PAUZA
```

Font sizes (clamp):
- Phase label: `clamp(1.4rem, 5vw, 2rem)`
- Timer: `clamp(3rem, 12vw, 5rem)`
- Pilot name: `clamp(1.1rem, 4vw, 1.6rem)`
- Channel label: `clamp(0.9rem, 3vw, 1.2rem)`

---

## 7. Timer Logic

Identical to `dashboard.html`:
- On each poll, receive `live_seconds_left` from the heat object.
- Set `timerEnds = Date.now() + live_seconds_left * 1000`.
- `setInterval(tick, 100)` renders `MM:SS` from `timerEnds - Date.now()`.
- When `live_seconds_left <= 0` → trigger immediate poll.
- No sounds are played.

---

## 8. Routing

New FastAPI route in `main.py`:

```python
@app.get("/pilot/{session_id}")
async def pilot_view(session_id: str):
    return FileResponse("static/pilot.html")
```

The `session_id` in the URL is not validated server-side for the HTML response — the JS inside
`pilot.html` reads it from `window.location.pathname` and passes it to the API calls.

> **Note:** `GET /api/session` currently returns the *active* session regardless of session_id.
> For MVP this is acceptable (there is only one active session at a time). If multiple concurrent
> sessions are needed in the future, add `GET /api/session/{session_id}` endpoint.

---

## 9. QR Code Library

Use **qrcode-generator** (MIT, no dependencies, ~10 KB) served as a local static file:
- Download `qrcode.min.js` to `static/js/qrcode.min.js`.
- Include in `dashboard.html` with a `<script>` tag.
- Render into a `<canvas>` or `<div id="qr-code">` element.

Alternative: **qrcodejs** (`qrcode.js`). Both are acceptable.

---

## 10. Out of Scope (MVP)

| Feature | Reason |
|---|---|
| QR token (not session_id) | Requires `qr_token` field on Session model — future work |
| Push / WebSocket updates | Polling at 3 s is sufficient; SSE excluded due to hosting constraints |
| Pilot self-identification | "Who am I?" personalisation — future feature |
| Text-to-speech | Frontend 1 only |
| Session history / results | Separate feature |

---

## 11. Files to Create / Modify

| File | Change |
|---|---|
| `static/pilot.html` | New — mobile pilot view |
| `static/js/qrcode.min.js` | New — QR code library (downloaded, no CDN) |
| `static/dashboard.html` | Add QR code widget (bottom-left, uses `qrcode.min.js`) |
| `main.py` | Add `GET /pilot/{session_id}` route |

---

## 12. Test Plan

- `test_pilot_view.py` — functional tests:
  - `GET /pilot/{valid_session_id}` returns 200 with HTML
  - `GET /pilot/{unknown_id}` returns 200 (HTML; JS handles the empty state)
  - `GET /api/session` used by the view returns correct phase and pilot data
  - Paused pilots have `status == 'paused'` in session response (already covered)
- Manual / visual:
  - Portrait mode rendering on real device (or DevTools mobile emulation)
  - QR code on dashboard scans correctly and opens pilot view
  - Timer counts down in sync with dashboard
  - Paused pilot badge visible
  - FINISHED state stops polling and shows goodbye screen
