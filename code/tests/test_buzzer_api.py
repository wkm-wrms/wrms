"""
Tests for GET /api/buzzer — the hardware buzzer endpoint.

Coverage:
  - Response shape and required fields
  - Phase and poll_interval_sec for IDLE / PREP / FLIGHT
  - Alarm generation: PREP_START, FLIGHT_START, FLIGHT_WARNING_30,
    COUNTDOWN alarms, FLIGHT_END
  - Alarm ID format and uniqueness
  - Short flights (< WARNING_AT_SEC): no WARNING_30, reduced COUNTDOWN set
  - No alarms emitted while paused
  - Public access (no auth required)
"""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from conftest import client, uid  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _create_and_start(flight_sec=120, prep_sec=2):
    """Create a session with one pilot, rebalance, and start. Return session."""
    client.post("/api/session", json={
        "name": f"S_{uid()}",
        "flight_duration_sec": flight_sec,
        "prep_duration_sec": prep_sec,
    })
    r = client.post("/api/pilot/", json={"name": f"P_{uid()}"})
    pid = r.json()["id"]
    client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
    client.post("/api/groups/rebalance", json={})
    client.post("/api/session/start")


def _advance_to_flight(prep_sec=2):
    """Wait for the PREP phase to expire and advance to FLIGHT via middleware."""
    time.sleep(prep_sec + 0.3)
    client.get("/api/heat")  # triggers session.loop() in middleware


# --------------------------------------------------------------------------- #
# IDLE (no session)                                                            #
# --------------------------------------------------------------------------- #

class TestBuzzerIdle:

    def test_no_session_returns_ok(self):
        r = client.get("/api/buzzer")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_no_session_phase_is_idle(self):
        r = client.get("/api/buzzer")
        assert r.json()["phase"] == "IDLE"

    def test_no_session_no_alarms(self):
        r = client.get("/api/buzzer")
        assert r.json()["alarms"] == []

    def test_no_session_poll_interval_is_15(self):
        r = client.get("/api/buzzer")
        assert r.json()["poll_interval_sec"] == 15

    def test_response_contains_server_time(self):
        r = client.get("/api/buzzer")
        data = r.json()
        assert "server_time" in data
        # Should end with Z (UTC)
        assert data["server_time"].endswith("Z")

    def test_endpoint_is_public(self):
        """No authentication cookie required."""
        r = client.get("/api/buzzer", cookies={})
        assert r.status_code == 200


# --------------------------------------------------------------------------- #
# PREP phase                                                                   #
# --------------------------------------------------------------------------- #

class TestBuzzerPrep:

    def test_prep_phase_is_reported(self):
        _create_and_start(prep_sec=30)
        r = client.get("/api/buzzer")
        assert r.json()["phase"] == "PREP"

    def test_prep_poll_interval_is_10(self):
        _create_and_start(prep_sec=30)
        r = client.get("/api/buzzer")
        assert r.json()["poll_interval_sec"] == 10

    def test_prep_includes_prep_start_alarm(self):
        """PREP_START alarm should be present while prep just started."""
        _create_and_start(prep_sec=30)
        r = client.get("/api/buzzer")
        types = [a["type"] for a in r.json()["alarms"]]
        assert "PREP_START" in types

    def test_prep_includes_future_flight_start_alarm(self):
        """FLIGHT_START alarm is predictable: prep_started_at + prep_time."""
        _create_and_start(prep_sec=30)
        r = client.get("/api/buzzer")
        types = [a["type"] for a in r.json()["alarms"]]
        assert "FLIGHT_START" in types

    def test_prep_flight_start_fire_at_is_in_future(self):
        """FLIGHT_START fire_at must be in the future relative to server_time."""
        _create_and_start(prep_sec=30)
        data = client.get("/api/buzzer").json()
        server_time = data["server_time"]
        flight_start = next(a for a in data["alarms"] if a["type"] == "FLIGHT_START")
        # Simple lexicographic comparison works for ISO-8601 UTC timestamps
        assert flight_start["fire_at"] > server_time

    def test_prep_alarm_id_format(self):
        """PREP_START alarm ID follows the heat-{n}-TYPE scheme."""
        _create_and_start(prep_sec=30)
        alarms = client.get("/api/buzzer").json()["alarms"]
        prep_alarm = next(a for a in alarms if a["type"] == "PREP_START")
        assert prep_alarm["id"].startswith("heat-")
        assert "PREP_START" in prep_alarm["id"]

    def test_prep_no_flight_end_alarms(self):
        """No FLIGHT_END / COUNTDOWN alarms should appear during PREP."""
        _create_and_start(prep_sec=30)
        types = [a["type"] for a in client.get("/api/buzzer").json()["alarms"]]
        assert "FLIGHT_END" not in types
        assert "COUNTDOWN" not in types
        assert "FLIGHT_WARNING_30" not in types


# --------------------------------------------------------------------------- #
# FLIGHT phase                                                                 #
# --------------------------------------------------------------------------- #

class TestBuzzerFlight:

    def test_flight_phase_is_reported(self):
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        r = client.get("/api/buzzer")
        assert r.json()["phase"] == "FLIGHT"

    def test_flight_poll_interval_is_5(self):
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        r = client.get("/api/buzzer")
        assert r.json()["poll_interval_sec"] == 5

    def test_flight_includes_warning_30(self):
        """Long flight (120s): FLIGHT_WARNING_30 alarm must be present."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        types = [a["type"] for a in client.get("/api/buzzer").json()["alarms"]]
        assert "FLIGHT_WARNING_30" in types

    def test_flight_includes_countdown_alarms(self):
        """Long flight: full countdown 10 → 1 must be present."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        countdown_alarms = [a for a in alarms if a["type"] == "COUNTDOWN"]
        assert len(countdown_alarms) == 10

    def test_flight_includes_flight_end_alarm(self):
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        types = [a["type"] for a in client.get("/api/buzzer").json()["alarms"]]
        assert "FLIGHT_END" in types

    def test_flight_alarm_fire_at_in_future(self):
        """All FLIGHT_END / COUNTDOWN alarm fire_at values must be in the future."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        data = client.get("/api/buzzer").json()
        server_time = data["server_time"]
        for alarm in data["alarms"]:
            if alarm["type"] in ("FLIGHT_END", "COUNTDOWN", "FLIGHT_WARNING_30"):
                assert alarm["fire_at"] > server_time, \
                    f"Alarm {alarm['id']} fire_at is not in the future"

    def test_flight_alarm_ids_are_unique(self):
        """Every alarm must have a distinct id."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        ids = [a["id"] for a in alarms]
        assert len(ids) == len(set(ids))

    def test_flight_countdown_ids_include_value(self):
        """Countdown alarm IDs must encode the countdown value: heat-N-COUNTDOWN-n."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        countdown_ids = [a["id"] for a in alarms if a["type"] == "COUNTDOWN"]
        # Should contain -10 through -1
        for n in range(1, 11):
            assert any(f"-COUNTDOWN-{n}" in aid for aid in countdown_ids), \
                f"COUNTDOWN-{n} missing from alarm IDs"

    def test_flight_countdown_ordered_by_fire_at(self):
        """Countdown alarms arrive in ascending fire_at order (10s first, 1s last)."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        countdown = [a for a in alarms if a["type"] == "COUNTDOWN"]
        fire_ats = [a["fire_at"] for a in countdown]
        assert fire_ats == sorted(fire_ats)

    def test_flight_flight_end_is_last_alarm(self):
        """FLIGHT_END must have the latest fire_at of all alarms."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        if not alarms:
            return
        max_fire = max(a["fire_at"] for a in alarms)
        flight_end = next(a for a in alarms if a["type"] == "FLIGHT_END")
        assert flight_end["fire_at"] == max_fire


# --------------------------------------------------------------------------- #
# Short flight (< WARNING_AT_SEC and < COUNTDOWN_FROM)                        #
# --------------------------------------------------------------------------- #

class TestBuzzerShortFlight:

    def test_no_warning_30_when_flight_too_short(self):
        """Flight of 20s has no time for WARNING_30 (fires at -30s = past)."""
        _create_and_start(flight_sec=20, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        types = [a["type"] for a in client.get("/api/buzzer").json()["alarms"]]
        assert "FLIGHT_WARNING_30" not in types

    def test_partial_countdown_when_flight_short(self):
        """Flight of 8s: only countdown 7 → 1 are in the future."""
        _create_and_start(flight_sec=8, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        countdown_alarms = [a for a in alarms if a["type"] == "COUNTDOWN"]
        # At most 7 countdown alarms (8s - ~0.3s elapsed = ~7.7s left → n=7..1)
        assert len(countdown_alarms) <= 7

    def test_no_flight_alarms_after_session_stop(self):
        """After session is explicitly stopped, phase is IDLE and no alarms."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        client.post("/api/session/stop")
        r = client.get("/api/buzzer")
        assert r.json()["phase"] == "IDLE"
        assert r.json()["alarms"] == []


# --------------------------------------------------------------------------- #
# Paused session                                                               #
# --------------------------------------------------------------------------- #

class TestBuzzerPaused:

    def test_paused_session_has_no_new_alarms(self):
        """When session is paused, no COUNTDOWN/FLIGHT_END alarms are emitted."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        client.post("/api/session/pause")
        data = client.get("/api/buzzer").json()
        types = [a["type"] for a in data["alarms"]]
        assert "COUNTDOWN" not in types
        assert "FLIGHT_END" not in types
        assert "FLIGHT_WARNING_30" not in types

    def test_paused_session_phase_is_flight(self):
        """Phase during pause should reflect the paused phase (FLIGHT)."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        client.post("/api/session/pause")
        phase = client.get("/api/buzzer").json()["phase"]
        assert phase == "FLIGHT"


# --------------------------------------------------------------------------- #
# Alarm schema regression                                                      #
# --------------------------------------------------------------------------- #

class TestBuzzerAlarmSchema:

    def test_every_alarm_has_id_type_fire_at(self):
        """Each alarm object must contain id, type, and fire_at fields."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        for alarm in alarms:
            assert "id" in alarm, f"Missing 'id' in {alarm}"
            assert "type" in alarm, f"Missing 'type' in {alarm}"
            assert "fire_at" in alarm, f"Missing 'fire_at' in {alarm}"

    def test_fire_at_is_iso8601_utc(self):
        """fire_at must be an ISO-8601 string ending with Z."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        for alarm in alarms:
            assert alarm["fire_at"].endswith("Z"), \
                f"fire_at {alarm['fire_at']} is not UTC (missing Z)"

    def test_alarm_id_contains_heat_number(self):
        """Alarm IDs must contain the heat number to allow per-session dedup."""
        _create_and_start(flight_sec=120, prep_sec=2)
        _advance_to_flight(prep_sec=2)
        alarms = client.get("/api/buzzer").json()["alarms"]
        for alarm in alarms:
            assert "heat-" in alarm["id"], \
                f"Alarm ID '{alarm['id']}' does not contain 'heat-'"

    def test_response_shape_is_complete(self):
        """Top-level response must contain all required fields."""
        r = client.get("/api/buzzer")
        data = r.json()
        for field in ("status", "server_time", "phase", "poll_interval_sec", "alarms"):
            assert field in data, f"Missing field '{field}' in response"
