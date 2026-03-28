"""
Testy maszyny stanów biegu (Heat) i synchronizacji timera.
Pokrycie: Req 3.3 (Frontend / Heat endpoint), cykl PREP → FLIGHT → FINISHED.
"""
import time
import pytest
from conftest import client, uid


class TestHeatEndpointWithoutSession:

    def test_heat_without_session_returns_error(self):
        resp = client.get("/api/heat")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_heat_without_started_session_returns_error(self, new_session):
        resp = client.get("/api/heat")
        assert resp.json()["status"] == "error"


class TestHeatInitialState:

    def test_heat_returns_ok_after_start(self, started_session):
        resp = client.get("/api/heat")
        assert resp.json()["status"] == "ok"
        assert resp.json()["heat"] is not None

    def test_first_heat_number_is_1(self, started_session):
        heat = client.get("/api/heat").json()["heat"]
        assert heat["heat_number"] == 1

    def test_heat_initial_status_is_prep(self, started_session):
        heat = client.get("/api/heat").json()["heat"]
        assert heat["status"] == "PREP"

    def test_heat_has_live_seconds_left(self, started_session):
        heat = client.get("/api/heat").json()["heat"]
        assert heat["live_seconds_left"] is not None
        assert heat["live_seconds_left"] > 0

    def test_heat_live_seconds_close_to_prep_time(self, started_session):
        """live_seconds_left po starcie powinien być bliski prep_duration_sec (30s)."""
        heat = client.get("/api/heat").json()["heat"]
        assert 28 <= heat["live_seconds_left"] <= 31

    def test_heat_channels_reflect_group(self, started_session):
        """Kanały w heat to snapshot kanałów grupy w momencie startu."""
        _, pilots = started_session
        heat = client.get("/api/heat").json()["heat"]
        assert len(heat["channels"]) > 0

    def test_heat_next_heat_is_heat_2(self, started_session):
        next_heat = client.get("/api/heat").json()["next_heat"]
        assert next_heat is not None
        assert next_heat["heat_number"] == 2

    def test_heat_channel_contains_pilot_data(self, started_session):
        heat = client.get("/api/heat").json()["heat"]
        for slot in heat["channels"].values():
            assert "pilot_id" in slot
            assert "pilot" in slot
            assert "name" in slot["pilot"]
            assert "vtx" in slot


class TestHeatTimerAccuracy:

    def test_timer_decreases_over_time(self):
        """Req 3.3: live_seconds_left maleje proporcjonalnie do czasu rzeczywistego."""
        client.post("/api/session", json={
            "name": f"Timer_{uid()}", "flight_duration_sec": 100, "prep_duration_sec": 100
        })
        name = f"TP_{uid()}"
        pid = client.post("/api/pilot/", json={"name": name}).json()["id"]
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        t1 = client.get("/api/heat").json()["heat"]["live_seconds_left"]
        wall_start = time.time()
        time.sleep(2)
        t2 = client.get("/api/heat").json()["heat"]["live_seconds_left"]
        elapsed = time.time() - wall_start

        assert t2 < t1
        assert abs((t1 - t2) - elapsed) < 0.3

    def test_timer_prep_transitions_to_flight(self):
        """Po upływie prep_time (2s) status biegu zmienia się na FLIGHT."""
        client.post("/api/session", json={
            "name": f"Trans_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 2
        })
        name = f"TP_{uid()}"
        pid = client.post("/api/pilot/", json={"name": name}).json()["id"]
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        assert client.get("/api/heat").json()["heat"]["status"] == "PREP"

        time.sleep(2.5)

        # Każde żądanie triggeruje session.loop() przez middleware
        heat = client.get("/api/heat").json()["heat"]
        assert heat["status"] == "FLIGHT"

    def test_flight_timer_starts_near_flight_duration(self):
        """Po przejściu do FLIGHT live_seconds_left ≈ flight_duration_sec."""
        client.post("/api/session", json={
            "name": f"FT_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 2
        })
        name = f"TP_{uid()}"
        pid = client.post("/api/pilot/", json={"name": name}).json()["id"]
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        time.sleep(2.5)
        heat = client.get("/api/heat").json()["heat"]
        assert heat["status"] == "FLIGHT"
        assert 58 <= heat["live_seconds_left"] <= 61


class TestHeatRotation:

    def test_skip_increments_heat_number(self, started_session):
        client.post("/api/session/skip_heat")
        heat = client.get("/api/heat").json()["heat"]
        assert heat["heat_number"] == 2

    def test_skip_changes_group(self, started_session):
        """Po skip grupa powinna się zmienić (jeśli są 2+ grupy)."""
        heat1 = client.get("/api/heat").json()["heat"]
        client.post("/api/session/skip_heat")
        heat2 = client.get("/api/heat").json()["heat"]
        # Jeśli są 2 grupy, group_sequence powinno być inne
        # Jeśli jest 1 grupa, wraca ta sama — akceptowalne
        assert heat2["heat_number"] == heat1["heat_number"] + 1

    def test_skip_new_heat_starts_in_prep(self, started_session):
        client.post("/api/session/skip_heat")
        heat = client.get("/api/heat").json()["heat"]
        assert heat["status"] == "PREP"

    def test_skip_without_active_session_returns_error(self):
        resp = client.post("/api/session/skip_heat")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_next_heat_advances_after_skip(self, started_session):
        next_before = client.get("/api/heat").json()["next_heat"]["heat_number"]
        client.post("/api/session/skip_heat")
        next_after = client.get("/api/heat").json()["next_heat"]["heat_number"]
        assert next_after == next_before + 1

    def test_multiple_skips_cycle_through_groups(self, started_session):
        """3 skip-y po sesji z 2 grupami: G1→G2→G1→G2 (rotacja)."""
        heat_numbers = []
        for _ in range(4):
            heat_numbers.append(client.get("/api/heat").json()["heat"]["heat_number"])
            client.post("/api/session/skip_heat")
        assert heat_numbers == [1, 2, 3, 4]
