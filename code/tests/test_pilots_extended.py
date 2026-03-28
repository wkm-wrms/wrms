"""
Extended pilot tests: new fields (risk_factor, notes), PUT /api/pilot/{id},
DELETE /api/pilot/{id}, persistence, and auth enforcement.
"""
import pytest
from fastapi.testclient import TestClient
from main import app
from database import get_db

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_pilot(name="TestPilot", country="PL", risk_factor=3, notes=""):
    r = client.post("/api/pilot/", json={"name": name, "country": country,
                                         "risk_factor": risk_factor, "notes": notes})
    assert r.json()["status"] == "ok"
    return r.json()["id"]


# ---------------------------------------------------------------------------
# New fields — create and read back
# ---------------------------------------------------------------------------

class TestPilotNewFields:
    def test_create_with_risk_factor(self):
        pid = _create_pilot(name="RiskPilot", risk_factor=5)
        r = client.get(f"/api/pilot/{pid}")
        assert r.json()["pilot"]["risk_factor"] == 5

    def test_create_with_notes(self):
        pid = _create_pilot(name="NotesPilot", notes="Test note here")
        r = client.get(f"/api/pilot/{pid}")
        assert r.json()["pilot"]["notes"] == "Test note here"

    def test_default_risk_factor_is_3(self):
        r = client.post("/api/pilot/", json={"name": "DefaultRisk"})
        pid = r.json()["id"]
        assert client.get(f"/api/pilot/{pid}").json()["pilot"]["risk_factor"] == 3

    def test_default_notes_is_empty(self):
        r = client.post("/api/pilot/", json={"name": "DefaultNotes"})
        pid = r.json()["id"]
        assert client.get(f"/api/pilot/{pid}").json()["pilot"]["notes"] == ""

    def test_new_fields_in_search_results(self):
        _create_pilot(name="SearchMe", risk_factor=2, notes="found")
        r = client.get("/api/pilot/search/SearchMe")
        p = r.json()["pilots"][0]
        assert p["risk_factor"] == 2
        assert p["notes"] == "found"


# ---------------------------------------------------------------------------
# PUT /api/pilot/{id}
# ---------------------------------------------------------------------------

class TestPilotUpdate:
    def test_update_name(self):
        pid = _create_pilot(name="OldName")
        r = client.put(f"/api/pilot/{pid}", json={"name": "NewName"})
        assert r.json()["status"] == "ok"
        assert r.json()["pilot"]["name"] == "NewName"

    def test_update_risk_factor(self):
        pid = _create_pilot(name="RiskUpdate")
        client.put(f"/api/pilot/{pid}", json={"name": "RiskUpdate", "risk_factor": 6})
        assert client.get(f"/api/pilot/{pid}").json()["pilot"]["risk_factor"] == 6

    def test_update_notes(self):
        pid = _create_pilot(name="NotesUpdate")
        client.put(f"/api/pilot/{pid}", json={"name": "NotesUpdate", "notes": "updated"})
        assert client.get(f"/api/pilot/{pid}").json()["pilot"]["notes"] == "updated"

    def test_update_country(self):
        pid = _create_pilot(name="CountryUpdate", country="PL")
        client.put(f"/api/pilot/{pid}", json={"name": "CountryUpdate", "country": "DE"})
        assert client.get(f"/api/pilot/{pid}").json()["pilot"]["country"] == "DE"

    def test_update_nonexistent_returns_error(self):
        r = client.put("/api/pilot/99999", json={"name": "Ghost"})
        assert r.json()["status"] == "error"

    def test_update_empty_name_returns_error(self):
        pid = _create_pilot(name="EmptyNameTest")
        r = client.put(f"/api/pilot/{pid}", json={"name": ""})
        assert r.json()["status"] == "error"

    def test_update_risk_too_low_returns_error(self):
        pid = _create_pilot(name="RiskLow")
        r = client.put(f"/api/pilot/{pid}", json={"name": "RiskLow", "risk_factor": 0})
        assert r.json()["status"] == "error"

    def test_update_risk_too_high_returns_error(self):
        pid = _create_pilot(name="RiskHigh")
        r = client.put(f"/api/pilot/{pid}", json={"name": "RiskHigh", "risk_factor": 7})
        assert r.json()["status"] == "error"

    def test_update_duplicate_name_returns_error(self):
        _create_pilot(name="PilotA")
        pid = _create_pilot(name="PilotB")
        r = client.put(f"/api/pilot/{pid}", json={"name": "PilotA"})
        assert r.json()["status"] == "error"


# ---------------------------------------------------------------------------
# DELETE /api/pilot/{id}
# ---------------------------------------------------------------------------

class TestPilotDelete:
    def test_delete_pilot(self):
        pid = _create_pilot(name="ToDelete")
        r = client.delete(f"/api/pilot/{pid}")
        assert r.json()["status"] == "ok"
        assert client.get(f"/api/pilot/{pid}").json()["status"] == "error"

    def test_delete_nonexistent_returns_error(self):
        r = client.delete("/api/pilot/99999")
        assert r.json()["status"] == "error"

    def test_delete_active_pilot_returns_error(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        r = client.delete(f"/api/pilot/{pid}")
        assert r.json()["status"] == "error"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPilotPersistence:
    def test_new_fields_survive_db_reload(self):
        pid = _create_pilot(name="PersistPilot", risk_factor=4, notes="persisted")
        db = get_db()
        reloaded = db.get_pilot_by_id(pid)
        assert reloaded.risk_factor == 4
        assert reloaded.notes == "persisted"

    def test_updated_fields_survive_db_reload(self):
        pid = _create_pilot(name="PersistUpdate")
        client.put(f"/api/pilot/{pid}", json={"name": "PersistUpdate", "risk_factor": 5, "notes": "new note"})
        db = get_db()
        reloaded = db.get_pilot_by_id(pid)
        assert reloaded.risk_factor == 5
        assert reloaded.notes == "new note"


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------

def test_put_requires_auth(monkeypatch):
    monkeypatch.delenv("WRMS_SKIP_AUTH", raising=False)
    with TestClient(app) as c:
        r = c.put("/api/pilot/1", json={"name": "x"})
        assert r.status_code == 401


def test_delete_requires_auth(monkeypatch):
    monkeypatch.delenv("WRMS_SKIP_AUTH", raising=False)
    with TestClient(app) as c:
        r = c.delete("/api/pilot/1")
        assert r.status_code == 401
