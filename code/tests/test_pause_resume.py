"""
Functional and unit tests for session pause/resume.

Covers:
  - heat.py: pause/resume state transitions, timer arithmetic, guard errors
  - session.py: session-level pause/resume, phase transitions, guards
  - API: POST /api/session/pause and /resume happy paths, error cases, 401
  - Persistence: paused state survives save + reload from DB
"""
import time
import pytest

from main import app  # noqa: E402  (conftest sets WRMS_DB_PATH before this import)
from fastapi.testclient import TestClient
from heat import Heat
from session import Session
from database import get_db

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_heat(status="FLIGHT", prep_time=30, flight_time=60):
    """Create a minimal Heat in the given status with timers already started."""
    h = Heat(
        session_id="test-session",
        heat_number=1,
        prep_time=prep_time,
        flight_time=flight_time,
        group_sequence=1,
        channels={},
    )
    if status in ("FLIGHT", "PAUSED"):
        h.start_prep()
        h.start_flight()
    elif status == "PREP":
        h.start_prep()
    if status == "PAUSED":
        h.pause()
    return h


# ---------------------------------------------------------------------------
# heat.py — unit tests
# ---------------------------------------------------------------------------

class TestHeatPause:
    def test_pause_flight_sets_status(self):
        h = _make_heat("FLIGHT")
        h.pause()
        assert h.status == "PAUSED"

    def test_pause_flight_saves_phase(self):
        h = _make_heat("FLIGHT")
        h.pause()
        assert h.phase_before_pause == "FLIGHT"

    def test_pause_flight_saves_remaining(self):
        h = _make_heat("FLIGHT")
        time.sleep(0.05)
        h.pause()
        assert h.remaining_seconds_at_pause is not None
        assert h.remaining_seconds_at_pause < h.flight_time

    def test_pause_prep_sets_status(self):
        h = _make_heat("PREP")
        h.pause()
        assert h.status == "PAUSED"

    def test_pause_prep_saves_phase(self):
        h = _make_heat("PREP")
        h.pause()
        assert h.phase_before_pause == "PREP"

    def test_pause_prep_saves_remaining(self):
        h = _make_heat("PREP")
        time.sleep(0.05)
        h.pause()
        assert h.remaining_seconds_at_pause is not None
        assert h.remaining_seconds_at_pause < h.prep_time

    def test_pause_planned_raises(self):
        h = Heat(session_id="s", heat_number=1, prep_time=30,
                 flight_time=60, group_sequence=1, channels={})
        with pytest.raises(ValueError, match="PREP or FLIGHT"):
            h.pause()

    def test_double_pause_raises(self):
        h = _make_heat("FLIGHT")
        h.pause()
        with pytest.raises(ValueError):
            h.pause()

    def test_remaining_frozen_while_paused(self):
        h = _make_heat("FLIGHT")
        time.sleep(0.05)
        h.pause()
        r1 = h.get_remaining_seconds()
        time.sleep(0.1)
        r2 = h.get_remaining_seconds()
        assert r1 == r2


class TestHeatResume:
    def test_resume_flight_restores_status(self):
        h = _make_heat("FLIGHT")
        h.pause()
        h.resume()
        assert h.status == "FLIGHT"

    def test_resume_flight_clears_phase_before_pause(self):
        h = _make_heat("FLIGHT")
        h.pause()
        h.resume()
        assert h.phase_before_pause is None

    def test_resume_flight_sets_last_resume_at(self):
        h = _make_heat("FLIGHT")
        h.pause()
        h.resume()
        assert h.last_resume_at is not None

    def test_resume_flight_timer_counts_down(self):
        h = _make_heat("FLIGHT")
        time.sleep(0.05)
        h.pause()
        frozen = h.remaining_seconds_at_pause
        time.sleep(0.1)
        h.resume()
        time.sleep(0.1)
        after = h.get_remaining_seconds()
        assert after < frozen

    def test_resume_prep_restores_status(self):
        h = _make_heat("PREP")
        h.pause()
        h.resume()
        assert h.status == "PREP"

    def test_resume_prep_clears_phase_before_pause(self):
        h = _make_heat("PREP")
        h.pause()
        h.resume()
        assert h.phase_before_pause is None

    def test_resume_prep_timer_continues_from_frozen_value(self):
        h = _make_heat("PREP")
        time.sleep(0.05)
        h.pause()
        frozen = h.remaining_seconds_at_pause
        time.sleep(0.1)
        h.resume()
        # Immediately after resume the timer should be very close to frozen value
        immediately_after = h.get_remaining_seconds()
        assert abs(immediately_after - frozen) < 0.1

    def test_resume_prep_timer_counts_down(self):
        h = _make_heat("PREP")
        time.sleep(0.05)
        h.pause()
        frozen = h.remaining_seconds_at_pause
        time.sleep(0.05)
        h.resume()
        time.sleep(0.1)
        after = h.get_remaining_seconds()
        assert after < frozen


# ---------------------------------------------------------------------------
# session.py — unit tests
# ---------------------------------------------------------------------------

@pytest.fixture
def running_session(new_session, make_pilot):
    """Session with 2 pilots, rebalanced, started."""
    p1, _ = make_pilot()
    p2, _ = make_pilot()
    client.post("/api/session/add_pilot", json={"pilot_id": p1, "vtx": "Analog"})
    client.post("/api/session/add_pilot", json={"pilot_id": p2, "vtx": "DJI"})
    client.post("/api/groups/rebalance", json={})
    client.post("/api/session/start")
    return new_session


class TestSessionPauseResume:
    def test_pause_sets_phase_paused(self, running_session):
        r = client.post("/api/session/pause")
        assert r.json()["status"] == "ok"
        r2 = client.get("/api/session")
        assert r2.json()["session"]["current_phase"] == "PAUSED"

    def test_resume_restores_phase(self, running_session):
        client.post("/api/session/pause")
        r = client.post("/api/session/resume")
        assert r.json()["status"] == "ok"
        r2 = client.get("/api/session")
        assert r2.json()["session"]["current_phase"] == "FLIGHT"

    def test_pause_when_not_running_returns_error(self):
        r = client.post("/api/session/pause")
        assert r.json()["status"] == "error"

    def test_resume_when_not_paused_returns_error(self, running_session):
        r = client.post("/api/session/resume")
        assert r.json()["status"] == "error"

    def test_double_pause_returns_error(self, running_session):
        client.post("/api/session/pause")
        r = client.post("/api/session/pause")
        assert r.json()["status"] == "error"

    def test_heat_status_paused_after_session_pause(self, running_session):
        client.post("/api/session/pause")
        r = client.get("/api/heat")
        assert r.json()["heat"]["status"] == "PAUSED"

    def test_heat_status_restored_after_resume(self, running_session):
        client.post("/api/session/pause")
        client.post("/api/session/resume")
        r = client.get("/api/heat")
        assert r.json()["heat"]["status"] in ("PREP", "FLIGHT")

    def test_live_seconds_left_frozen_while_paused(self, running_session):
        client.post("/api/session/pause")
        r1 = client.get("/api/heat").json()["heat"]["live_seconds_left"]
        time.sleep(0.3)
        r2 = client.get("/api/heat").json()["heat"]["live_seconds_left"]
        assert abs(r1 - r2) < 0.05


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------

def test_pause_requires_auth(monkeypatch):
    monkeypatch.delenv("WRMS_SKIP_AUTH", raising=False)
    with TestClient(app) as c:
        r = c.post("/api/session/pause")
        assert r.status_code == 401


def test_resume_requires_auth(monkeypatch):
    monkeypatch.delenv("WRMS_SKIP_AUTH", raising=False)
    with TestClient(app) as c:
        r = c.post("/api/session/resume")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPausePersistence:
    def test_pause_state_survives_db_save_and_reload(self, running_session):
        """Pause → save_session_data + create_or_update_heat → reload from DB → still PAUSED."""
        client.post("/api/session/pause")

        from session import get_session
        session = get_session()
        db = get_db()
        db.save_session_data(session)
        db.create_or_update_heat(session.current_heat, session.active_pilots)

        reloaded = db.get_session_by_id(session.session_id)
        assert reloaded.current_phase == "PAUSED"
        assert reloaded.current_heat.status == "PAUSED"
        assert reloaded.current_heat.remaining_seconds_at_pause is not None
        assert reloaded.current_heat.phase_before_pause in ("PREP", "FLIGHT")

    def test_resume_state_survives_db_save_and_reload(self, running_session):
        """Pause → resume → save → reload from DB → phase is FLIGHT, heat is not PAUSED."""
        client.post("/api/session/pause")
        client.post("/api/session/resume")

        from session import get_session
        session = get_session()
        db = get_db()
        db.save_session_data(session)
        db.create_or_update_heat(session.current_heat, session.active_pilots)

        reloaded = db.get_session_by_id(session.session_id)
        assert reloaded.current_phase == "FLIGHT"
        assert reloaded.current_heat.status != "PAUSED"
        assert reloaded.current_heat.phase_before_pause is None


# ---------------------------------------------------------------------------
# Pause duration accounting
# ---------------------------------------------------------------------------

PAUSE_SECONDS = 3
TOLERANCE_SECONDS = 2


class TestPauseDurationAccounting:
    def test_pause_duration_shifts_end_time(self, running_session):
        """
        The heat end time must shift forward by approximately the pause duration.

        Steps:
          1. Fetch remaining seconds → calculate expected end timestamp T1.
          2. Pause, wait PAUSE_SECONDS, resume.
          3. Fetch remaining seconds again → calculate new expected end timestamp T2.
          4. Assert T2 - T1 ≈ PAUSE_SECONDS (within TOLERANCE_SECONDS).
        """
        # 1. Measure expected end time before pause
        r_before = client.get("/api/heat").json()
        assert r_before["status"] == "ok", "Heat not running before pause"
        secs_before = r_before["heat"]["live_seconds_left"]
        t1 = time.time() + secs_before

        # 2. Pause, wait, resume
        assert client.post("/api/session/pause").json()["status"] == "ok"
        time.sleep(PAUSE_SECONDS)
        assert client.post("/api/session/resume").json()["status"] == "ok"

        # 3. Measure expected end time after resume
        r_after = client.get("/api/heat").json()
        assert r_after["status"] == "ok", "Heat not running after resume"
        assert r_after["heat"]["status"] != "PAUSED", "Heat still paused after resume"
        secs_after = r_after["heat"]["live_seconds_left"]
        t2 = time.time() + secs_after

        # 4. End time must have shifted by ≈ PAUSE_SECONDS
        shift = t2 - t1
        assert PAUSE_SECONDS - TOLERANCE_SECONDS <= shift <= PAUSE_SECONDS + TOLERANCE_SECONDS, (
            f"End time shifted by {shift:.2f}s, expected ~{PAUSE_SECONDS}s "
            f"(tolerance ±{TOLERANCE_SECONDS}s)"
        )
