"""
Testy integracyjne — scenariusze end-to-end na podstawie use cases.
Testują kompletne przepływy MC (Mistrz Ceremonii), a nie pojedyncze endpointy.
"""
import time
import pytest
from conftest import client, uid


def make_pilot_in_db(name=None) -> tuple[int, str]:
    n = name or f"P_{uid()}"
    pid = client.post("/api/pilot/", json={"name": n}).json()["id"]
    return pid, n


# ---------------------------------------------------------------------------
# UC1: MC inicjuje Sesję Treningową
# ---------------------------------------------------------------------------

class TestUC1_SessionInit:

    def test_full_session_setup_flow(self):
        """
        Kompletny przepływ: Utwórz sesję → dodaj pilotów → rebalans → start.
        Weryfikacja: sesja aktywna, bieg nr 1 w PREP, piloci w kanałach.
        """
        # 1. Utwórz sesję
        resp = client.post("/api/session", json={
            "name": f"UC1_{uid()}", "flight_duration_sec": 120, "prep_duration_sec": 60
        })
        assert resp.json()["status"] == "ok"

        # 2. Zarejestruj 4 pilotów
        pilots = []
        for vtx in ["Analog", "Analog", "DJI", "DJI"]:
            pid, name = make_pilot_in_db()
            r = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": vtx})
            assert r.json()["status"] == "ok"
            pilots.append({"id": pid, "name": name, "vtx": vtx})

        # 3. Rebalans — system proponuje podział
        r = client.post("/api/groups/rebalance", json={})
        assert r.json()["status"] == "ok"
        groups = r.json()["groups"]
        assert len(groups) == 1

        # 4. Start sesji
        r = client.post("/api/session/start")
        assert r.json()["status"] == "ok"

        # 5. Weryfikacja stanu
        session = client.get("/api/session").json()["session"]
        assert session["is_active"] is True
        assert session["current_phase"] == "FLIGHT"

        heat = client.get("/api/heat").json()["heat"]
        assert heat["heat_number"] == 1
        assert heat["status"] == "PREP"
        assert len(heat["channels"]) == 4

    def test_pilot_search_and_add_existing_pilot(self):
        """UC1: Wyszukanie istniejącego pilota i dodanie go do sesji."""
        pid, name = make_pilot_in_db(f"KnownPilot_{uid()}")

        client.post("/api/session", json={
            "name": f"UC1b_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 30
        })

        # Wyszukaj pilota
        search = client.get(f"/api/pilot/search/{name}").json()["pilots"]
        assert any(p["pilot_id"] == pid for p in search)

        # Dodaj znalezionego pilota
        r = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# UC2: Automatyczny cykl treningowy
# ---------------------------------------------------------------------------

class TestUC2_TrainingCycle:

    def test_heat_auto_transitions_prep_to_flight(self):
        """UC2: Po upływie prep_time system automatycznie startuje przelot."""
        client.post("/api/session", json={
            "name": f"UC2_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 2
        })
        pid, _ = make_pilot_in_db()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        assert client.get("/api/heat").json()["heat"]["status"] == "PREP"
        time.sleep(2.5)
        assert client.get("/api/heat").json()["heat"]["status"] == "FLIGHT"

    def test_group_rotation_after_skip(self):
        """UC2: Po każdym biegu system przechodzi do następnej grupy."""
        client.post("/api/session", json={
            "name": f"UC2b_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        p1, n1 = make_pilot_in_db(f"G1_{uid()}")
        p2, n2 = make_pilot_in_db(f"G2_{uid()}")
        client.post("/api/session/add_pilot", json={"pilot_id": p1, "vtx": "Analog"})
        client.post("/api/session/add_pilot", json={"pilot_id": p2, "vtx": "Analog"})

        # Ręczny podział na 2 grupy po 1 pilocie
        client.post("/api/groups/new")
        client.post("/api/groups/new")
        client.post("/api/groups/move_pilot", json={
            "pilot_id": p1, "to_group": 1, "to_channel": "R1"
        })
        client.post("/api/groups/move_pilot", json={
            "pilot_id": p2, "to_group": 2, "to_channel": "R1"
        })
        client.post("/api/session/start")

        heat1 = client.get("/api/heat").json()["heat"]
        assert heat1["channels"]["R1"]["pilot"]["name"] == n1

        client.post("/api/session/skip_heat")

        heat2 = client.get("/api/heat").json()["heat"]
        assert heat2["channels"]["R1"]["pilot"]["name"] == n2
        assert heat2["heat_number"] == 2

    def test_heat_snapshot_is_isolated_from_group_changes(self):
        """
        UC2: Heat jest snapshotem grupy. Zmiany w grupie po starcie
        nie powinny wpływać na trwający bieg.
        """
        client.post("/api/session", json={
            "name": f"UC2c_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        p1, n1 = make_pilot_in_db()
        p2, _ = make_pilot_in_db()
        client.post("/api/session/add_pilot", json={"pilot_id": p1, "vtx": "Analog"})
        client.post("/api/session/add_pilot", json={"pilot_id": p2, "vtx": "Analog"})
        client.post("/api/groups/new")
        client.post("/api/groups/move_pilot", json={
            "pilot_id": p1, "to_group": 1, "to_channel": "R1"
        })
        client.post("/api/session/start")

        # Pilot w biegu przed zmianą
        heat_before = client.get("/api/heat").json()["heat"]
        pilot_in_heat = heat_before["channels"]["R1"]["pilot"]["name"]
        assert pilot_in_heat == n1

        # Zmieniamy grupę (przenosimy p1 do paddocka)
        client.post("/api/groups/move_pilot", json={
            "pilot_id": p1, "from_group": 1, "from_channel": "R1"
        })

        # Bieg nadal ma p1 (snapshot jest niezmienny)
        heat_after = client.get("/api/heat").json()["heat"]
        assert heat_after["channels"]["R1"]["pilot"]["name"] == n1


# ---------------------------------------------------------------------------
# UC4: Zakończenie sesji
# ---------------------------------------------------------------------------

class TestUC4_SessionEnd:

    def test_stop_session_clears_active_state(self, started_session):
        """UC4: Po zatrzymaniu sesja jest nieaktywna i brak aktywnego biegu."""
        client.post("/api/session/stop")
        assert client.get("/api/session").json()["status"] == "error"
        assert client.get("/api/heat").json()["status"] == "error"

    def test_new_session_can_be_created_after_stop(self, started_session):
        """UC4: Po zakończeniu sesji można rozpocząć nową."""
        client.post("/api/session/stop")
        resp = client.post("/api/session", json={
            "name": f"New_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# UC5: Nowy pilot dołącza do sesji
# ---------------------------------------------------------------------------

class TestUC5_PilotJoins:

    def test_add_pilot_during_active_session(self, started_session):
        """UC5: Dodanie pilota nie zatrzymuje cyklu."""
        pid, _ = make_pilot_in_db()
        r = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        assert r.json()["status"] == "ok"

        # Sesja nadal aktywna, bieg nadal trwa
        heat = client.get("/api/heat").json()["heat"]
        assert heat is not None
        assert heat["heat_number"] == 1

    def test_new_pilot_appears_in_active_pilots(self, started_session):
        pid, _ = make_pilot_in_db()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        session = client.get("/api/session").json()["session"]
        assert str(pid) in session["active_pilots"]


# ---------------------------------------------------------------------------
# UC6: Pilot opuszcza sesję
# ---------------------------------------------------------------------------

class TestUC6_PilotLeaves:

    def test_remove_pilot_does_not_stop_cycle(self, started_session):
        """UC6: Usunięcie pilota nie wstrzymuje biegu."""
        _, pilots = started_session
        pid = pilots[0]["id"]

        client.post("/api/session/remove_pilot", json={"pilot_id": pid})

        heat = client.get("/api/heat").json()["heat"]
        assert heat is not None

    def test_removed_pilot_not_in_active_pilots(self, started_session):
        _, pilots = started_session
        pid = pilots[0]["id"]
        client.post("/api/session/remove_pilot", json={"pilot_id": pid})
        session = client.get("/api/session").json()["session"]
        assert str(pid) not in session["active_pilots"]


# ---------------------------------------------------------------------------
# UC7: Widok harmonogramu grup
# ---------------------------------------------------------------------------

class TestUC7_GroupScheduleView:

    def test_groups_endpoint_returns_all_groups(self, session_with_pilots):
        resp = client.get("/api/groups")
        assert resp.json()["status"] == "ok"
        assert len(resp.json()["groups"]) >= 1

    def test_session_groups_list_endpoint(self, session_with_pilots):
        resp = client.get("/api/session/groups")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "groups" in resp.json()

    def test_groups_contain_pilot_names(self, session_with_pilots):
        _, pilots = session_with_pilots
        pilot_names = {p["name"] for p in pilots}
        groups = client.get("/api/groups").json()["groups"]
        names_in_groups = set()
        for g in groups:
            for slot in g["channels"].values():
                if slot:
                    names_in_groups.add(slot["pilot"]["name"])
        assert names_in_groups == pilot_names
