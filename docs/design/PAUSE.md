# Pause / Resume — Functional Specification

## Status: Pending implementation

---

## Scope

The MC can pause and resume the active training session at any point during
a running heat — both during the PREP phase and the FLIGHT phase.
Pausing freezes the countdown timer. Resuming continues it from the exact
second it was frozen. The paused state survives a server process restart.

---

## State Machines

### Session-level (`session.current_phase`)

```
IDLE → FLIGHT (session.start())
FLIGHT → PAUSED  (session.pause())
PAUSED → FLIGHT  (session.resume())
FLIGHT → FINISHED (session.stop())
```

`session.current_phase = 'PAUSED'` already exists in the DB schema
(`CHECK` constraint includes `'PAUSED'`). `phase_before_pause` is also
already a column in the `session` table — it stores the phase to return to
on resume (always `'FLIGHT'` in the current design).

### Heat-level (`heat.status`)

```
PREP   → PAUSED  (heat.pause() called when session pauses during PREP)
FLIGHT → PAUSED  (heat.pause() called when session pauses during FLIGHT)
PAUSED → PREP    (heat.resume() called when session resumes from PREP-pause)
PAUSED → FLIGHT  (heat.resume() called when session resumes from FLIGHT-pause)
```

`heat.status = 'PAUSED'` is a valid value (already in DB `DEFAULT 'INIT'` column).
`heat.remaining_seconds_at_pause` and `heat.last_resume_at` columns already exist.

---

## New DB field required: `heat.phase_before_pause`

The `heat` table does **not** have a `phase_before_pause` column yet.
It is needed so the heat knows whether to restore to PREP or FLIGHT on resume.

**Migration (idempotent):**
```sql
ALTER TABLE heat ADD COLUMN phase_before_pause TEXT;
```

No default value — `NULL` means heat was never paused.

---

## What already works (no changes needed)

| Component | Status |
|---|---|
| `heat.get_remaining_seconds()` | Returns `remaining_seconds_at_pause` when `status == 'PAUSED'` |
| `heat_api.py` `live_seconds_left` | Computed server-side on every request — automatically frozen during PAUSED |
| `session.current_phase` CHECK | 'PAUSED' already in constraint |
| `session.phase_before_pause` column | Already in DB and persisted by `save_session_data()` |
| `heat.remaining_seconds_at_pause` | Already in DB and persisted by `create_or_update_heat()` |
| `heat.last_resume_at` | Already in DB and persisted by `create_or_update_heat()` |
| `session.loop()` | Returns `False` when `current_phase != 'FLIGHT'` — timer won't advance while PAUSED |
| Frontend PAUZA / WZNÓW buttons | Already in `session.html`, call correct endpoints |
| `pauseSession()` / `resumeSession()` JS | Already call API and stop/start local timer |

---

## Changes required

### 1. `heat.py`

**Add field:**
```python
phase_before_pause: Optional[str] = None
```

**Extend `pause()`** — support both PREP and FLIGHT:
```python
def pause(self):
    if self.status not in ('PREP', 'FLIGHT'):
        raise ValueError("Cannot pause: heat is not in PREP or FLIGHT phase.")
    self.phase_before_pause = self.status
    self.remaining_seconds_at_pause = self.get_remaining_seconds()
    self.status = 'PAUSED'
```

**Extend `resume()`** — restore correct phase and recalculate timers:
```python
def resume(self):
    now = datetime.now()
    if self.phase_before_pause == 'FLIGHT':
        self.last_resume_at = now
        self.status = 'FLIGHT'
    elif self.phase_before_pause == 'PREP':
        # Rewind prep_started_at so the remaining time is preserved:
        # remaining = prep_time - (now - prep_started_at)
        # → prep_started_at = now - (prep_time - remaining)
        elapsed_before_pause = self.prep_time - self.remaining_seconds_at_pause
        self.prep_started_at = now - timedelta(seconds=elapsed_before_pause)
        self.status = 'PREP'
    self.phase_before_pause = None
```

Note: `timedelta` import from `datetime` already present.

**`__init__`:** add `phase_before_pause: Optional[str] = None` parameter and pass to `super().__init__`.

---

### 2. `database.py`

**`_init_tables()`** — add column to heat CREATE TABLE:
```sql
phase_before_pause TEXT
```

**Idempotent migration** (added to the existing `_adds` list):
```python
"ALTER TABLE heat ADD COLUMN phase_before_pause TEXT",
```

**`create_or_update_heat()` INSERT** — add `phase_before_pause` to column list and params.

**`create_or_update_heat()` UPDATE** — add `phase_before_pause=?` to SET clause.

**`get_heat_by_number()` SELECT** — add `phase_before_pause` to SELECT.

**`Heat(...)` construction in `get_heat_by_number()`** — pass `phase_before_pause=row["phase_before_pause"]`.

---

### 3. `session.py`

**Replace the stub `pause()` method:**
```python
def pause(self):
    if self.current_phase != 'FLIGHT':
        raise ValueError("Cannot pause: session is not running.")
    if not self.current_heat or self.current_heat.status not in ('PREP', 'FLIGHT'):
        raise ValueError("No pausable heat active.")
    self.phase_before_pause = self.current_phase
    self.current_heat.pause()
    self.current_phase = 'PAUSED'
```

**Add `resume()` method:**
```python
def resume(self):
    if self.current_phase != 'PAUSED':
        raise ValueError("Cannot resume: session is not paused.")
    self.current_heat.resume()
    self.current_phase = self.phase_before_pause or 'FLIGHT'
```

---

### 4. `session_api.py`

**`pause_timer()`:**
```python
@router.post("/pause")
async def pause_timer(_: str = Depends(require_admin)):
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    try:
        session.pause()
    except (ValueError, NotImplementedError) as e:
        return {"status": "error", "message": str(e)}
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    return {"status": "ok"}
```

**`resume_timer()`:**
```python
@router.post("/resume")
async def resume_timer(_: str = Depends(require_admin)):
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    try:
        session.resume()
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    return {"status": "ok"}
```

---

### 5. `session.html`

**Problem:** After pressing PAUZA, the local timer in session.html immediately stops
(`stopTimer()`). But the WZNÓW button is hidden with `display:none` and the PAUZA button
stays visible — the MC has no visual confirmation that the session is paused, and cannot
resume it.

**Fix in `rendertHeats()`** — toggle button visibility based on `heat.status`:
```javascript
const isPaused = heat.status === 'PAUSED';
document.getElementById('btnPause').style.display  = isPaused ? 'none'  : '';
document.getElementById('btnResume').style.display = isPaused ? ''      : 'none';
```

Additionally, after a successful `pauseSession()` call, immediately flip the buttons
without waiting for the next poll (5-second latency):
```javascript
async function pauseSession() {
    // ... existing fetch + error check ...
    stopTimer();
    document.getElementById('btnPause').style.display  = 'none';
    document.getElementById('btnResume').style.display = '';
}

async function resumeSession() {
    // ... existing fetch + error check ...
    startTimer();
    document.getElementById('btnPause').style.display  = '';
    document.getElementById('btnResume').style.display = 'none';
}
```

---

## Timer synchronisation after resume

`heat_api.py` returns `live_seconds_left = heat.get_remaining_seconds()` on every poll.

After resume, `heat.get_remaining_seconds()` for FLIGHT returns:
```
remaining_seconds_at_pause - (now - last_resume_at)
```
For PREP (after `prep_started_at` was rewound):
```
prep_time - (now - prep_started_at)   # = remaining_seconds_at_pause - elapsed since resume
```

Both correctly count down from where the pause was. The dashboard timer
(`currentTimerEnds = Date.now() + secs * 1000`) is reset on the next
`updateHeats()` poll, so within 5 seconds it is fully re-synchronised.
No additional changes to `heat_api.py` are needed.

---

## Server restart recovery

On restart, `main.py` calls `db.get_active_session()` → `get_session_by_id()`.
This reloads:
- `session.current_phase` (may be `'PAUSED'`) — loop() returns False, no timer runs
- `session.phase_before_pause` — stored
- `heat.status` (may be `'PAUSED'`) — `get_remaining_seconds()` returns `remaining_seconds_at_pause`
- `heat.remaining_seconds_at_pause` — frozen value returned by API to dashboard
- `heat.phase_before_pause` — needed to know which phase to restore on resume

The resumed session continues from the exact point of the pause.

---

## Tests to write (`test_pause_resume.py`)

| Test | Covers |
|---|---|
| Pause during FLIGHT phase → heat.status == PAUSED | Happy path FLIGHT |
| Pause during PREP phase → heat.status == PAUSED | Happy path PREP |
| Resume from FLIGHT pause → status FLIGHT, timer continues | Resume FLIGHT |
| Resume from PREP pause → status PREP, prep_started_at recalculated | Resume PREP |
| `get_remaining_seconds()` frozen at pause value after pause | Timer freeze |
| `get_remaining_seconds()` counts down after resume | Timer resume |
| Pause without active session → error | Guard |
| Double pause → error | Guard |
| Resume without being paused → error | Guard |
| `session.current_phase` changes on pause/resume | Session state |
| DB persistence: pause state survives `save_session_data()` + reload | Persistence |
| Pause + DB save + fresh `RaceDatabase` instance → still PAUSED | Restart simulation |
| `GET /api/heat` returns frozen `live_seconds_left` during pause | API |
| `POST /api/session/pause` requires auth | Auth |
| `POST /api/session/resume` requires auth | Auth |

---

## Open questions

None — all decisions are resolved above.

---

## Technical Design

### `heat.py`

**New model field:**
```python
phase_before_pause: Optional[str] = None
```

**`__init__` — new parameter** (add to signature and pass to `super().__init__`):
```python
phase_before_pause: Optional[str] = None,
```

**`pause()` — extend to cover PREP phase:**
```python
def pause(self):
    if self.status not in ('PREP', 'FLIGHT'):
        raise ValueError("Cannot pause: heat is not in PREP or FLIGHT phase.")
    self.phase_before_pause = self.status          # remember which phase to restore
    self.remaining_seconds_at_pause = self.get_remaining_seconds()
    self.status = 'PAUSED'
```

**`resume()` — branch on `phase_before_pause`:**
```python
def resume(self):
    now = datetime.now()
    if self.phase_before_pause == 'FLIGHT':
        self.last_resume_at = now
        self.status = 'FLIGHT'
    elif self.phase_before_pause == 'PREP':
        # Rewind prep_started_at so get_remaining_seconds() returns the frozen value.
        # remaining = prep_time - (now - prep_started_at)
        # → prep_started_at = now - (prep_time - remaining_seconds_at_pause)
        elapsed_before_pause = self.prep_time - self.remaining_seconds_at_pause
        self.prep_started_at = now - timedelta(seconds=elapsed_before_pause)
        self.status = 'PREP'
    self.phase_before_pause = None
```

`timedelta` is imported from `datetime` — already present in the module.

---

### `database.py`

**`CREATE TABLE heat`** — add column to the baseline definition:
```sql
phase_before_pause TEXT
```

**`_adds` list** — add idempotent migration alongside the existing `user.created_at` entry:
```python
"ALTER TABLE heat ADD COLUMN phase_before_pause TEXT",
```

**`create_or_update_heat()` INSERT query** — add to column list and params tuple:
```sql
INSERT INTO heat (
    group_sequence, status, channels_json,
    prep_time, flight_time,
    created_at, prep_started_at, flight_started_at, finished_at,
    remaining_seconds_at_pause, last_resume_at,
    phase_before_pause,            -- NEW
    session_id, heat_number
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```
Params tuple: append `heat.phase_before_pause` before `heat.session_id`.

**`create_or_update_heat()` UPDATE query** — add to SET clause:
```sql
UPDATE heat SET
    group_sequence=?, status=?, channels_json=?,
    prep_time=?, flight_time=?,
    created_at=?, prep_started_at=?, flight_started_at=?,
    finished_at=?,
    remaining_seconds_at_pause=?, last_resume_at=?,
    phase_before_pause=?           -- NEW
WHERE session_id=? AND heat_number=?
```

**`get_heat_by_number()` SELECT** — add `phase_before_pause` to the column list:
```sql
SELECT session_id, heat_number, group_sequence, status,
       prep_time, flight_time, channels_json, created_at,
       prep_started_at, flight_started_at, finished_at,
       remaining_seconds_at_pause, last_resume_at,
       phase_before_pause           -- NEW
FROM heat
WHERE session_id = ? AND heat_number = ?
```

**`Heat(...)` construction in `get_heat_by_number()`** — pass new field:
```python
Heat(
    ...
    phase_before_pause=row["phase_before_pause"],   # NEW
)
```

---

### `session.py`

**`pause()` — replace the `raise NotImplementedError` stub:**
```python
def pause(self):
    if self.current_phase != 'FLIGHT':
        raise ValueError("Cannot pause: session is not running.")
    if not self.current_heat or self.current_heat.status not in ('PREP', 'FLIGHT'):
        raise ValueError("No pausable heat active.")
    self.phase_before_pause = self.current_phase   # always 'FLIGHT' at session level
    self.current_heat.pause()
    self.current_phase = 'PAUSED'
```

**`resume()` — new method (add after `pause()`):**
```python
def resume(self):
    """Resume a paused session and its current heat."""
    if self.current_phase != 'PAUSED':
        raise ValueError("Cannot resume: session is not paused.")
    self.current_heat.resume()
    self.current_phase = self.phase_before_pause or 'FLIGHT'
```

---

### `session_api.py`

**`pause_timer()`** — replace the stub response:
```python
@router.post("/pause")
async def pause_timer(_: str = Depends(require_admin)):
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    try:
        session.pause()
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    return {"status": "ok"}
```

**`resume_timer()`** — replace the stub response:
```python
@router.post("/resume")
async def resume_timer(_: str = Depends(require_admin)):
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    try:
        session.resume()
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    return {"status": "ok"}
```

---

### `session.html`

**`pauseSession()`** — flip buttons immediately after confirmed API response:
```javascript
async function pauseSession() {
    try {
        const res = await fetch('/api/session/pause', { method: 'POST' });
        const data = await res.json();
        if (data.status === "error") { alert("Błąd: " + data.message); return; }
    } catch (err) { alert("Błąd sieci: " + err.message); return; }
    stopTimer();
    document.getElementById('btnPause').style.display  = 'none';
    document.getElementById('btnResume').style.display = '';
}
```

**`resumeSession()`** — flip buttons immediately after confirmed API response:
```javascript
async function resumeSession() {
    try {
        const res = await fetch('/api/session/resume', { method: 'POST' });
        const data = await res.json();
        if (data.status === "error") { alert("Błąd: " + data.message); return; }
    } catch (err) { alert("Błąd sieci: " + err.message); return; }
    startTimer();
    document.getElementById('btnPause').style.display  = '';
    document.getElementById('btnResume').style.display = 'none';
}
```

**`rendertHeats()`** — synchronise button state on every poll (handles page reload
and server restart recovery — within one poll interval the buttons will be correct):
```javascript
// After heat status is known:
const isPaused = heat.status === 'PAUSED';
document.getElementById('btnPause').style.display  = isPaused ? 'none' : '';
document.getElementById('btnResume').style.display = isPaused ? ''     : 'none';
```

---

### `tests/test_pause_resume.py` (new file)

**`heat.py` unit tests:**
| Test | Assertion |
|---|---|
| `pause()` during FLIGHT → `status == 'PAUSED'`, `phase_before_pause == 'FLIGHT'`, `remaining_seconds_at_pause` set | |
| `pause()` during PREP → `status == 'PAUSED'`, `phase_before_pause == 'PREP'`, `remaining_seconds_at_pause` set | |
| `pause()` when not PREP/FLIGHT → `ValueError` raised | |
| `resume()` from FLIGHT-pause → `status == 'FLIGHT'`, `last_resume_at` set, `phase_before_pause` cleared | |
| `resume()` from PREP-pause → `status == 'PREP'`, `prep_started_at` recalculated, `phase_before_pause` cleared | |
| `get_remaining_seconds()` frozen while PAUSED | |
| `get_remaining_seconds()` counts down after FLIGHT resume | |
| `get_remaining_seconds()` counts down after PREP resume | |

**`session.py` unit tests:**
| Test | Assertion |
|---|---|
| `session.pause()` during FLIGHT heat → `session.current_phase == 'PAUSED'` | |
| `session.pause()` during PREP heat → `session.current_phase == 'PAUSED'` | |
| `session.pause()` when not active → `ValueError` | |
| `session.resume()` → `session.current_phase == 'FLIGHT'` | |
| `session.resume()` when not PAUSED → `ValueError` | |

**API functional tests (with `WRMS_SKIP_AUTH=1`):**
| Test | Assertion |
|---|---|
| `POST /api/session/pause` on started session → 200 ok | |
| `POST /api/session/resume` after pause → 200 ok | |
| `POST /api/session/pause` with no session → error | |
| `POST /api/session/pause` without auth → 401 | |
| `POST /api/session/resume` without auth → 401 | |
| `GET /api/heat` during pause → `live_seconds_left` frozen (same value on two consecutive calls) | |

**Persistence tests:**
| Test | Assertion |
|---|---|
| pause → `save_session_data()` → fresh `RaceDatabase.get_session_by_id()` → `current_phase == 'PAUSED'` | |
| pause → `create_or_update_heat()` → fresh `get_heat_by_number()` → `status == 'PAUSED'`, `phase_before_pause` correct, `remaining_seconds_at_pause` correct | |

---

*Created: 2026-03-28*
