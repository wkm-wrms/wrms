"""
Testy zarządzania grupami i algorytmu matchmakingu.
Pokrycie: Req 3.1 (algorytm podziału), UC8 (ręczna modyfikacja grup).
"""
import pytest
from conftest import client, uid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def add_n_pilots(n: int, vtx: str = "Analog") -> list[int]:
    """Tworzy n pilotów i dodaje ich do aktywnej sesji. Zwraca listę pilot_id."""
    ids = []
    for _ in range(n):
        name = f"P_{uid()}"
        pid = client.post("/api/pilot/", json={"name": name}).json()["id"]
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": vtx})
        ids.append(pid)
    return ids


def get_groups():
    return client.get("/api/session").json()["session"]["groups"]


def get_all_assigned_pilot_ids() -> set[int]:
    """Zwraca zbiór pilot_id przypisanych do jakiegokolwiek kanału w grupach."""
    assigned = set()
    for g in get_groups():
        for slot in g["channels"].values():
            if slot:
                assigned.add(slot["pilot_id"])
    return assigned


# ---------------------------------------------------------------------------
# Req 3.1: Algorytm podziału na grupy
# ---------------------------------------------------------------------------

class TestRebalanceGroupSizes:

    def test_4_pilots_creates_1_group(self, new_session):
        add_n_pilots(4)
        client.post("/api/groups/rebalance", json={})
        assert len(get_groups()) == 1

    def test_4_pilots_group_has_4_slots(self, new_session):
        add_n_pilots(4)
        client.post("/api/groups/rebalance", json={})
        groups = get_groups()
        assert len(groups[0]["channels"]) == 4

    def test_8_pilots_creates_2_groups(self, new_session):
        add_n_pilots(8)
        client.post("/api/groups/rebalance", json={})
        assert len(get_groups()) == 2

    def test_8_pilots_groups_balanced_4_4(self, new_session):
        add_n_pilots(8)
        client.post("/api/groups/rebalance", json={})
        sizes = [len(g["channels"]) for g in get_groups()]
        assert sizes == [4, 4]

    def test_5_pilots_creates_2_groups(self, new_session):
        """Req 3.1.1: 5 pilotów bez low_band → podział na 2 grupy (3+2)."""
        add_n_pilots(5)
        client.post("/api/groups/rebalance", json={})
        assert len(get_groups()) == 2

    def test_5_pilots_split_3_2(self, new_session):
        """Req 3.1.1: Podział 5 pilotów to 3+2, nie 4+1."""
        add_n_pilots(5)
        client.post("/api/groups/rebalance", json={})
        sizes = sorted([len(g["channels"]) for g in get_groups()], reverse=True)
        assert sizes == [3, 2]

    def test_all_active_pilots_assigned_after_rebalance(self, new_session):
        ids = add_n_pilots(6)
        client.post("/api/groups/rebalance", json={})
        assigned = get_all_assigned_pilot_ids()
        for pid in ids:
            assert pid in assigned

    def test_rebalance_with_zero_pilots_creates_no_groups(self, new_session):
        client.post("/api/groups/rebalance", json={})
        assert get_groups() == []


class TestRebalanceChannelAssignment:

    def test_analog_pilots_get_low_channels(self, new_session):
        """Req 3.1.3: Piloci analogowi dostają niskie kanały (R1, R3)."""
        LOW_CHANNELS = {"R1", "R3"}
        add_n_pilots(2, vtx="Analog")
        add_n_pilots(2, vtx="DJI")
        client.post("/api/groups/rebalance", json={})

        groups = get_groups()
        for g in groups:
            for channel, slot in g["channels"].items():
                if slot and not slot["is_digital"]:
                    assert channel in LOW_CHANNELS, (
                        f"Pilot analogowy na kanale {channel}, oczekiwano {LOW_CHANNELS}"
                    )

    def test_digital_pilots_get_high_channels(self, new_session):
        """Req 3.1.3: Piloci cyfrowi dostają wysokie kanały (R6, R7)."""
        HIGH_CHANNELS = {"R6", "R7"}
        add_n_pilots(2, vtx="Analog")
        add_n_pilots(2, vtx="DJI")
        client.post("/api/groups/rebalance", json={})

        groups = get_groups()
        for g in groups:
            for channel, slot in g["channels"].items():
                if slot and slot["is_digital"]:
                    assert channel in HIGH_CHANNELS, (
                        f"Pilot cyfrowy na kanale {channel}, oczekiwano {HIGH_CHANNELS}"
                    )

    def test_channels_unique_within_group(self, new_session):
        """Każdy kanał w grupie jest zajęty przez co najwyżej jednego pilota."""
        add_n_pilots(4)
        client.post("/api/groups/rebalance", json={})
        for g in get_groups():
            assigned = [v["pilot_id"] for v in g["channels"].values() if v]
            assert len(assigned) == len(set(assigned))

    def test_pilot_assigned_to_exactly_one_channel(self, new_session):
        """Pilot pojawia się maksymalnie raz w całym harmonogramie po rebalansie."""
        ids = add_n_pilots(4)
        client.post("/api/groups/rebalance", json={})
        all_pilot_ids = []
        for g in get_groups():
            all_pilot_ids += [v["pilot_id"] for v in g["channels"].values() if v]
        assert len(all_pilot_ids) == len(set(all_pilot_ids))


# ---------------------------------------------------------------------------
# UC8: Ręczna modyfikacja grup
# ---------------------------------------------------------------------------

class TestGroupCRUD:

    def test_add_new_group(self, new_session):
        resp = client.post("/api/groups/new")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert len(get_groups()) == 1

    def test_add_multiple_groups(self, new_session):
        client.post("/api/groups/new")
        client.post("/api/groups/new")
        assert len(get_groups()) == 2

    def test_delete_group(self, new_session):
        client.post("/api/groups/new")
        client.post("/api/groups/new")
        resp = client.post("/api/groups/delete", json={"group_sequence": 1})
        assert resp.json()["status"] == "ok"
        assert len(get_groups()) == 1

    def test_delete_nonexistent_group_returns_error(self, new_session):
        resp = client.post("/api/groups/delete", json={"group_sequence": 99})
        assert resp.json()["status"] == "error"

    def test_groups_endpoint_without_session_returns_error(self):
        resp = client.get("/api/groups")
        assert resp.json()["status"] == "error"

    def test_new_group_without_session_returns_error(self):
        resp = client.post("/api/groups/new")
        assert resp.json()["status"] == "error"


class TestMovePilot:

    def test_move_pilot_to_empty_slot(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/new")

        resp = client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "to_group": 1, "to_channel": "R1"
        })
        assert resp.json()["status"] == "ok"

        channels = get_groups()[0]["channels"]
        assert "R1" in channels
        assert channels["R1"]["pilot_id"] == pid

    def test_move_pilot_between_groups(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/new")
        client.post("/api/groups/new")
        client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "to_group": 1, "to_channel": "R1"
        })

        resp = client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "from_group": 1, "from_channel": "R1",
            "to_group": 2, "to_channel": "R3"
        })
        assert resp.json()["status"] == "ok"

        groups = get_groups()
        assert "R1" not in groups[0]["channels"] or groups[0]["channels"].get("R1") is None
        assert groups[1]["channels"]["R3"]["pilot_id"] == pid

    def test_move_pilot_collision_displaces_occupant(self, new_session, make_pilot):
        """UC8: Przeniesienie na zajęty slot 'wypycha' poprzedniego pilota do paddocka."""
        pid1, _ = make_pilot()
        pid2, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid1, "vtx": "Analog"})
        client.post("/api/session/add_pilot", json={"pilot_id": pid2, "vtx": "Analog"})
        client.post("/api/groups/new")
        client.post("/api/groups/move_pilot", json={
            "pilot_id": pid1, "to_group": 1, "to_channel": "R1"
        })

        client.post("/api/groups/move_pilot", json={
            "pilot_id": pid2, "to_group": 1, "to_channel": "R1"
        })

        channels = get_groups()[0]["channels"]
        assert channels["R1"]["pilot_id"] == pid2
        assert not any(v and v["pilot_id"] == pid1 for v in channels.values())

    def test_move_pilot_to_paddock(self, new_session, make_pilot):
        """Przeniesienie do paddocka (to_group=None) usuwa z grupy."""
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/new")
        client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "to_group": 1, "to_channel": "R1"
        })

        resp = client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "from_group": 1, "from_channel": "R1"
        })
        assert resp.json()["status"] == "ok"

        channels = get_groups()[0]["channels"]
        assert "R1" not in channels or channels.get("R1") is None

    def test_move_inactive_pilot_returns_error(self, new_session):
        resp = client.post("/api/groups/move_pilot", json={
            "pilot_id": 9999999, "to_group": 1, "to_channel": "R1"
        })
        assert resp.json()["status"] == "error"

    def test_move_to_invalid_channel_returns_error(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/new")

        resp = client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "to_group": 1, "to_channel": "R9"
        })
        assert resp.json()["status"] == "error"

    def test_move_to_nonexistent_group_returns_error(self, new_session, make_pilot):
        pid, _ = make_pilot()
        client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})

        resp = client.post("/api/groups/move_pilot", json={
            "pilot_id": pid, "to_group": 99, "to_channel": "R1"
        })
        assert resp.json()["status"] == "error"


# ---------------------------------------------------------------------------
# Regression: GET /api/groups public access + current_group_index field
# Bug: groups_view.html called /api/session (admin-only) instead of /api/groups
# ---------------------------------------------------------------------------

class TestGroupsPublicEndpoint:

    def test_get_groups_returns_current_group_index(self, new_session):
        """GET /api/groups must include current_group_index for public schedule view."""
        resp = client.get("/api/groups")
        data = resp.json()
        assert data["status"] == "ok"
        assert "current_group_index" in data

    def test_get_groups_current_group_index_is_none_before_start(self, new_session):
        """current_group_index is None before the session starts (no heat running yet)."""
        resp = client.get("/api/groups")
        assert resp.json()["current_group_index"] is None

    def test_get_groups_no_session_returns_error(self):
        """Without an active session, /api/groups returns an error (no crash)."""
        resp = client.get("/api/groups")
        assert resp.json()["status"] == "error"

    def test_get_groups_current_group_index_advances_after_rotation(self, new_session, make_pilot):
        """current_group_index must increment after heat rotation (requires 2+ groups)."""
        # 5 pilots → 2 groups so there is a next group to rotate into
        for _ in range(5):
            pid, _ = make_pilot()
            client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": "Analog"})
        client.post("/api/groups/rebalance", json={})
        client.post("/api/session/start")

        before = client.get("/api/groups").json()["current_group_index"]
        client.post("/api/session/skip_heat")
        after = client.get("/api/groups").json()["current_group_index"]
        assert after == before + 1
