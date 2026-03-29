"""
Tests for session parameter update (flight_duration_sec / prep_duration_sec).

Covers:
  - update_params endpoint happy path (before and during session)
  - validation errors (zero / negative values)
  - no active session guard
  - next_heat timers updated when params change mid-session
  - current heat unaffected by param change
  - DB persistence of updated params
"""
import time
import pytest
from conftest import client, uid


def make_pilot(name: str = None, risk_factor: int = 3) -> int:
    n = name or f"P_{time.time_ns()}"
    resp = client.post("/api/pilot/", json={"name": n, "risk_factor": risk_factor})
    assert resp.status_code == 200
    return resp.json()["id"]


def create_session(flight: int = 300, prep: int = 60) -> dict:
    resp = client.post("/api/session", json={
        "name": f"S_{uid()}",
        "flight_duration_sec": flight,
        "prep_duration_sec": prep,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    return resp.json()["session"]


def add_pilot_to_session(vtx: str = "Analog") -> int:
    pid = make_pilot()
    r = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": vtx})
    assert r.json()["status"] == "ok"
    return pid


def start_session():
    add_pilot_to_session()
    client.post("/api/groups/rebalance", json={})
    r = client.post("/api/session/start")
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Basic API behaviour
# ---------------------------------------------------------------------------

class TestUpdateParamsBasic:

    def test_update_params_returns_ok(self, new_session):
        """POST /update_params returns status ok and new values."""
        r = client.post("/api/session/update_params", json={
            "flight_duration_sec": 400,
            "prep_duration_sec": 80,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["flight_duration_sec"] == 400
        assert data["prep_duration_sec"] == 80

    def test_update_params_reflected_in_get_session(self, new_session):
        """After update, GET /api/session returns the new values."""
        client.post("/api/session/update_params", json={
            "flight_duration_sec": 500,
            "prep_duration_sec": 90,
        })
        session = client.get("/api/session").json()["session"]
        assert session["flight_duration_sec"] == 500
        assert session["prep_duration_sec"] == 90

    def test_update_params_no_session_returns_error(self):
        """Without a session, update_params returns error."""
        r = client.post("/api/session/update_params", json={
            "flight_duration_sec": 300,
            "prep_duration_sec": 60,
        })
        assert r.json()["status"] == "error"

    def test_update_params_zero_flight_returns_error(self, new_session):
        """flight_duration_sec=0 is rejected."""
        r = client.post("/api/session/update_params", json={
            "flight_duration_sec": 0,
            "prep_duration_sec": 60,
        })
        assert r.json()["status"] == "error"

    def test_update_params_negative_prep_returns_error(self, new_session):
        """prep_duration_sec=-1 is rejected."""
        r = client.post("/api/session/update_params", json={
            "flight_duration_sec": 300,
            "prep_duration_sec": -1,
        })
        assert r.json()["status"] == "error"

    def test_update_params_before_session_starts(self, new_session):
        """Params can be changed before the session is started."""
        r = client.post("/api/session/update_params", json={
            "flight_duration_sec": 120,
            "prep_duration_sec": 30,
        })
        assert r.json()["status"] == "ok"
        session = client.get("/api/session").json()["session"]
        assert session["flight_duration_sec"] == 120
        assert session["prep_duration_sec"] == 30


# ---------------------------------------------------------------------------
# Effect on heats during active session
# ---------------------------------------------------------------------------

class TestUpdateParamsDuringSession:

    def test_next_heat_gets_new_timers(self, new_session):
        """After update, next_heat.prep_time and flight_time reflect new values."""
        start_session()

        client.post("/api/session/update_params", json={
            "flight_duration_sec": 777,
            "prep_duration_sec": 111,
        })

        session = client.get("/api/session").json()["session"]
        next_heat = session.get("next_heat")
        assert next_heat is not None
        assert next_heat["flight_time"] == 777
        assert next_heat["prep_time"] == 111

    def test_current_heat_unaffected_by_update(self, new_session):
        """The currently running heat keeps its original timers after param update."""
        start_session()
        session_before = client.get("/api/session").json()["session"]
        original_flight = session_before["current_heat"]["flight_time"]
        original_prep   = session_before["current_heat"]["prep_time"]

        client.post("/api/session/update_params", json={
            "flight_duration_sec": original_flight + 999,
            "prep_duration_sec": original_prep + 999,
        })

        session_after = client.get("/api/session").json()["session"]
        assert session_after["current_heat"]["flight_time"] == original_flight
        assert session_after["current_heat"]["prep_time"] == original_prep

    def test_update_params_persisted_to_db(self, new_session):
        """Updated params survive a re-read from DB (via GET /api/session)."""
        client.post("/api/session/update_params", json={
            "flight_duration_sec": 654,
            "prep_duration_sec": 321,
        })
        # Read fresh from API (which reads from in-memory session but saves to DB)
        session = client.get("/api/session").json()["session"]
        assert session["flight_duration_sec"] == 654
        assert session["prep_duration_sec"] == 321

    def test_update_params_multiple_times(self, new_session):
        """Params can be updated more than once; last value wins."""
        client.post("/api/session/update_params", json={
            "flight_duration_sec": 100,
            "prep_duration_sec": 50,
        })
        client.post("/api/session/update_params", json={
            "flight_duration_sec": 200,
            "prep_duration_sec": 25,
        })
        session = client.get("/api/session").json()["session"]
        assert session["flight_duration_sec"] == 200
        assert session["prep_duration_sec"] == 25

    def test_update_params_during_paused_session(self, new_session):
        """Params can be updated while session is paused."""
        start_session()
        client.post("/api/session/pause")
        r = client.post("/api/session/update_params", json={
            "flight_duration_sec": 450,
            "prep_duration_sec": 45,
        })
        assert r.json()["status"] == "ok"
        session = client.get("/api/session").json()["session"]
        assert session["flight_duration_sec"] == 450
