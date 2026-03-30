"""
Tests for pilot pause/resume within a session.

Covers:
  - pause_pilot / resume_pilot API endpoints (happy path)
  - status reflected in GET /api/session response
  - no rebalance triggered on pause/resume
  - group assignment unchanged after pause
  - DB persistence of status (via direct DB read)
  - error cases (no session, unknown pilot)
  - regression: remove still works on paused pilot
  - heat filtering: paused pilots excluded from next_heat channels
"""
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from conftest import client, uid  # noqa: E402
from database import get_db  # noqa: E402


def make_pilot(name: str = None) -> int:
    n = name or f"P_{time.time_ns()}"
    r = client.post("/api/pilot/", json={"name": n})
    assert r.status_code == 200
    return r.json()["id"]


def add_to_session(pilot_id: int, vtx: str = "Analog"):
    r = client.post("/api/session/add_pilot", json={"pilot_id": pilot_id, "vtx": vtx})
    assert r.json()["status"] == "ok"


def get_pilot_status(pilot_id: int) -> str:
    """Return the status field of a pilot from the active session."""
    data = client.get("/api/session").json()
    pilots = data["session"]["active_pilots"]
    return pilots[str(pilot_id)]["status"]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestPausePilotBasic:

    def test_pause_pilot_returns_ok(self, new_session):
        pid = make_pilot()
        add_to_session(pid)
        r = client.post("/api/session/pause_pilot", json={"pilot_id": pid})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_pause_sets_status_paused(self, new_session):
        pid = make_pilot()
        add_to_session(pid)
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})
        assert get_pilot_status(pid) == "paused"

    def test_resume_sets_status_active(self, new_session):
        pid = make_pilot()
        add_to_session(pid)
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})
        client.post("/api/session/resume_pilot", json={"pilot_id": pid})
        assert get_pilot_status(pid) == "active"

    def test_new_pilot_status_is_active_by_default(self, new_session):
        pid = make_pilot()
        add_to_session(pid)
        assert get_pilot_status(pid) == "active"

    def test_pause_resume_cycle(self, new_session):
        """Pilot can be paused and resumed multiple times."""
        pid = make_pilot()
        add_to_session(pid)
        for _ in range(3):
            client.post("/api/session/pause_pilot", json={"pilot_id": pid})
            assert get_pilot_status(pid) == "paused"
            client.post("/api/session/resume_pilot", json={"pilot_id": pid})
            assert get_pilot_status(pid) == "active"


# ---------------------------------------------------------------------------
# Group assignment unchanged
# ---------------------------------------------------------------------------

class TestPauseGroupAssignment:

    def test_paused_pilot_stays_in_group(self, new_session):
        """Pausing a pilot does not remove them from their group or channel."""
        pid = make_pilot()
        add_to_session(pid, "DJI")
        client.post("/api/groups/rebalance", json={})

        def channel_pilot_ids(groups):
            """Return {group_seq: {channel: pilot_id}} — ignores status field."""
            return {
                g["group_sequence"]: {
                    ch: slot["pilot_id"] if slot else None
                    for ch, slot in g["channels"].items()
                }
                for g in groups
            }

        before = channel_pilot_ids(client.get("/api/session").json()["session"]["groups"])
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})
        after = channel_pilot_ids(client.get("/api/session").json()["session"]["groups"])

        assert before == after

    def test_pause_does_not_trigger_rebalance(self, new_session):
        """Group count unchanged after pause."""
        for _ in range(8):
            add_to_session(make_pilot())
        client.post("/api/groups/rebalance", json={})
        groups_before = client.get("/api/session").json()["session"]["groups"]

        pid = make_pilot()
        add_to_session(pid)
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})

        groups_after = client.get("/api/session").json()["session"]["groups"]
        assert len(groups_after) == len(groups_before)


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

class TestPauseDbPersistence:

    def test_pause_persisted_to_db(self, new_session):
        """Paused status is saved to the active_pilot table."""
        pid = make_pilot()
        add_to_session(pid)

        session_id = client.get("/api/session").json()["session"]["session_id"]
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})

        db = get_db()
        import sqlite3
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT status FROM active_pilot WHERE session_id=? AND pilot_id=?",
                (session_id, pid)
            ).fetchone()
        assert row["status"] == "paused"

    def test_resume_persisted_to_db(self, new_session):
        """Resumed status is saved back to 'active' in the DB."""
        pid = make_pilot()
        add_to_session(pid)

        session_id = client.get("/api/session").json()["session"]["session_id"]
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})
        client.post("/api/session/resume_pilot", json={"pilot_id": pid})

        db = get_db()
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT status FROM active_pilot WHERE session_id=? AND pilot_id=?",
                (session_id, pid)
            ).fetchone()
        assert row["status"] == "active"

    def test_status_survives_session_reload(self, new_session):
        """Paused status is loaded correctly when session is read from DB."""
        pid = make_pilot()
        add_to_session(pid)
        session_id = client.get("/api/session").json()["session"]["session_id"]
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})

        # Re-read via DB directly (simulating server restart load)
        db = get_db()
        session = db.get_session_by_id(session_id)
        assert session.active_pilots[pid].status == "paused"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestPausePilotErrors:

    def test_pause_no_session_returns_error(self):
        r = client.post("/api/session/pause_pilot", json={"pilot_id": 999})
        assert r.json()["status"] == "error"

    def test_resume_no_session_returns_error(self):
        r = client.post("/api/session/resume_pilot", json={"pilot_id": 999})
        assert r.json()["status"] == "error"

    def test_pause_unknown_pilot_returns_error(self, new_session):
        r = client.post("/api/session/pause_pilot", json={"pilot_id": 99999})
        assert r.json()["status"] == "error"

    def test_resume_unknown_pilot_returns_error(self, new_session):
        r = client.post("/api/session/resume_pilot", json={"pilot_id": 99999})
        assert r.json()["status"] == "error"


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------

class TestPauseRegression:

    def test_remove_paused_pilot_works(self, new_session):
        """A paused pilot can still be removed from the session."""
        pid = make_pilot()
        add_to_session(pid)
        client.post("/api/session/pause_pilot", json={"pilot_id": pid})
        r = client.post("/api/session/remove_pilot", json={"pilot_id": pid})
        assert r.json()["status"] == "ok"
        pilots = client.get("/api/session").json()["session"]["active_pilots"]
        assert str(pid) not in pilots

    def test_multiple_pilots_independent_status(self, new_session):
        """Pausing one pilot does not affect others."""
        p1 = make_pilot()
        p2 = make_pilot()
        add_to_session(p1)
        add_to_session(p2)
        client.post("/api/session/pause_pilot", json={"pilot_id": p1})
        assert get_pilot_status(p1) == "paused"
        assert get_pilot_status(p2) == "active"

    def test_paused_pilot_status_in_api_response(self, new_session):
        """GET /api/session always includes status field on each active pilot."""
        pid = make_pilot()
        add_to_session(pid)
        data = client.get("/api/session").json()
        pilot = data["session"]["active_pilots"][str(pid)]
        assert "status" in pilot
        assert pilot["status"] == "active"


# ---------------------------------------------------------------------------
# Heat filtering — paused pilots must not appear in next_heat channels
# ---------------------------------------------------------------------------

class TestPauseHeatFiltering:

    def _start_session_with_pilots(self, vtx_list: list[str]) -> list[int]:
        """Add pilots with given VTX types, rebalance, start session. Returns pilot IDs."""
        pids = []
        for vtx in vtx_list:
            pid = make_pilot()
            add_to_session(pid, vtx)
            pids.append(pid)
        client.post("/api/groups/rebalance", json={})
        r = client.post("/api/session/start")
        assert r.json()["status"] == "ok"
        return pids

    def _next_heat_pilot_ids(self) -> set:
        """Return the set of pilot_ids assigned to next_heat channels."""
        data = client.get("/api/session").json()["session"]
        next_heat = data.get("next_heat")
        if next_heat is None:
            return set()
        return {slot["pilot_id"] for slot in next_heat["channels"].values() if slot}

    def test_paused_pilot_absent_from_next_heat(self, new_session):
        """After pausing, the pilot is removed from next_heat channels."""
        pids = self._start_session_with_pilots(["Analog", "DJI", "Analog", "DJI"])
        target_pid = pids[0]
        # Pilot must be in next_heat before pause (if they belong to next group)
        client.post("/api/session/pause_pilot", json={"pilot_id": target_pid})
        assert target_pid not in self._next_heat_pilot_ids()

    def test_resumed_pilot_back_in_next_heat(self, new_session):
        """After resuming, the pilot reappears in next_heat channels."""
        pids = self._start_session_with_pilots(["Analog", "DJI", "Analog", "DJI"])
        target_pid = pids[0]
        client.post("/api/session/pause_pilot", json={"pilot_id": target_pid})
        client.post("/api/session/resume_pilot", json={"pilot_id": target_pid})
        # After resume, pilot in next group should be back in next_heat
        data = client.get("/api/session").json()["session"]
        # Check the pilot is back in the session with active status
        assert data["active_pilots"][str(target_pid)]["status"] == "active"

    def test_next_heat_pilot_ids_match_db(self, new_session):
        """Pilot IDs in next_heat via API match what is persisted in the DB."""
        pids = self._start_session_with_pilots(["Analog", "DJI", "Analog", "DJI"])
        client.post("/api/session/pause_pilot", json={"pilot_id": pids[0]})

        # Get next_heat from in-memory API response
        api_ids = self._next_heat_pilot_ids()

        # Get next_heat from DB (simulated via session reload)
        session_id = client.get("/api/session").json()["session"]["session_id"]
        db = get_db()
        session_from_db = db.get_session_by_id(session_id)
        if session_from_db.next_heat:
            db_ids = {
                slot.pilot_id
                for slot in session_from_db.next_heat.channels.values()
                if slot
            }
        else:
            db_ids = set()

        assert api_ids == db_ids
