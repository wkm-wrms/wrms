"""
Tests for the public pilot view (Frontend 2).

Covers:
  - GET /pilot/{session_id} returns 200 with HTML for active session
  - GET /pilot/{session_id} returns 404 for unknown or inactive session
  - GET /api/heat includes session_id field
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from conftest import client, uid  # noqa: E402


class TestPilotViewRoute:
    """Tests for the /pilot/{session_id} HTML route."""

    def test_pilot_view_unknown_session_returns_404(self):
        """Unknown session_id returns 404 HTML with 'Session is not active'."""
        r = client.get("/pilot/nonexistent-session-xyz")
        assert r.status_code == 404
        assert "text/html" in r.headers["content-type"]
        assert "Session is not active" in r.text

    def test_pilot_view_wrong_id_returns_404(self):
        """Wrong session_id (even if a session is active) returns 404."""
        client.post("/api/session", json={
            "name": f"S_{uid()}",
            "flight_duration_sec": 60,
            "prep_duration_sec": 30,
        })
        r = client.get("/pilot/wrong-id")
        assert r.status_code == 404

    def test_pilot_view_no_session_returns_404(self):
        """No active session returns 404."""
        r = client.get("/pilot/any-id")
        assert r.status_code == 404

    def test_pilot_view_active_session_returns_200(self):
        """Correct session_id of active session returns 200 HTML."""
        client.post("/api/session", json={
            "name": f"S_{uid()}",
            "flight_duration_sec": 60,
            "prep_duration_sec": 30,
        })
        r = client.post("/api/pilot/", json={"name": f"P_{uid()}"})
        pid = r.json()["id"]
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        sid = client.get("/api/heat").json()["heat"]["session_id"]
        r = client.get(f"/pilot/{sid}")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


class TestHeatApiSessionId:
    """Tests that GET /api/heat includes session_id for QR code generation."""

    def _create_and_start_session(self):
        """Create a session with one pilot, rebalance, and start."""
        client.post("/api/session", json={
            "name": f"S_{uid()}",
            "flight_duration_sec": 60,
            "prep_duration_sec": 30,
        })
        r = client.post("/api/pilot/", json={"name": f"P_{uid()}"})
        pid = r.json()["id"]
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

    def test_heat_response_contains_session_id(self):
        """GET /api/heat includes session_id in the heat dict."""
        self._create_and_start_session()
        r = client.get("/api/heat")
        data = r.json()
        assert data["status"] == "ok"
        assert "session_id" in data["heat"]
        assert data["heat"]["session_id"] is not None

    def test_heat_session_id_matches_pilot_route(self):
        """session_id from heat response gives 200 on the pilot view route."""
        self._create_and_start_session()
        sid = client.get("/api/heat").json()["heat"]["session_id"]
        r = client.get(f"/pilot/{sid}")
        assert r.status_code == 200
