"""
Testy cyklu życia sesji treningowej.
Pokrycie: UC1 (inicjacja), UC4 (zakończenie), UC5 (dodanie pilota),
          UC6 (usunięcie pilota), Req 3.2 (kontrola sesji).
"""
import pytest
from conftest import client, uid


class TestSessionCreate:

    def test_create_session_returns_ok(self):
        resp = client.post("/api/session", json={
            "name": "Test", "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_create_session_persists_parameters(self):
        name = f"Sesja_{uid()}"
        client.post("/api/session", json={
            "name": name, "flight_duration_sec": 300, "prep_duration_sec": 90
        })
        session = client.get("/api/session").json()["session"]
        assert session["name"] == name
        assert session["flight_duration_sec"] == 300
        assert session["prep_duration_sec"] == 90

    def test_create_session_initial_phase_is_idle(self):
        client.post("/api/session", json={
            "name": "Ph", "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        session = client.get("/api/session").json()["session"]
        assert session["current_phase"] == "IDLE"

    def test_create_session_empty_name_returns_error(self):
        resp = client.post("/api/session", json={
            "name": "   ", "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        assert resp.status_code == 400

    def test_create_session_zero_flight_duration_returns_error(self):
        resp = client.post("/api/session", json={
            "name": "Bad", "flight_duration_sec": 0, "prep_duration_sec": 30
        })
        assert resp.status_code == 400

    def test_create_session_negative_prep_duration_returns_error(self):
        resp = client.post("/api/session", json={
            "name": "Bad", "flight_duration_sec": 60, "prep_duration_sec": -1
        })
        assert resp.status_code == 400

    def test_get_session_without_creating_returns_error(self):
        resp = client.get("/api/session")
        assert resp.status_code == 400


class TestSessionStart:

    def test_start_without_pilots_returns_error(self, new_session):
        resp = client.post("/api/session/start")
        assert resp.json()["status"] == "error"
        assert "pilot" in resp.json()["message"].lower()

    def test_start_without_groups_returns_error(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        resp = client.post("/api/session/start")
        assert resp.json()["status"] == "error"
        assert "group" in resp.json()["message"].lower()

    def test_start_session_success(self, session_with_pilots):
        resp = client.post("/api/session/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_start_sets_session_active(self, session_with_pilots):
        client.post("/api/session/start")
        session = client.get("/api/session").json()["session"]
        assert session["is_active"] is True

    def test_start_sets_phase_to_flight(self, session_with_pilots):
        client.post("/api/session/start")
        session = client.get("/api/session").json()["session"]
        assert session["current_phase"] == "FLIGHT"

    def test_start_twice_returns_error(self, session_with_pilots):
        client.post("/api/session/start")
        resp = client.post("/api/session/start")
        assert resp.json()["status"] == "error"

    def test_start_creates_current_heat(self, started_session):
        heat = client.get("/api/heat").json()["heat"]
        assert heat is not None
        assert heat["heat_number"] == 1

    def test_start_creates_next_heat(self, started_session):
        next_heat = client.get("/api/heat").json()["next_heat"]
        assert next_heat is not None
        assert next_heat["heat_number"] == 2


class TestSessionStop:

    def test_stop_active_session(self, started_session):
        resp = client.post("/api/session/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_stop_clears_global_session(self, started_session):
        client.post("/api/session/stop")
        resp = client.get("/api/session")
        assert resp.status_code == 400

    def test_stop_without_session_returns_error(self):
        resp = client.post("/api/session/stop")
        assert resp.json()["status"] == "error"


class TestSessionPilotManagement:

    def test_add_pilot_to_session(self, new_session, make_pilot):
        pid, _ = make_pilot()
        resp = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_add_pilot_appears_in_active_pilots(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        session = client.get("/api/session").json()["session"]
        assert str(pid) in session["active_pilots"]

    def test_add_pilot_vtx_persisted(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "DJI"})
        session = client.get("/api/session").json()["session"]
        assert session["active_pilots"][str(pid)]["vtx"] == "DJI"

    def test_add_duplicate_pilot_returns_error(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        resp = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        assert resp.json()["status"] == "error"

    def test_remove_pilot_from_session(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        resp = client.post("/api/session/remove_pilot", json={"pilot_id": pid})
        assert resp.status_code == 200
        session = client.get("/api/session").json()["session"]
        assert str(pid) not in session["active_pilots"]

    def test_remove_pilot_removes_from_group_channel(self, new_session, make_pilot):
        """UC6: pilot usunięty z sesji musi zniknąć ze swojego kanału w grupie."""
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/new")
        client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "to_group": 1, "to_channel": "R1"
        })

        client.post("/api/session/remove_pilot", json={"pilot_id": pid})

        session = client.get("/api/session").json()["session"]
        channels = session["groups"][0]["channels"]
        assert "R1" not in channels or channels.get("R1") is None

    def test_add_pilot_without_session_returns_error(self, make_pilot):
        pid, _ = make_pilot()
        resp = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        assert resp.status_code == 400
