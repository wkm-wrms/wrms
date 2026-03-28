import sys
import os
import time
from fastapi.testclient import TestClient

# Dynamiczne dodanie katalogu nadrzędnego (code/) do ścieżki wyszukiwania modułów.
# Pozwala to na uruchomienie testów z dowolnego miejsca i poprawny import 'main'.
# Musi to być wykonane PRZED importem 'main'.
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..')))

if True:
    from main import app


client = TestClient(app)


def test_full_pilot_lifecycle():
    """Weryfikacja: Tworzenie -> Wyszukiwanie -> Dodawanie do sesji."""
    # 1. Tworzenie pilota
    pilot_name = f"TestPilot_{int(time.time())}"
    create_resp = client.post("/api/pilot", json={"name": pilot_name})
    assert create_resp.status_code == 200
    pilot_id = create_resp.json()["id"]

    # 2. Wyszukiwanie
    search_resp = client.get(f"/api/pilot/search/{pilot_name}")
    assert any(p["pilot_id"] == pilot_id for p in search_resp.json()["pilots"])

    # 3. Przygotowanie sesji i dodanie pilota
    client.post("/api/session", json={"name": "Test",
                "flight_duration_sec": 10, "prep_duration_sec": 10})
    add_resp = client.post("/api/session/add_pilot",
                           json={"pilot_id": pilot_id, "vtx": "Analog"})
    assert add_resp.status_code == 200

    # Sprawdzenie czy pilot jest w sesji
    session_resp = client.get("/api/session")
    assert str(pilot_id) in session_resp.json()["session"]["active_pilots"]


def test_session_creation_and_validation():
    """Weryfikacja: Poprawność parametrów sesji."""
    session_name = "Mistrzostwa Truskawia"
    payload = {"name": session_name,
               "flight_duration_sec": 600, "prep_duration_sec": 120}
    client.post("/api/session", json=payload)

    resp = client.get("/api/session")
    data = resp.json()["session"]
    assert data["name"] == session_name
    assert data["flight_duration_sec"] == 600


def test_heat_rotation_and_skip():
    """Weryfikacja: Czy skip_heat faktycznie rotuje biegi i grupy."""
    # Setup: Sesja z dwoma pilotami w dwóch grupach
    client.post("/api/session", json={"name": "RotationTest",
                "flight_duration_sec": 60, "prep_duration_sec": 60})

    ts = int(time.time() * 1000)
    name1, name2 = f"P1_{ts}", f"P2_{ts}"
    resp1 = client.post("/api/pilot", json={"name": name1})
    resp2 = client.post("/api/pilot", json={"name": name2})
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    p1, p2 = resp1.json()["id"], resp2.json()["id"]

    client.post("/api/session/add_pilot",
                json={"pilot_id": p1, "vtx": "Analog"})
    client.post("/api/session/add_pilot",
                json={"pilot_id": p2, "vtx": "Analog"})

    # Rebalance do 2 grup (ręcznie wymuszamy mały limit w teście lub po prostu move)
    assert client.post("/api/groups/new").status_code == 200
    assert client.post("/api/groups/new").status_code == 200
    client.post("/api/groups/move_pilot",
                json={"pilot_id": p1, "to_group": 1, "to_channel": "R1"})
    client.post("/api/groups/move_pilot",
                json={"pilot_id": p2, "to_group": 2, "to_channel": "R1"})

    client.post("/api/session/start")

    # Sprawdzamy startowy bieg (powinien być P1)
    heat1 = client.get("/api/heat").json()["heat"]
    assert heat1["heat_number"] == 1
    assert heat1["channels"]["R1"]["pilot"]["name"] == name1

    # Skip
    skip_resp = client.post("/api/session/skip_heat")
    assert skip_resp.status_code == 200

    # Sprawdzamy nowy bieg (powinien być P2)
    heat2 = client.get("/api/heat").json()["heat"]
    assert heat2["heat_number"] == 2
    assert heat2["channels"]["R1"]["pilot"]["name"] == name2


def test_timer_accuracy():
    """Weryfikacja: Czy live_seconds_left zmniejsza się proporcjonalnie do czasu rzeczywistego."""
    client.post("/api/session", json={"name": "TimerTest",
                "flight_duration_sec": 100, "prep_duration_sec": 100})

    resp = client.post(
        "/api/pilot", json={"name": f"TimerPilot_{int(time.time()*1000)}"})
    assert resp.status_code == 200
    p1 = resp.json()["id"]
    client.post("/api/session/add_pilot",
                json={"pilot_id": p1, "vtx": "Analog"})
    client.post("/api/groups/move_pilot",
                json={"pilot_id": p1, "to_group": 1, "to_channel": "R1"})
    assert client.post("/api/session/start").status_code == 200

    # Pierwszy pomiar
    t1_resp = client.get("/api/heat").json()["heat"]["live_seconds_left"]
    start_wall = time.time()

    # Czekamy 2 sekundy
    time.sleep(2)

    # Drugi pomiar
    t2_resp = client.get("/api/heat").json()["heat"]["live_seconds_left"]
    end_wall = time.time()

    elapsed_wall = end_wall - start_wall
    elapsed_api = t1_resp - t2_resp

    # Tolerancja 0.2s na opóźnienia sieciowe/przetwarzanie
    assert abs(elapsed_api - elapsed_wall) < 0.2
    assert t2_resp < t1_resp


def test_move_pilot_collision():
    """Weryfikacja: Czy pilot spada do paddocku przy kolizji."""
    client.post("/api/session", json={"name": "Collision",
                "flight_duration_sec": 60, "prep_duration_sec": 60})

    ts = int(time.time() * 1000)
    resp1 = client.post("/api/pilot", json={"name": f"Target_{ts}"})
    resp2 = client.post("/api/pilot", json={"name": f"Attacker_{ts}"})
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    p1, p2 = resp1.json()["id"], resp2.json()["id"]

    client.post("/api/session/add_pilot",
                json={"pilot_id": p1, "vtx": "Analog"})
    client.post("/api/session/add_pilot",
                json={"pilot_id": p2, "vtx": "Analog"})

    # Utworzenie grupy, aby było gdzie przenosić pilotów
    client.post("/api/groups/new")

    # P1 -> G1 R1
    client.post("/api/groups/move_pilot",
                json={"pilot_id": p1, "to_group": 1, "to_channel": "R1"})
    # P2 -> G1 R1 (Wypycha P1)
    client.post("/api/groups/move_pilot",
                json={"pilot_id": p2, "to_group": 1, "to_channel": "R1"})

    session = client.get("/api/session").json()["session"]
    # P1 nie powinien być w żadnym kanale grupy 1
    channels = session["groups"][0]["channels"]
    assert channels["R1"]["pilot_id"] == p2
    assert not any(v and v["pilot_id"] == p1 for v in channels.values())
