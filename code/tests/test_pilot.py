"""
Testy dla modułu zarządzania pilotami (CRUD, wyszukiwanie).
Pokrycie: Req 2.1 (Model Pilot), endpoint /api/pilot/
"""
import pytest
from conftest import client, uid


class TestPilotCreate:

    def test_create_pilot_returns_id_and_ok(self, make_pilot):
        pid, _ = make_pilot()
        assert isinstance(pid, int)
        assert pid > 0

    def test_create_pilot_name_persisted(self, make_pilot):
        pid, name = make_pilot()
        resp = client.get(f"/api/pilot/{pid}")
        assert resp.status_code == 200
        assert resp.json()["pilot"]["name"] == name

    def test_create_pilot_country_persisted(self, make_pilot):
        pid, _ = make_pilot(country="DE")
        resp = client.get(f"/api/pilot/{pid}")
        assert resp.json()["pilot"]["country"] == "DE"

    def test_create_pilot_country_optional(self):
        name = f"NoCntry_{uid()}"
        resp = client.post("/api/pilot/", json={"name": name})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_create_pilot_duplicate_name_returns_error(self, make_pilot):
        _, name = make_pilot()
        resp = client.post("/api/pilot/", json={"name": name})
        assert resp.json()["status"] == "error"

    def test_create_pilot_empty_name_returns_error(self):
        resp = client.post("/api/pilot/", json={"name": ""})
        assert resp.json()["status"] == "error"


class TestPilotGet:

    def test_get_pilot_by_id(self, make_pilot):
        pid, name = make_pilot()
        resp = client.get(f"/api/pilot/{pid}")
        assert resp.status_code == 200
        data = resp.json()["pilot"]
        assert data["pilot_id"] == pid
        assert data["name"] == name

    def test_get_pilot_not_found_returns_error(self):
        resp = client.get("/api/pilot/9999999")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_get_all_pilots_returns_list(self, make_pilot):
        make_pilot()
        resp = client.get("/api/pilot/")
        assert resp.status_code == 200
        assert isinstance(resp.json()["pilots"], list)
        assert len(resp.json()["pilots"]) >= 1


class TestPilotSearch:

    def test_search_finds_exact_name(self, make_pilot):
        pid, name = make_pilot()
        resp = client.get(f"/api/pilot/search/{name}")
        assert resp.status_code == 200
        ids = [p["pilot_id"] for p in resp.json()["pilots"]]
        assert pid in ids

    def test_search_finds_partial_name(self, make_pilot):
        unique = f"SRCH_{uid()}"
        make_pilot(name=f"{unique}_full")
        resp = client.get(f"/api/pilot/search/{unique}")
        assert len(resp.json()["pilots"]) >= 1

    def test_search_no_match_returns_empty_list(self):
        resp = client.get("/api/pilot/search/XYZNOTEXISTS_999_abc")
        assert resp.status_code == 200
        assert resp.json()["pilots"] == []

    def test_search_result_contains_required_fields(self, make_pilot):
        make_pilot()
        resp = client.get("/api/pilot/search/Pilot_")
        pilots = resp.json()["pilots"]
        if pilots:
            p = pilots[0]
            assert "pilot_id" in p
            assert "name" in p
