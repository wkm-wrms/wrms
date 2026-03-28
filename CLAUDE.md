# CLAUDE.md — Context for AI-assisted development of WRMS

This file is the shared context document for AI collaborators working on this codebase.
Keep it up to date as decisions are made, bugs are found/fixed, and architecture evolves.

---

## Project: WKM Racing Management System (WRMS)

FPV drone race session management system used at live events. The MC (Mistrz Ceremonii / Race Director)
uses the admin panel to manage pilots, groups, and the training cycle. A public dashboard shows the
current heat status to spectators.

**Repo**: `wrms/` (this directory)
**Branch convention**: `draft` is the active development branch.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, Uvicorn |
| Database | SQLite with WAL mode (`data/race_system.db`) |
| Frontend | Plain HTML + vanilla JS (no build step), served as static files |
| Tests | pytest, FastAPI TestClient |

---

## Collaboration Rules

These rules were set by the project owner and must be followed in every session:

1. **Language**: All code comments and program messages (log output, error strings, docstrings) must be in **English**. User-facing UI text may remain in Polish.
2. **Tests**: Every new feature or bug fix must include regression tests AND functional tests. Tests go in `code/tests/`.
3. **TODO**: Use `docs/design/TODO.md` as the task tracker. Pull tasks from there, mark completed items, add new ideas as "Ideas / Future Improvements".
4. **No auto-commit**: Never commit or push without explicit instruction from the user. Suggest natural commit points ("good moment to commit") but wait for the user's go-ahead.
5. **Context**: Update this file (CLAUDE.md) when significant decisions, bugs, or architectural facts are discovered. Other developers (or future AI sessions) must be able to pick up from here.

---

## Architecture

### Request lifecycle

```
HTTP request → middleware (session.loop()) → router handler → response
```

`session.loop()` is called on **every** HTTP request (not a background thread). It advances
the heat state machine (PREP→FLIGHT, FLIGHT→rotate) and triggers DB writes when a transition occurs.
This means state transitions only happen when there is HTTP activity.

### Session/heat state machine

```
Session: IDLE → FLIGHT (started) → FINISHED (stopped)
Heat:     PLANNED → PREP → FLIGHT → FINISHED
```

- `session.start()` → heat #1 enters PREP, heat #2 is pre-created in PLANNED
- `session.loop()` → drives timers; on PREP expiry calls `heat.start_flight()`; on FLIGHT expiry calls `rotate_heats()`
- `rotate_heats()` → archives current heat (FINISHED), advances to next, pre-creates next+1
- `session.stop()` → sets `current_phase='FINISHED'`, saves to DB, clears in-memory session.
  Note: `is_active` flag is NOT reset to False by stop() — only `current_phase` changes.
- On server restart, `main.py` calls `db.get_active_session()` which queries `WHERE current_phase <> 'FINISHED'`.

### Group / Channel system

- Channels: `R1`, `R3` (analog/low), `R6`, `R7` (digital/high)
- Max 4 pilots per group
- Rebalance: `math.ceil(n/4)` groups, even distribution. Example: 5 pilots → 3+2 (NOT 4+1)
- Analog pilots → low channels (R1, R3 first), digital → high channels (R7, R6 first)

### Database isolation for tests

`database.py` reads `WRMS_DB_PATH` env var (falls back to `data/race_system.db`).
`tests/conftest.py` sets this env var to a `tempfile.mkstemp()` path **before** any app import,
so `db_instance = RaceDatabase()` at module load time picks up the test DB automatically.

---

## Key Files

```
code/
  main.py               — FastAPI app, middleware, session reload on startup
  database.py           — RaceDatabase class, all SQLite operations
  session.py            — Session model, state machine, group management
  heat.py               — Heat model, timer logic, PREP/FLIGHT/FINISHED transitions
  routers/
    session_api.py      — /api/session endpoints (create, start, stop, add/remove pilot)
    heat_api.py         — /api/heat endpoint (current heat + next heat)
    group_api.py        — /api/groups endpoints (new, delete, rebalance, move_pilot)
    pilot_api.py        — /api/pilot endpoints (create, search, get by id)
  tests/
    conftest.py         — Fixtures: reset_session, make_pilot, new_session, started_session, etc.
    test_pilot.py       — 13 tests: pilot CRUD + search + validation
    test_session_lifecycle.py — 22 tests: session create/start/stop, add/remove pilot
    test_groups_matchmaking.py — 25 tests: rebalance algorithm, manual group management (UC8)
    test_heat.py        — 17 tests: heat state machine, timer accuracy, rotation
    test_integration.py — 19 tests: end-to-end UC1–UC7 scenarios
    test_heat_finished.py — 18 tests: FLIGHT→FINISHED transition, DB persistence, stop() behavior
    test_persistence.py — 32 tests: all write operations verified via direct SQL + fresh DB instances
    test_functional.py  — original 13 tests (overlap with newer files, kept for history)
docs/
  design/
    requirements.md     — Functional requirements (Req 2.x, 3.x)
    use cases.md        — UC1–UC8 use case descriptions
    TODO.md             — Task tracker, completed items, improvement ideas
  API.md                — API endpoint reference
static/
  dashboard.html        — Public kiosk view (heat timer, pilot display)
  session.html          — Admin panel
  groups.html           — Group management UI
data/
  race_system.db        — Production SQLite database (gitignored)
```

---

## Fixed Bugs (history)

| Bug | Location | Fix |
|---|---|---|
| `sessions` table name | `database.get_all_sessions()` | Renamed to `session` |
| `hashlib.sha256(pw)` missing `.encode()` | `database.add_admin()`, `verify_admin()` | Added `.encode()` |
| `users` table name | `database.add_admin()`, `verify_admin()` | Renamed to `user` |
| Nested `with self._get_conn()` | `database.create_or_update_heat()` | Removed inner context manager, reused outer conn |
| Dead variable `ret` | `database.get_active_pilots()` | Removed |
| `datetime.now()` as mutable default | `heat.Heat.__init__` | Moved to constructor body |
| `remaining_seconds_at_pause()` naming clash with Pydantic field | `heat.py` | Renamed to `get_remaining_seconds_at_pause()` |
| `groups: list[Group] = None` | `session.Session` | Changed to `= []` |
| Dict mutation during iteration | `session.remove_pilot()` | Two-pass pattern with `ch_to_pop` |
| `Optional[str]` without `= None` (Pydantic v2) | `group_api.PilotMove` | Added `= None` defaults |
| Null check missing | `group_api.py` all endpoints | Added session null guards |
| `get_group_by_id` sets channel to `None` when pilot not in active_pilots | `database.py` | Skip instead of assign None |
| `current_group_id` AUTOINCREMENT mismatch | `database.get_session_by_id()` | Use `current_group_index` + `groups[idx]` |

---

## Test strategy

- **Unit-style**: individual endpoint behavior (pilot, session, heat, group APIs)
- **State machine**: timer transitions, rotation, skip
- **Integration / E2E**: full MC workflows (UC1–UC7)
- **Persistence**: every write operation verified via raw SQL + fresh `RaceDatabase` instance (simulating server restart)
- **Regression**: tests named after bugs/requirements, run on every change

**Principle**: each new feature must have both functional and regression tests before merge.

---

## Production Database

Location: `data/race_system.db` (gitignored).
Real pilots: id 1–12 (porlock, Piter, BART, Boczi, Bej_con, Malina, FiFi, Marcin, PanDron, Kuki, Baro, Youlson).
Real sessions: 4 sessions created on 2026-03-24 (name "aa").
Test contamination was cleaned on 2026-03-28 (493 pilots and 203 sessions removed).
