"""
Functional tests for admin authentication (login, logout, me, register,
set_password, list, remove) and protected endpoint enforcement.

These tests remove WRMS_SKIP_AUTH so that real authentication is exercised.
Each test function gets a fresh TestClient (new cookie jar) and a clean
admin state via the clean_admins fixture.
"""
import pytest
from fastapi.testclient import TestClient

# Import the app after conftest has already set WRMS_DB_PATH
from main import app  # noqa: E402
from database import get_db  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def enable_auth(monkeypatch):
    """Remove WRMS_SKIP_AUTH so authentication is enforced in every test here."""
    monkeypatch.delenv("WRMS_SKIP_AUTH", raising=False)


@pytest.fixture()
def clean_admins():
    """Delete all admin accounts and sessions before and after each test."""
    db = get_db()
    with db._get_conn() as conn:  # pylint: disable=protected-access
        conn.execute("DELETE FROM admin_session")
        conn.execute("DELETE FROM user")
        conn.commit()
    yield
    with db._get_conn() as conn:  # pylint: disable=protected-access
        conn.execute("DELETE FROM admin_session")
        conn.execute("DELETE FROM user")
        conn.commit()


@pytest.fixture()
def auth_client(clean_admins):
    """Fresh TestClient with real auth; no admins in the DB."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def logged_in_client(clean_admins):
    """
    TestClient with one admin pre-registered and already logged in.
    Yields (client, username, password).
    """
    with TestClient(app) as c:
        username, password = "mc_admin", "secret123"
        r = c.post("/api/admin/register", json={"username": username, "password": password})
        assert r.json()["status"] == "ok"
        r = c.post("/api/admin/login", json={"username": username, "password": password})
        assert r.json()["status"] == "ok"
        yield c, username, password


# ---------------------------------------------------------------------------
# GET /api/admin/me — unauthenticated states
# ---------------------------------------------------------------------------

def test_me_no_admins_returns_first_setup(auth_client):
    """When user table is empty, me returns first_setup=True."""
    r = auth_client.get("/api/admin/me")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "error"
    assert data["first_setup"] is True


def test_me_admins_exist_but_not_logged_in(auth_client):
    """When admins exist but no valid cookie, first_setup is False."""
    db = get_db()
    db.add_admin("existing_admin", "pw")
    r = auth_client.get("/api/admin/me")
    data = r.json()
    assert data["status"] == "error"
    assert data["first_setup"] is False


# ---------------------------------------------------------------------------
# POST /api/admin/register — first-time setup and auth-gated
# ---------------------------------------------------------------------------

def test_register_first_admin_succeeds(auth_client):
    """First registration requires no authentication."""
    r = auth_client.post("/api/admin/register",
                         json={"username": "admin1", "password": "pass1"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["username"] == "admin1"


def test_register_second_admin_requires_auth(auth_client):
    """Second registration requires an authenticated session."""
    # Register the first admin
    auth_client.post("/api/admin/register",
                     json={"username": "admin1", "password": "pass1"})
    # Try to register a second without logging in
    r = auth_client.post("/api/admin/register",
                         json={"username": "admin2", "password": "pass2"})
    assert r.json()["status"] == "error"
    assert "Authentication required" in r.json()["message"]


def test_register_second_admin_with_auth(auth_client):
    """Second registration succeeds when caller is authenticated."""
    auth_client.post("/api/admin/register",
                     json={"username": "admin1", "password": "pass1"})
    auth_client.post("/api/admin/login",
                     json={"username": "admin1", "password": "pass1"})
    r = auth_client.post("/api/admin/register",
                         json={"username": "admin2", "password": "pass2"})
    assert r.json()["status"] == "ok"


def test_register_duplicate_username_fails(auth_client):
    """Registering with an existing username returns an error."""
    auth_client.post("/api/admin/register",
                     json={"username": "admin1", "password": "pass1"})
    auth_client.post("/api/admin/login",
                     json={"username": "admin1", "password": "pass1"})
    r = auth_client.post("/api/admin/register",
                         json={"username": "admin1", "password": "other"})
    assert r.json()["status"] == "error"
    assert "already exists" in r.json()["message"]


# ---------------------------------------------------------------------------
# POST /api/admin/login
# ---------------------------------------------------------------------------

def test_login_valid_credentials_sets_cookie(auth_client):
    """Successful login returns ok and sets a session_token cookie."""
    auth_client.post("/api/admin/register",
                     json={"username": "mc", "password": "pw"})
    r = auth_client.post("/api/admin/login",
                         json={"username": "mc", "password": "pw"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "session_token" in r.cookies


def test_login_invalid_password_fails(auth_client):
    """Wrong password returns an error and no cookie is set."""
    auth_client.post("/api/admin/register",
                     json={"username": "mc", "password": "pw"})
    r = auth_client.post("/api/admin/login",
                         json={"username": "mc", "password": "wrong"})
    assert r.json()["status"] == "error"
    assert "session_token" not in r.cookies


def test_login_unknown_user_fails(auth_client):
    """Unknown username returns an error."""
    r = auth_client.post("/api/admin/login",
                         json={"username": "nobody", "password": "pw"})
    assert r.json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/admin/me — authenticated state
# ---------------------------------------------------------------------------

def test_me_after_login_returns_username(logged_in_client):
    """me returns ok with username after successful login."""
    client, username, _ = logged_in_client
    r = client.get("/api/admin/me")
    assert r.json()["status"] == "ok"
    assert r.json()["username"] == username


# ---------------------------------------------------------------------------
# POST /api/admin/logout
# ---------------------------------------------------------------------------

def test_logout_clears_session(logged_in_client):
    """After logout, me no longer recognises the session."""
    client, _, _ = logged_in_client
    client.post("/api/admin/logout")
    r = client.get("/api/admin/me")
    assert r.json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /api/admin/set_password
# ---------------------------------------------------------------------------

def test_set_password_changes_credentials(logged_in_client):
    """set_password allows login with the new password only."""
    client, username, old_pw = logged_in_client
    r = client.post("/api/admin/set_password",
                    json={"username": username, "new_password": "newpass"})
    assert r.json()["status"] == "ok"

    # Old password no longer works
    with TestClient(app) as fresh:
        r = fresh.post("/api/admin/login",
                       json={"username": username, "password": old_pw})
        assert r.json()["status"] == "error"

    # New password works
    with TestClient(app) as fresh:
        r = fresh.post("/api/admin/login",
                       json={"username": username, "password": "newpass"})
        assert r.json()["status"] == "ok"


def test_set_password_unknown_user_fails(logged_in_client):
    """set_password returns error for a non-existent username."""
    client, _, _ = logged_in_client
    r = client.post("/api/admin/set_password",
                    json={"username": "nobody", "new_password": "pw"})
    assert r.json()["status"] == "error"


def test_set_password_requires_auth(auth_client):
    """set_password returns 401 without a valid session."""
    r = auth_client.post("/api/admin/set_password",
                         json={"username": "mc", "new_password": "pw"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/admin/list
# ---------------------------------------------------------------------------

def test_list_admins_returns_accounts(logged_in_client):
    """list returns the registered admins without password hashes."""
    client, username, _ = logged_in_client
    r = client.get("/api/admin/list")
    assert r.json()["status"] == "ok"
    usernames = [a["username"] for a in r.json()["admins"]]
    assert username in usernames
    for admin in r.json()["admins"]:
        assert "password_hash" not in admin


def test_list_admins_requires_auth(auth_client):
    """list returns 401 without a valid session."""
    r = auth_client.get("/api/admin/list")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/admin/remove
# ---------------------------------------------------------------------------

def test_remove_other_admin(logged_in_client):
    """An admin can remove another admin account."""
    client, _, _ = logged_in_client
    client.post("/api/admin/register",
                json={"username": "spare", "password": "pw"})
    r = client.request("DELETE", "/api/admin/remove", json={"username": "spare"})
    assert r.json()["status"] == "ok"

    # Verify spare is gone
    r = client.get("/api/admin/list")
    usernames = [a["username"] for a in r.json()["admins"]]
    assert "spare" not in usernames


def test_cannot_remove_own_account(logged_in_client):
    """An admin cannot delete their own account."""
    client, username, _ = logged_in_client
    r = client.request("DELETE", "/api/admin/remove", json={"username": username})
    assert r.json()["status"] == "error"
    assert "own account" in r.json()["message"]


def test_remove_nonexistent_admin_fails(logged_in_client):
    """Removing a non-existent username returns an error."""
    client, _, _ = logged_in_client
    r = client.request("DELETE", "/api/admin/remove", json={"username": "ghost"})
    assert r.json()["status"] == "error"


def test_remove_admin_requires_auth(auth_client):
    """remove returns 401 without a valid session."""
    r = auth_client.request("DELETE", "/api/admin/remove", json={"username": "mc"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Protected endpoints return 401 without auth
# ---------------------------------------------------------------------------

def test_create_session_requires_auth(auth_client):
    """POST /api/session without auth returns 401."""
    r = auth_client.post("/api/session",
                         json={"name": "Test", "flight_duration_sec": 60,
                               "prep_duration_sec": 30})
    assert r.status_code == 401


def test_create_pilot_requires_auth(auth_client):
    """POST /api/pilot/ without auth returns 401."""
    r = auth_client.post("/api/pilot/", json={"name": "TestPilot"})
    assert r.status_code == 401


def test_rebalance_requires_auth(auth_client):
    """POST /api/groups/rebalance without auth returns 401."""
    r = auth_client.post("/api/groups/rebalance", json={})
    assert r.status_code == 401


def test_get_heat_public(auth_client):
    """GET /api/heat is accessible without authentication."""
    r = auth_client.get("/api/heat")
    assert r.status_code == 200


def test_get_pilots_public(auth_client):
    """GET /api/pilot/ is accessible without authentication."""
    r = auth_client.get("/api/pilot/")
    assert r.status_code == 200
