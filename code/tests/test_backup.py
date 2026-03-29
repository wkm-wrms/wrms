"""
Backup and restore API tests.
"""
import gzip
import io
import pytest
from fastapi.testclient import TestClient
from main import app
from database import SCHEMA_VERSION

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_backup_bytes(schema_version=None, extra_sql="", forbidden=None):
    """
    Build a .sql.gz backup file for testing.

    Uses the real /api/backup/download content as the SQL base so the schema
    is always complete and up-to-date. Overrides the Schema version header
    when schema_version is given, and appends extra_sql / forbidden lines at
    the end (before COMMIT) for validation tests.
    """
    sv = schema_version if schema_version is not None else SCHEMA_VERSION

    # Get a real dump from the running app — guaranteed to have the full schema.
    r = client.get("/api/backup/download")
    base_sql = gzip.decompress(r.content).decode()

    # Replace the schema version header if overriding.
    import re as _re
    base_sql = _re.sub(
        r"-- Schema version: \d+",
        f"-- Schema version: {sv}",
        base_sql,
    )

    # Inject extra / forbidden SQL before the final COMMIT.
    if extra_sql or forbidden:
        injection = "\n".join(filter(None, [extra_sql, forbidden or ""])) + "\n"
        base_sql = base_sql.replace("COMMIT;", injection + "COMMIT;")

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(base_sql.encode())
    return buf.getvalue()


def _upload(data: bytes, filename="test.sql.gz"):
    return client.post(
        "/api/backup/restore",
        files={"file": (filename, io.BytesIO(data), "application/gzip")},
    )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class TestBackupDownload:
    def test_returns_200(self):
        r = client.get("/api/backup/download")
        assert r.status_code == 200

    def test_content_type_gzip(self):
        r = client.get("/api/backup/download")
        assert "gzip" in r.headers.get("content-type", "")

    def test_filename_has_timestamp(self):
        r = client.get("/api/backup/download")
        cd = r.headers.get("content-disposition", "")
        assert "wrms_backup_" in cd
        assert ".sql.gz" in cd

    def test_decompresses_to_valid_sql(self):
        r = client.get("/api/backup/download")
        sql = gzip.decompress(r.content).decode()
        assert "BEGIN TRANSACTION" in sql or "CREATE TABLE" in sql

    def test_contains_schema_version_header(self):
        r = client.get("/api/backup/download")
        sql = gzip.decompress(r.content).decode()
        assert f"Schema version: {SCHEMA_VERSION}" in sql

    def test_requires_auth(self, monkeypatch):
        monkeypatch.delenv("WRMS_SKIP_AUTH", raising=False)
        with TestClient(app) as c:
            r = c.get("/api/backup/download")
            assert r.status_code == 401


# ---------------------------------------------------------------------------
# Restore — happy path
# ---------------------------------------------------------------------------

class TestBackupRestore:
    def test_restore_own_backup(self):
        r_dl = client.get("/api/backup/download")
        r = _upload(r_dl.content)
        assert r.json()["status"] == "ok"

    def test_restore_returns_versions(self):
        r_dl = client.get("/api/backup/download")
        data = _upload(r_dl.content).json()
        assert data["backup_version"] == SCHEMA_VERSION
        assert data["current_version"] == SCHEMA_VERSION

    def test_older_schema_warns(self):
        data = _upload(_make_backup_bytes(schema_version=SCHEMA_VERSION - 1)).json()
        assert data["status"] == "ok"
        assert data["warning"] is not None
        assert "older" in data["warning"]

    def test_current_schema_no_warning(self):
        data = _upload(_make_backup_bytes()).json()
        assert data["status"] == "ok"
        assert data["warning"] is None


# ---------------------------------------------------------------------------
# Restore — validation failures
# ---------------------------------------------------------------------------

class TestBackupRestoreValidation:
    def test_invalid_gzip_rejected(self):
        r = _upload(b"this is not gzip")
        assert r.json()["status"] == "error"
        assert "gzip" in r.json()["message"].lower()

    def test_missing_version_header_rejected(self):
        sql = "BEGIN TRANSACTION;\nCREATE TABLE IF NOT EXISTS pilot (pilot_id INTEGER PRIMARY KEY, name TEXT NOT NULL);\nCOMMIT;\n"
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(sql.encode())
        r = _upload(buf.getvalue())
        assert r.json()["status"] == "error"
        assert "version" in r.json()["message"].lower()

    def test_newer_version_rejected(self):
        r = _upload(_make_backup_bytes(schema_version=SCHEMA_VERSION + 1))
        assert r.json()["status"] == "error"
        assert "newer" in r.json()["message"].lower()

    def test_drop_table_rejected(self):
        r = _upload(_make_backup_bytes(forbidden="DROP TABLE pilot;"))
        assert r.json()["status"] == "error"

    def test_update_rejected(self):
        r = _upload(_make_backup_bytes(forbidden="UPDATE pilot SET name='x' WHERE 1=1;"))
        assert r.json()["status"] == "error"

    def test_alter_rejected(self):
        r = _upload(_make_backup_bytes(forbidden="ALTER TABLE pilot ADD COLUMN evil TEXT;"))
        assert r.json()["status"] == "error"

    def test_attach_rejected(self):
        r = _upload(_make_backup_bytes(forbidden="ATTACH DATABASE '/etc/passwd' AS evil;"))
        assert r.json()["status"] == "error"

    def test_restore_requires_auth(self, monkeypatch):
        monkeypatch.delenv("WRMS_SKIP_AUTH", raising=False)
        with TestClient(app) as c:
            r = c.post("/api/backup/restore", files={"file": ("x.sql.gz", io.BytesIO(b""), "application/gzip")})
            assert r.status_code == 401
