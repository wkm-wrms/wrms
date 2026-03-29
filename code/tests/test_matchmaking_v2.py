"""
Tests for Matchmaking 2.0 — digital-first grouping and score-based channel assignment.

Covers:
  - total_score() on ActivePilot
  - digital-first group distribution
  - score-based channel assignment within group
  - regression: existing analog/digital channel rules still hold
"""
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from conftest import client, uid  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pilot(name: str = None, risk_factor: int = 3) -> int:
    """Create a pilot and return its id."""
    n = name or f"P_{uid()}"
    resp = client.post("/api/pilot/", json={"name": n, "risk_factor": risk_factor})
    assert resp.status_code == 200
    return resp.json()["id"]


def add_to_session(pilot_id: int, vtx: str):
    r = client.post("/api/session/add_pilot", json={"pilot_id": pilot_id, "vtx": vtx})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def rebalance() -> list[dict]:
    r = client.post("/api/groups/rebalance", json={})
    assert r.status_code == 200
    return r.json()["groups"]


def new_session():
    resp = client.post("/api/session", json={
        "name": f"S_{uid()}",
        "flight_duration_sec": 60,
        "prep_duration_sec": 30,
    })
    assert resp.status_code == 200
    return resp.json()["session"]


def channels_of(group: dict) -> dict[str, dict | None]:
    """Return {channel: slot_or_none} for a group."""
    return group["channels"]


def pilots_in(group: dict) -> list[dict]:
    """Return list of non-empty slots in a group."""
    return [v for v in group["channels"].values() if v is not None]


# ---------------------------------------------------------------------------
# Unit-style: total_score via API response (indirect)
# We verify score indirectly through channel ordering.
# Direct unit tests on ActivePilot.total_score() are below using imports.
# ---------------------------------------------------------------------------

class TestTotalScore:
    """Direct unit tests for ActivePilot.total_score()."""

    def test_analog_min_risk(self):
        """Analog + risk_factor=1 → score 2."""
        from activepilot import ActivePilot, VTX_POINTS
        from pilot import Pilot
        p = Pilot(pilot_id=1, name="X", risk_factor=1)
        ap = ActivePilot(p, "Analog")
        assert ap.total_score() == 2

    def test_hd0_max_risk(self):
        """HD0 + risk_factor=6 → score 11."""
        from activepilot import ActivePilot
        from pilot import Pilot
        p = Pilot(pilot_id=1, name="X", risk_factor=6)
        ap = ActivePilot(p, "HD0")
        assert ap.total_score() == 11

    def test_dji_mid_risk(self):
        """DJI + risk_factor=3 → score 7."""
        from activepilot import ActivePilot
        from pilot import Pilot
        p = Pilot(pilot_id=1, name="X", risk_factor=3)
        ap = ActivePilot(p, "DJI")
        assert ap.total_score() == 7

    def test_walksnail_mid_risk(self):
        """Walksnail + risk_factor=3 → score 7 (same as DJI)."""
        from activepilot import ActivePilot
        from pilot import Pilot
        p = Pilot(pilot_id=1, name="X", risk_factor=3)
        ap = ActivePilot(p, "Walksnail")
        assert ap.total_score() == 7

    def test_unknown_vtx_fallback(self):
        """Unknown vtx string → vision_points=1, is_digital=True."""
        from activepilot import ActivePilot
        from pilot import Pilot
        p = Pilot(pilot_id=1, name="X", risk_factor=4)
        ap = ActivePilot(p, "SomeFutureSystem")
        assert ap.total_score() == 5   # 1 (fallback) + 4
        assert ap.is_digital is True

    def test_vtx_points_table_values(self):
        """VTX_POINTS contains all canonical vtx values."""
        from activepilot import VTX_POINTS
        assert VTX_POINTS["Analog"] == 1
        assert VTX_POINTS["DJI"] == 4
        assert VTX_POINTS["Walksnail"] == 4
        assert VTX_POINTS["HD0"] == 5


# ---------------------------------------------------------------------------
# Digital-first grouping
# ---------------------------------------------------------------------------

class TestDigitalFirstGrouping:

    def test_6_pilots_3d_3a_creates_homogeneous_groups(self, new_session):
        """3 digital + 3 analog → Gr.1 all-digital, Gr.2 all-analog."""
        for _ in range(3):
            add_to_session(make_pilot(), "DJI")
        for _ in range(3):
            add_to_session(make_pilot(), "Analog")

        groups = rebalance()
        assert len(groups) == 2

        for g in groups:
            slots = pilots_in(g)
            types = {s["is_digital"] for s in slots}
            assert len(types) == 1, (
                f"Group {g['group_sequence']} is mixed: {[s['vtx'] for s in slots]}"
            )

    def test_5_pilots_3d_2a_creates_homogeneous_groups(self, new_session):
        """3 digital + 2 analog → Gr.1=[D,D,D], Gr.2=[A,A]."""
        for _ in range(3):
            add_to_session(make_pilot(), "HD0")
        for _ in range(2):
            add_to_session(make_pilot(), "Analog")

        groups = rebalance()
        assert len(groups) == 2

        gr1_pilots = pilots_in(groups[0])
        gr2_pilots = pilots_in(groups[1])
        assert all(s["is_digital"] for s in gr1_pilots), "Group 1 should be all-digital"
        assert all(not s["is_digital"] for s in gr2_pilots), "Group 2 should be all-analog"

    def test_7_pilots_4d_3a_creates_homogeneous_groups(self, new_session):
        """4 digital + 3 analog → Gr.1=[D,D,D,D], Gr.2=[A,A,A]."""
        for _ in range(4):
            add_to_session(make_pilot(), "DJI")
        for _ in range(3):
            add_to_session(make_pilot(), "Analog")

        groups = rebalance()
        assert len(groups) == 2

        assert all(s["is_digital"] for s in pilots_in(groups[0]))
        assert all(not s["is_digital"] for s in pilots_in(groups[1]))

    def test_6_pilots_2d_4a_minimises_mixed_groups(self, new_session):
        """2 digital + 4 analog → Gr.1 mixed, Gr.2 all-analog (best possible)."""
        for _ in range(2):
            add_to_session(make_pilot(), "DJI")
        for _ in range(4):
            add_to_session(make_pilot(), "Analog")

        groups = rebalance()
        assert len(groups) == 2

        # Both digital pilots must be in group 1 (not split across groups)
        digital_in_gr1 = sum(1 for s in pilots_in(groups[0]) if s["is_digital"])
        digital_in_gr2 = sum(1 for s in pilots_in(groups[1]) if s["is_digital"])
        assert digital_in_gr1 == 2
        assert digital_in_gr2 == 0

    def test_8_pilots_all_digital_two_groups(self, new_session):
        """8 digital → 2 groups of 4, both all-digital."""
        for _ in range(8):
            add_to_session(make_pilot(), "HD0")

        groups = rebalance()
        assert len(groups) == 2
        for g in groups:
            assert all(s["is_digital"] for s in pilots_in(g))


# ---------------------------------------------------------------------------
# Score-based channel assignment
# ---------------------------------------------------------------------------

class TestScoreBasedChannels:

    def test_all_digital_highest_score_gets_r7(self, new_session):
        """4 digital pilots: pilot with highest score must be on R7."""
        # risk_factors: 6, 4, 3, 1 → scores: 9, 8, 7, 6 (HD0=5 pts + risk) wait...
        # HD0=5, DJI=4. Use DJI for all to keep vision equal.
        # DJI+risk=6 → 10, DJI+risk=4 → 8, DJI+risk=2 → 6, DJI+risk=1 → 5
        p_high = make_pilot(risk_factor=6)
        p_mid2 = make_pilot(risk_factor=4)
        p_mid1 = make_pilot(risk_factor=2)
        p_low  = make_pilot(risk_factor=1)
        for pid in [p_high, p_mid2, p_mid1, p_low]:
            add_to_session(pid, "DJI")

        groups = rebalance()
        assert len(groups) == 1

        ch = channels_of(groups[0])
        assert ch["R7"] is not None
        assert ch["R7"]["pilot"]["pilot_id"] == p_high

    def test_all_digital_lowest_score_gets_r1(self, new_session):
        """4 digital pilots: pilot with lowest score must be on R1."""
        p_high = make_pilot(risk_factor=6)
        p_mid2 = make_pilot(risk_factor=4)
        p_mid1 = make_pilot(risk_factor=2)
        p_low  = make_pilot(risk_factor=1)
        for pid in [p_high, p_mid2, p_mid1, p_low]:
            add_to_session(pid, "DJI")

        groups = rebalance()
        ch = channels_of(groups[0])
        assert ch["R1"]["pilot"]["pilot_id"] == p_low

    def test_all_analog_highest_score_gets_r7(self, new_session):
        """4 analog pilots: pilot with highest score must be on R7."""
        p_high = make_pilot(risk_factor=6)
        p_low  = make_pilot(risk_factor=1)
        p_mid1 = make_pilot(risk_factor=2)
        p_mid2 = make_pilot(risk_factor=4)
        for pid in [p_high, p_low, p_mid1, p_mid2]:
            add_to_session(pid, "Analog")

        groups = rebalance()
        ch = channels_of(groups[0])
        assert ch["R7"]["pilot"]["pilot_id"] == p_high

    def test_mixed_2d_2a_channel_separation(self, new_session):
        """2 digital + 2 analog: digital on R6/R7, analog on R1/R3.

        Within each tier: higher score → higher channel.
        Analog fills from R1 upward (asc order) → a_high on R3, a_low on R1.
        Digital fills from R7 downward (desc order) → d_high on R7, d_low on R6.
        """
        d_high = make_pilot(risk_factor=6)
        d_low  = make_pilot(risk_factor=1)
        a_high = make_pilot(risk_factor=5)
        a_low  = make_pilot(risk_factor=2)
        add_to_session(d_high, "DJI")
        add_to_session(d_low,  "DJI")
        add_to_session(a_high, "Analog")
        add_to_session(a_low,  "Analog")

        groups = rebalance()
        assert len(groups) == 1
        ch = channels_of(groups[0])

        # Digital: highest score → R7, lower → R6
        assert ch["R7"]["pilot"]["pilot_id"] == d_high
        assert ch["R6"]["pilot"]["pilot_id"] == d_low
        # Analog: highest score → R3 (top of analog tier), lower → R1
        assert ch["R3"]["pilot"]["pilot_id"] == a_high
        assert ch["R1"]["pilot"]["pilot_id"] == a_low

    def test_mixed_3d_1a_analog_gets_r1(self, new_session):
        """3 digital + 1 analog: analog always on R1 (lowest channel)."""
        a = make_pilot(risk_factor=6)   # high score but still analog
        for _ in range(3):
            add_to_session(make_pilot(risk_factor=1), "DJI")
        add_to_session(a, "Analog")

        groups = rebalance()
        ch = channels_of(groups[0])
        assert ch["R1"]["pilot"]["pilot_id"] == a
        assert ch["R1"]["is_digital"] is False

    def test_mixed_1d_3a_digital_gets_r7(self, new_session):
        """1 digital + 3 analog: digital always on R7 (highest channel)."""
        d = make_pilot(risk_factor=1)   # low score but still digital
        for _ in range(3):
            add_to_session(make_pilot(risk_factor=6), "Analog")
        add_to_session(d, "DJI")

        groups = rebalance()
        ch = channels_of(groups[0])
        assert ch["R7"]["pilot"]["pilot_id"] == d
        assert ch["R7"]["is_digital"] is True

    def test_score_tie_all_assigned(self, new_session):
        """Pilots with equal score: no crash, all channels assigned."""
        for _ in range(4):
            add_to_session(make_pilot(risk_factor=3), "DJI")

        groups = rebalance()
        ch = channels_of(groups[0])
        assigned = [v for v in ch.values() if v is not None]
        assert len(assigned) == 4

    def test_walksnail_treated_as_digital(self, new_session):
        """Walksnail pilot is treated as digital (gets high channel in mixed group)."""
        ws = make_pilot(risk_factor=3)
        a  = make_pilot(risk_factor=3)
        add_to_session(ws, "Walksnail")
        add_to_session(a, "Analog")

        groups = rebalance()
        ch = channels_of(groups[0])
        # Walksnail should be on a high channel (R6 or R7)
        ws_channel = next(k for k, v in ch.items() if v and v["pilot"]["pilot_id"] == ws)
        assert ws_channel in ("R6", "R7")

    def test_hd0_outscores_dji_same_risk(self, new_session):
        """HD0 pilot scores higher than DJI pilot with same risk_factor → higher channel."""
        hd = make_pilot(risk_factor=3)   # HD0=5+3=8
        dj = make_pilot(risk_factor=3)   # DJI=4+3=7
        add_to_session(hd, "HD0")
        add_to_session(dj, "DJI")

        groups = rebalance()
        ch = channels_of(groups[0])
        assert ch["R7"]["pilot"]["pilot_id"] == hd
        assert ch["R6"]["pilot"]["pilot_id"] == dj


# ---------------------------------------------------------------------------
# Regression: existing tests must still pass
# ---------------------------------------------------------------------------

class TestRegressionMatchmaking:

    def test_analog_pilots_stay_on_low_channels(self, new_session):
        """Analog pilots always on R1/R3 in a mixed group."""
        LOW = {"R1", "R3"}
        add_to_session(make_pilot(), "Analog")
        add_to_session(make_pilot(), "Analog")
        add_to_session(make_pilot(), "DJI")
        add_to_session(make_pilot(), "DJI")

        groups = rebalance()
        for g in groups:
            for ch, slot in g["channels"].items():
                if slot and not slot["is_digital"]:
                    assert ch in LOW, f"Analog pilot on {ch}, expected {LOW}"

    def test_digital_pilots_stay_on_high_channels(self, new_session):
        """Digital pilots always on R6/R7 in a mixed group."""
        HIGH = {"R6", "R7"}
        add_to_session(make_pilot(), "Analog")
        add_to_session(make_pilot(), "Analog")
        add_to_session(make_pilot(), "DJI")
        add_to_session(make_pilot(), "DJI")

        groups = rebalance()
        for g in groups:
            for ch, slot in g["channels"].items():
                if slot and slot["is_digital"]:
                    assert ch in HIGH, f"Digital pilot on {ch}, expected {HIGH}"

    def test_5_pilots_creates_2_groups_3_plus_2(self, new_session):
        """5 pilots → 2 groups sized 3+2."""
        for _ in range(5):
            add_to_session(make_pilot(), "Analog")

        groups = rebalance()
        sizes = sorted([len(pilots_in(g)) for g in groups], reverse=True)
        assert sizes == [3, 2]

    def test_4_pilots_single_group(self, new_session):
        """4 pilots → 1 group of 4."""
        for _ in range(4):
            add_to_session(make_pilot(), "DJI")

        groups = rebalance()
        assert len(groups) == 1
        assert len(pilots_in(groups[0])) == 4

    def test_8_pilots_two_groups_of_4(self, new_session):
        """8 pilots → 2 groups of 4."""
        for _ in range(8):
            add_to_session(make_pilot(), "Analog")

        groups = rebalance()
        assert len(groups) == 2
        for g in groups:
            assert len(pilots_in(g)) == 4
