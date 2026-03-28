"""
Wspólna konfiguracja testów i fixtures dla WRMS test suite.

Izolacja bazy danych:
  Zmienna środowiskowa WRMS_DB_PATH jest ustawiana na tymczasowy plik
  PRZED importem aplikacji. Dzięki temu database.py tworzy db_instance
  wskazujący na bazę testową, a produkcyjna data/race_system.db pozostaje
  niezmieniona przez cały czas trwania testów.

Izolacja stanu sesji:
  Fixture reset_session (autouse) zeruje in-memory globalny stan sesji
  przed i po każdym teście.
"""
import sys
import os
import time
import tempfile
import atexit
import pytest

# ---------------------------------------------------------------------------
# Krok 1: ustaw ścieżkę testowej bazy PRZED jakimkolwiek importem aplikacji
# ---------------------------------------------------------------------------
_db_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="wrms_test_")
os.close(_db_fd)
os.remove(_TEST_DB_PATH)          # usuń pusty plik — RaceDatabase go odtworzy
os.environ["WRMS_DB_PATH"] = _TEST_DB_PATH
# Bypass authentication in all tests by default.
# test_auth.py uses monkeypatch.delenv("WRMS_SKIP_AUTH") to test real auth.
os.environ["WRMS_SKIP_AUTH"] = "1"


def _cleanup_test_db():
    """Usuwa pliki testowej bazy po zakończeniu sesji testowej."""
    for suffix in ["", "-shm", "-wal"]:
        path = _TEST_DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)


atexit.register(_cleanup_test_db)

# ---------------------------------------------------------------------------
# Krok 2: importy aplikacji (już z podmienionym env var)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app                    # noqa: E402
from session import set_session         # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


def uid() -> str:
    """Unikalny suffix oparty na czasie (nanosekudy)."""
    return str(time.time_ns())


# ---------------------------------------------------------------------------
# Izolacja stanu sesji między testami
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_session():
    """Zeruje globalny stan sesji przed i po każdym teście."""
    set_session(None)
    yield
    set_session(None)


# ---------------------------------------------------------------------------
# Fixtures pomocnicze
# ---------------------------------------------------------------------------

@pytest.fixture
def make_pilot():
    """Fabryka pilotów. Zwraca (pilot_id, name)."""
    def _create(name: str = None, country: str = "PL") -> tuple[int, str]:
        n = name or f"Pilot_{uid()}"
        resp = client.post("/api/pilot/", json={"name": n, "country": country})
        assert resp.status_code == 200, f"Nie udało się stworzyć pilota: {resp.json()}"
        assert resp.json()["status"] == "ok"
        return resp.json()["id"], n
    return _create


@pytest.fixture
def new_session():
    """Tworzy świeżą sesję (60s lotu / 30s prep) i zwraca jej dane."""
    resp = client.post("/api/session", json={
        "name": f"Session_{uid()}",
        "flight_duration_sec": 60,
        "prep_duration_sec": 30,
    })
    assert resp.status_code == 200
    return resp.json()["session"]


@pytest.fixture
def short_session():
    """Sesja z bardzo krótkim timerem (2s) — do testów maszyny stanów."""
    resp = client.post("/api/session", json={
        "name": f"ShortSession_{uid()}",
        "flight_duration_sec": 2,
        "prep_duration_sec": 2,
    })
    assert resp.status_code == 200
    return resp.json()["session"]


@pytest.fixture
def session_with_pilots(new_session, make_pilot):
    """
    Sesja z 4 pilotami (2x Analog, 2x DJI) po rebalansie.
    Zwraca (session_data, [{"id", "name", "vtx"}, ...]).
    """
    configs = [
        ("Analog", f"Ana1_{uid()}"),
        ("Analog", f"Ana2_{uid()}"),
        ("DJI",    f"Dji1_{uid()}"),
        ("DJI",    f"Dji2_{uid()}"),
    ]
    pilots = []
    for vtx, name in configs:
        pid, pname = make_pilot(name=name)
        r = client.post("/api/session/add_pilot", json={"pilot_id": pid, "vtx": vtx})
        assert r.status_code == 200
        pilots.append({"id": pid, "name": pname, "vtx": vtx})

    client.post("/api/groups/rebalance", json={})
    return new_session, pilots


@pytest.fixture
def started_session(session_with_pilots):
    """Sesja z pilotami i uruchomionym cyklem treningowym."""
    session, pilots = session_with_pilots
    r = client.post("/api/session/start")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    return session, pilots
