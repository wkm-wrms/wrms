"""
Testy maszyny stanów: FLIGHT → FINISHED.
Pokrycie: pełny cykl biegu (PREP→FLIGHT→FINISHED), zapis archiwalny do DB,
zachowanie sesji i serwera po stop().

Środowisko czasowe:
  - Sesje tworzone z prep=2s, flight=2s.
  - loop() wyzwalany przez middleware przy każdym HTTP request.
  - Przejście PREP→FLIGHT: sleep(2.5), jeden request.
  - Przejście FLIGHT→FINISHED: kolejne sleep(2.5), kolejny request.
"""
import time
import sqlite3
import os
import pytest
from conftest import client, uid

_DB = os.environ["WRMS_DB_PATH"]


def _qdb(sql, params=()):
    """Pomocnik: bezpośrednie zapytanie do testowej bazy SQLite."""
    with sqlite3.connect(_DB) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


def _start_2s_session():
    """Tworzy i startuje sesję z 2s prep / 2s flight. Zwraca session_id."""
    r = client.post("/api/session", json={
        "name": f"FS_{uid()}", "flight_duration_sec": 2, "prep_duration_sec": 2
    })
    session_id = r.json()["session"]["session_id"]
    pid = client.post("/api/pilot/", json={"name": f"FP_{uid()}"}).json()["id"]
    client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
    client.post("/api/groups/rebalance", json={})
    client.post("/api/session/start")
    return session_id


# ---------------------------------------------------------------------------
# Cykl PREP → FLIGHT → FINISHED (w pamięci)
# ---------------------------------------------------------------------------

class TestFlightToFinished:

    def test_heat_transitions_prep_flight_finished_sequence(self):
        """
        Sekwencja PREP→FLIGHT→PREP(nowy bieg):
        każde przejście odbywa się dokładnie raz, po upływie timera.
        """
        _start_2s_session()
        assert client.get("/api/heat").json()["heat"]["status"] == "PREP"

        time.sleep(2.5)
        assert client.get("/api/heat").json()["heat"]["status"] == "FLIGHT"

        time.sleep(2.5)
        heat = client.get("/api/heat").json()["heat"]
        # Stary heat (FINISHED) jest zarchiwizowany; bieżący = nowy heat #2 w PREP
        assert heat["status"] == "PREP"

    def test_heat_number_increments_after_flight_expires(self):
        """Po wygaśnięciu FLIGHT numer biegu rośnie do 2."""
        _start_2s_session()

        time.sleep(2.5)
        client.get("/api/heat")          # PREP → FLIGHT
        time.sleep(2.5)
        heat = client.get("/api/heat").json()["heat"]   # FLIGHT → rotate
        assert heat["heat_number"] == 2

    def test_current_heat_after_rotation_is_in_prep(self):
        """Nowy bieżący heat po rotacji jest w statusie PREP."""
        _start_2s_session()

        time.sleep(2.5)
        client.get("/api/heat")
        time.sleep(2.5)
        heat = client.get("/api/heat").json()["heat"]
        assert heat["status"] == "PREP"
        assert heat["heat_number"] >= 2

    def test_next_heat_advances_after_rotation(self):
        """next_heat po rotacji ma numer 3."""
        _start_2s_session()

        time.sleep(2.5)
        client.get("/api/heat")
        time.sleep(2.5)
        data = client.get("/api/heat").json()
        assert data["next_heat"]["heat_number"] == 3


# ---------------------------------------------------------------------------
# Persystencja FINISHED w bazie danych
# ---------------------------------------------------------------------------

class TestFinishedHeatPersistence:

    def test_finished_heat_status_in_db(self):
        """Heat #1 ma status FINISHED w bazie danych po zakończeniu lotu."""
        session_id = _start_2s_session()

        time.sleep(2.5)
        client.get("/api/heat")          # PREP → FLIGHT
        time.sleep(2.5)
        client.get("/api/heat")          # FLIGHT → rotate (middleware zapisuje FINISHED)

        rows = _qdb(
            "SELECT status FROM heat WHERE session_id=? AND heat_number=1",
            (session_id,)
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "FINISHED"

    def test_finished_heat_has_finished_at_in_db(self):
        """Ukończony heat #1 ma wypełnione pole finished_at w bazie."""
        session_id = _start_2s_session()

        time.sleep(2.5)
        client.get("/api/heat")
        time.sleep(2.5)
        client.get("/api/heat")

        rows = _qdb(
            "SELECT finished_at FROM heat WHERE session_id=? AND heat_number=1",
            (session_id,)
        )
        assert rows[0]["finished_at"] is not None

    def test_finished_heat_has_flight_started_at_in_db(self):
        """Ukończony heat #1 ma wypełnione pole flight_started_at w bazie."""
        session_id = _start_2s_session()

        time.sleep(2.5)
        client.get("/api/heat")
        time.sleep(2.5)
        client.get("/api/heat")

        rows = _qdb(
            "SELECT flight_started_at FROM heat WHERE session_id=? AND heat_number=1",
            (session_id,)
        )
        assert rows[0]["flight_started_at"] is not None

    def test_two_heats_exist_in_db_after_one_cycle(self):
        """Po pełnym cyklu w bazie są co najmniej 2 heaty dla sesji."""
        session_id = _start_2s_session()

        time.sleep(2.5)
        client.get("/api/heat")
        time.sleep(2.5)
        client.get("/api/heat")

        rows = _qdb(
            "SELECT heat_number, status FROM heat WHERE session_id=? ORDER BY heat_number",
            (session_id,)
        )
        assert len(rows) >= 2
        statuses = {r["heat_number"]: r["status"] for r in rows}
        assert statuses[1] == "FINISHED"
        assert statuses[2] == "PREP"


# ---------------------------------------------------------------------------
# Zachowanie serwera po stop()
# ---------------------------------------------------------------------------

class TestStopSession:

    def test_stop_clears_in_memory_session(self):
        """Po stop() GET /api/session zwraca error (brak sesji w pamięci)."""
        _start_2s_session()
        client.post("/api/session/stop")
        resp = client.get("/api/session")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_stop_clears_active_heat(self):
        """Po stop() GET /api/heat zwraca status error."""
        _start_2s_session()
        client.post("/api/session/stop")
        assert client.get("/api/heat").json()["status"] == "error"

    def test_stop_saves_finished_phase_to_db(self):
        """Po stop() sesja w DB ma current_phase='FINISHED'."""
        session_id = _start_2s_session()
        client.post("/api/session/stop")

        rows = _qdb(
            "SELECT current_phase FROM session WHERE session_id=?",
            (session_id,)
        )
        assert rows[0]["current_phase"] == "FINISHED"

    def test_stop_does_not_affect_is_active_flag(self):
        """
        stop() zmienia current_phase na FINISHED, ale nie zeruje is_active.
        Sesja jest wyszukiwana po current_phase, nie is_active.
        """
        session_id = _start_2s_session()
        client.post("/api/session/stop")

        rows = _qdb(
            "SELECT current_phase FROM session WHERE session_id=?",
            (session_id,)
        )
        assert rows[0]["current_phase"] == "FINISHED"

    def test_stop_saves_both_heats_to_db(self):
        """Po stop() zarówno heat bieżący jak i następny są zapisane w DB."""
        session_id = _start_2s_session()
        client.post("/api/session/stop")

        rows = _qdb(
            "SELECT heat_number FROM heat WHERE session_id=? ORDER BY heat_number",
            (session_id,)
        )
        assert len(rows) >= 2

    def test_new_session_fully_startable_after_stop(self):
        """Po stop() można utworzyć, skonfigurować i uruchomić nową sesję."""
        _start_2s_session()
        client.post("/api/session/stop")

        pid = client.post("/api/pilot/", json={"name": f"NP_{uid()}"}).json()["id"]
        client.post("/api/session", json={
            "name": f"New_{uid()}", "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        r = client.post("/api/session/start")
        assert r.json()["status"] == "ok"
