"""
Testy persystencji bazy danych.
Weryfikacja, że każda operacja zapisu jest trwała i dostępna po symulowanym
restarcie serwera (= nowa instancja RaceDatabase na tym samym pliku DB).

Wzorzec "symulowany restart":
    fresh = RaceDatabase(os.environ["WRMS_DB_PATH"])
    # fresh.get_session_by_id(...) / fresh.get_active_pilots(...) etc.

Odpowiada temu, co main.py robi przy starcie:
    db = RaceDatabase()   (odczytuje WRMS_DB_PATH)
    active_session = db.get_active_session()
"""
import json
import sqlite3
import os
import pytest
from conftest import client, uid
from database import RaceDatabase

_DB = os.environ["WRMS_DB_PATH"]


def _qdb(sql, params=()):
    """Direct SQLite query — bypasses app layer, proves raw persistence."""
    with sqlite3.connect(_DB) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


def _fresh_db() -> RaceDatabase:
    """New RaceDatabase instance — simulates server restart."""
    return RaceDatabase(_DB)


def _make_session(flight=60, prep=30) -> str:
    """Creates a session via API and returns session_id."""
    r = client.post("/api/session", json={
        "name": f"Ses_{uid()}", "flight_duration_sec": flight, "prep_duration_sec": prep
    })
    return r.json()["session"]["session_id"]


def _make_pilot(vtx="Analog") -> int:
    """Creates a pilot via API and returns pilot_id."""
    return client.post("/api/pilot/", json={"name": f"P_{uid()}"}).json()["id"]


def _full_start(flight=60, prep=30):
    """Creates session + pilot + rebalance + start. Returns (session_id, pilot_id)."""
    sid = _make_session(flight, prep)
    pid = _make_pilot()
    client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
    client.post("/api/groups/rebalance", json={})
    client.post("/api/session/start")
    return sid, pid


# ---------------------------------------------------------------------------
# Pilot persistence
# ---------------------------------------------------------------------------

class TestPilotPersistence:

    def test_pilot_written_to_db_immediately(self):
        """Nowo dodany pilot jest natychmiast widoczny via bezpośrednie SQL."""
        name = f"Persist_{uid()}"
        pid = client.post("/api/pilot/", json={"name": name}).json()["id"]

        rows = _qdb("SELECT name FROM pilot WHERE pilot_id=?", (pid,))
        assert len(rows) == 1 and rows[0]["name"] == name

    def test_pilot_country_persisted(self):
        """Pole country pilota jest zapisywane."""
        name = f"Country_{uid()}"
        pid = client.post("/api/pilot/", json={"name": name, "country": "DE"}).json()["id"]

        rows = _qdb("SELECT country FROM pilot WHERE pilot_id=?", (pid,))
        assert rows[0]["country"] == "DE"

    def test_pilot_readable_via_fresh_db_instance(self):
        """Pilot jest widoczny przez nową instancję RaceDatabase (restart)."""
        name = f"Restart_{uid()}"
        pid = client.post("/api/pilot/", json={"name": name}).json()["id"]

        pilot = _fresh_db().get_pilot_by_id(pid)
        assert pilot is not None and pilot.name == name

    def test_pilot_search_works_on_fresh_db_instance(self):
        """search_pilots() na nowej instancji zwraca pilota dodanego wcześniej."""
        name = f"Searchable_{uid()}"
        client.post("/api/pilot/", json={"name": name})

        results = _fresh_db().search_pilots(name)
        assert any(p.name == name for p in results)


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

class TestSessionPersistence:

    def test_session_written_to_db_on_create(self):
        """Nowo tworzona sesja jest widoczna w tabeli session."""
        name = f"Ses_{uid()}"
        r = client.post("/api/session", json={
            "name": name, "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        sid = r.json()["session"]["session_id"]

        rows = _qdb("SELECT name, flight_duration_sec, prep_duration_sec FROM session WHERE session_id=?", (sid,))
        assert rows[0]["name"] == name
        assert rows[0]["flight_duration_sec"] == 60
        assert rows[0]["prep_duration_sec"] == 30

    def test_session_readable_via_fresh_db_instance(self):
        """get_session_by_id() na nowej instancji zwraca poprawną sesję."""
        name = f"RS_{uid()}"
        r = client.post("/api/session", json={
            "name": name, "flight_duration_sec": 60, "prep_duration_sec": 30
        })
        sid = r.json()["session"]["session_id"]

        session = _fresh_db().get_session_by_id(sid)
        assert session is not None and session.name == name

    def test_session_start_persists_is_active_true(self):
        """Po start() is_active=1 jest zapisane w DB."""
        sid, _ = _full_start()

        rows = _qdb("SELECT is_active FROM session WHERE session_id=?", (sid,))
        assert rows[0]["is_active"] == 1

    def test_session_start_persists_flight_phase(self):
        """Po start() current_phase='FLIGHT' jest w DB."""
        sid, _ = _full_start()

        rows = _qdb("SELECT current_phase FROM session WHERE session_id=?", (sid,))
        assert rows[0]["current_phase"] == "FLIGHT"

    def test_session_start_persists_heat_number(self):
        """Po start() current_heat_number=1 jest w DB."""
        sid, _ = _full_start()

        rows = _qdb("SELECT current_heat_number FROM session WHERE session_id=?", (sid,))
        assert rows[0]["current_heat_number"] == 1

    def test_session_stop_persists_finished_phase(self):
        """Po stop() current_phase='FINISHED' jest w DB."""
        sid, _ = _full_start()
        client.post("/api/session/stop")

        rows = _qdb("SELECT current_phase, is_active FROM session WHERE session_id=?", (sid,))
        assert rows[0]["current_phase"] == "FINISHED"

    def test_stopped_session_has_finished_phase_on_fresh_db(self):
        """
        Sesja po stop() jest załadowana przez nową instancję DB
        z current_phase='FINISHED' — nie wróci jako aktywna po restarcie.
        """
        sid, _ = _full_start()
        client.post("/api/session/stop")

        session = _fresh_db().get_session_by_id(sid)
        assert session.current_phase == "FINISHED"


# ---------------------------------------------------------------------------
# Active pilot persistence (session ↔ pilot binding)
# ---------------------------------------------------------------------------

class TestActivePilotPersistence:

    def test_add_pilot_written_to_active_pilot_table(self):
        """Dodanie pilota do sesji jest widoczne w tabeli active_pilot."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "DJI"})

        rows = _qdb(
            "SELECT vtx FROM active_pilot WHERE session_id=? AND pilot_id=?",
            (sid, pid)
        )
        assert len(rows) == 1 and rows[0]["vtx"] == "DJI"

    def test_remove_pilot_removed_from_active_pilot_table(self):
        """Usunięcie pilota z sesji jest odzwierciedlone w active_pilot."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/session/remove_pilot", json={"pilot_id": pid})

        rows = _qdb(
            "SELECT * FROM active_pilot WHERE session_id=? AND pilot_id=?",
            (sid, pid)
        )
        assert len(rows) == 0

    def test_active_pilots_readable_via_fresh_db(self):
        """Piloci dodani do sesji są widoczni przez nową instancję DB."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})

        pilots = _fresh_db().get_active_pilots(sid)
        assert pid in pilots and pilots[pid].vtx == "Analog"

    def test_multiple_pilots_all_persisted(self):
        """Wszystkie dodane piloty są w active_pilot po operacji."""
        sid = _make_session()
        pids = []
        for vtx in ["Analog", "Analog", "DJI", "DJI"]:
            pid = _make_pilot(vtx)
            client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": vtx})
            pids.append(pid)

        rows = _qdb("SELECT pilot_id FROM active_pilot WHERE session_id=?", (sid,))
        stored_ids = {r["pilot_id"] for r in rows}
        assert all(pid in stored_ids for pid in pids)


# ---------------------------------------------------------------------------
# Group persistence
# ---------------------------------------------------------------------------

class TestGroupPersistence:

    def test_rebalance_saves_groups_to_session_group(self):
        """Grupy po rebalansie są w tabeli session_group."""
        sid = _make_session()
        for _ in range(4):
            pid = _make_pilot()
            client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})

        rows = _qdb("SELECT group_id FROM session_group WHERE session_id=?", (sid,))
        assert len(rows) == 1

    def test_group_channel_map_persisted_correctly(self):
        """channel_map w session_group poprawnie mapuje kanały na pilot_id."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/new")
        client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "to_group": 1, "to_channel": "R1"
        })

        rows = _qdb("SELECT channel_map FROM session_group WHERE session_id=?", (sid,))
        channel_map = json.loads(rows[0]["channel_map"])
        assert "R1" in channel_map and channel_map["R1"] == pid

    def test_group_readable_via_fresh_db(self):
        """Grupy po rebalansie są dostępne przez nową instancję DB."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})

        fresh = _fresh_db()
        groups = fresh.get_groups_by_session_id(sid, fresh.get_active_pilots(sid))
        assert len(groups) == 1 and len(groups[0].channels) == 1

    def test_8_pilots_two_groups_both_persisted(self):
        """8 pilotów po rebalansie → 2 grupy w session_group."""
        sid = _make_session()
        for _ in range(8):
            pid = _make_pilot()
            client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})

        rows = _qdb("SELECT group_id FROM session_group WHERE session_id=?", (sid,))
        assert len(rows) == 2

    def test_group_removed_after_rebalance_overwrites(self):
        """Ponowny rebalans nadpisuje poprzednie grupy (brak duplikatów)."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/groups/rebalance", json={})  # drugi raz

        rows = _qdb("SELECT group_id FROM session_group WHERE session_id=?", (sid,))
        assert len(rows) == 1  # nie 2


# ---------------------------------------------------------------------------
# Heat persistence
# ---------------------------------------------------------------------------

class TestHeatPersistence:

    def test_two_heats_created_on_session_start(self):
        """Po start() tabela heat zawiera heat #1 i #2 dla sesji."""
        sid, _ = _full_start()

        rows = _qdb(
            "SELECT heat_number FROM heat WHERE session_id=? ORDER BY heat_number",
            (sid,)
        )
        heat_numbers = [r["heat_number"] for r in rows]
        assert 1 in heat_numbers and 2 in heat_numbers

    def test_heat1_status_is_prep_after_start(self):
        """Po start() heat #1 ma status PREP w DB."""
        sid, _ = _full_start()

        rows = _qdb("SELECT status FROM heat WHERE session_id=? AND heat_number=1", (sid,))
        assert rows[0]["status"] == "PREP"

    def test_heat1_prep_started_at_set_after_start(self):
        """Po start() heat #1 ma prep_started_at wypełnione w DB."""
        sid, _ = _full_start()

        rows = _qdb("SELECT prep_started_at FROM heat WHERE session_id=? AND heat_number=1", (sid,))
        assert rows[0]["prep_started_at"] is not None

    def test_heat_channels_json_contains_pilot(self):
        """channels_json heat #1 zawiera poprawny pilot_id."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        rows = _qdb("SELECT channels_json FROM heat WHERE session_id=? AND heat_number=1", (sid,))
        channels = json.loads(rows[0]["channels_json"])
        pilot_ids = [v["pilot_id"] for v in channels.values()]
        assert pid in pilot_ids

    def test_pilot_heat_records_created_on_start(self):
        """Po start() tabela pilot_heat zawiera wpisy dla pilotów w heat #1."""
        sid = _make_session()
        pid = _make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        rows = _qdb(
            "SELECT pilot_id FROM pilot_heat WHERE session_id=? AND heat_number=1",
            (sid,)
        )
        assert any(r["pilot_id"] == pid for r in rows)

    def test_skip_heat_saves_finished_status_to_db(self):
        """Po skip_heat() heat #1 ma status FINISHED w DB."""
        sid, _ = _full_start()
        client.post("/api/session/skip_heat")

        rows = _qdb("SELECT status FROM heat WHERE session_id=? AND heat_number=1", (sid,))
        assert rows[0]["status"] == "FINISHED"

    def test_skip_heat_advances_current_heat_in_db(self):
        """Po skip_heat() heat #2 ma status PREP w DB."""
        sid, _ = _full_start()
        client.post("/api/session/skip_heat")

        rows = _qdb("SELECT status FROM heat WHERE session_id=? AND heat_number=2", (sid,))
        assert rows[0]["status"] == "PREP"

    def test_heat_readable_via_fresh_db(self):
        """Heat jest dostępny przez nową instancję DB po start()."""
        sid, pid = _full_start()

        fresh = _fresh_db()
        pilots = fresh.get_active_pilots(sid)
        heat = fresh.get_heat_by_number(sid, 1, pilots)
        assert heat is not None and heat.status == "PREP"

    def test_session_reloaded_with_current_heat_after_restart(self):
        """
        Sesja załadowana przez nową instancję DB ma current_heat z heat_number=1.
        Odpowiada zachowaniu main.py przy restarcie serwera po aktywnej sesji.
        """
        sid, _ = _full_start()

        session = _fresh_db().get_session_by_id(sid)
        assert session is not None
        assert session.current_heat is not None
        assert session.current_heat.heat_number == 1
        assert session.is_active

    def test_session_reloaded_with_active_pilots_after_restart(self):
        """Sesja załadowana po restarcie zawiera listę aktywnych pilotów."""
        sid = _make_session()
        pids = []
        for _ in range(3):
            pid = _make_pilot()
            client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
            pids.append(pid)
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        session = _fresh_db().get_session_by_id(sid)
        assert all(pid in session.active_pilots for pid in pids)

    def test_session_reloaded_with_groups_after_restart(self):
        """Sesja załadowana po restarcie zawiera grupy z pilotami."""
        sid, pid = _full_start()

        session = _fresh_db().get_session_by_id(sid)
        assert len(session.groups) >= 1
        assigned = [
            slot.pilot_id
            for g in session.groups
            for slot in g.channels.values()
        ]
        assert pid in assigned
