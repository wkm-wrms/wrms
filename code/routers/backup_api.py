"""
Backup and restore API for WRMS.

GET  /api/backup/download — stream a gzip-compressed SQL dump (admin only)
POST /api/backup/restore  — validate and restore a .sql.gz backup (admin only)
"""
import gzip
import io
import os
import re
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse

from auth import require_admin
from database import get_db, SCHEMA_VERSION
from session import set_session

router = APIRouter(prefix="/backup", tags=["backup"])

db = get_db()

# Maximum upload size for a restore file (50 MB)
_MAX_RESTORE_BYTES = 50 * 1024 * 1024

# SQL statement prefixes that are allowed in a restore file
_ALLOWED_PREFIXES = (
    "begin", "commit", "rollback",
    "create table", "create index", "create unique index",
    "insert into", "delete from",
    "pragma",
    "--", "",  # comments and blank lines
)

# Keywords that must never appear in a restore file
_FORBIDDEN_KEYWORDS = [
    r"\bdrop\b", r"\balter\b", r"\bupdate\b",
    r"\battach\b", r"\bdetach\b",
    r"load_extension", r"pragma\s+key",
    r"writefile",
]
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_KEYWORDS), re.IGNORECASE)


def _generate_dump() -> bytes:
    """Create a gzip-compressed SQL dump of the current database."""
    buf = io.BytesIO()
    now = datetime.now().isoformat(timespec="seconds")
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        header = (
            f"-- WRMS Database Backup\n"
            f"-- Created: {now}\n"
            f"-- Schema version: {SCHEMA_VERSION}\n"
            f"-- App version: WRMS\n\n"
        )
        gz.write(header.encode())
        with sqlite3.connect(db.db_path) as conn:
            for line in conn.iterdump():
                gz.write((line + "\n").encode())
    return buf.getvalue()


@router.get("/download")
async def download_backup(_: str = Depends(require_admin)):
    """
    Stream a gzip-compressed SQL dump of the database.

    The filename includes a timestamp to the second so backups are
    easy to identify and sort.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"wrms_backup_{ts}.sql.gz"

    def _stream():
        yield _generate_dump()

    return StreamingResponse(
        _stream(),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _parse_version(sql_text: str) -> int | None:
    """Extract the schema version from the backup header comment."""
    m = re.search(r"--\s*Schema version:\s*(\d+)", sql_text)
    return int(m.group(1)) if m else None


def _validate_sql(sql_text: str) -> str | None:
    """
    Validate backup SQL for safety.

    Returns an error message string if validation fails, or None if the
    content is safe to execute.
    """
    for i, raw_line in enumerate(sql_text.splitlines(), 1):
        line = raw_line.strip().lower()

        # Check forbidden keywords anywhere in the line
        if _FORBIDDEN_RE.search(raw_line):
            return f"Forbidden keyword on line {i}: {raw_line[:120]}"

        # Check that every non-empty, non-comment line starts with an allowed prefix
        if line and not line.startswith("--"):
            if not any(line.startswith(p) for p in _ALLOWED_PREFIXES):
                return f"Disallowed statement on line {i}: {raw_line[:120]}"

    return None


@router.post("/restore")
async def restore_backup(
    file: UploadFile = File(...),
    _: str = Depends(require_admin),
):
    """
    Restore the database from a .sql.gz backup file.

    Validates size, gzip integrity, schema version, and SQL safety before
    applying. Saves a .pre_restore copy of the current database as a
    safety net.
    """
    # 1. Size check
    content = await file.read()
    if len(content) > _MAX_RESTORE_BYTES:
        return {"status": "error", "message": "File too large (max 50 MB)."}

    # 2. Decompress
    try:
        sql_bytes = gzip.decompress(content)
    except Exception:
        return {"status": "error", "message": "Invalid gzip file. Only .sql.gz backups are accepted."}

    sql_text = sql_bytes.decode("utf-8", errors="replace")

    # 3. Parse header
    backup_version = _parse_version(sql_text)
    if backup_version is None:
        return {"status": "error", "message": "Missing schema version header. This does not appear to be a WRMS backup."}

    # 4. Version check
    if backup_version > SCHEMA_VERSION:
        return {
            "status": "error",
            "message": (
                f"Backup schema version ({backup_version}) is newer than this "
                f"application ({SCHEMA_VERSION}). Update the application first."
            ),
        }

    # 5. SQL validation
    error = _validate_sql(sql_text)
    if error:
        return {"status": "error", "message": f"Backup validation failed: {error}"}

    # 6. Apply restore
    db_path = db.db_path
    pre_restore_path = db_path + ".pre_restore"

    try:
        import shutil

        # Build the restored database in memory first so we can validate it
        # before touching the live file.
        mem_conn = sqlite3.connect(":memory:")
        mem_conn.executescript(sql_text)

        # Copy the current live database to a timestamped archive file.
        # On Windows the live file cannot be renamed while it is open, so we
        # copy it instead — the original will be overwritten by backup() below.
        if os.path.exists(db_path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = db_path + f".{ts}.replaced_by_restore"
            shutil.copy2(db_path, archive_path)
            shutil.copy2(db_path, pre_restore_path)

        # Overwrite the live database file using SQLite's built-in backup API.
        # This avoids file-deletion issues on Windows where open file handles
        # would prevent os.remove() from succeeding.
        with sqlite3.connect(db_path) as live_conn:
            mem_conn.backup(live_conn)
        mem_conn.close()

        # Run migrations to fill any columns added after the backup was made.
        db._init_tables()  # pylint: disable=protected-access

        # Reset in-memory session state.
        set_session(None)

    except Exception as exc:
        # Attempt rollback from pre_restore copy.
        if os.path.exists(pre_restore_path):
            try:
                mem_conn.close()
            except Exception:
                pass
            with sqlite3.connect(db_path) as live_conn:
                restore_conn = sqlite3.connect(pre_restore_path)
                restore_conn.backup(live_conn)
                restore_conn.close()
            db._init_tables()  # pylint: disable=protected-access
        return {"status": "error", "message": f"Restore failed: {exc}. Previous database has been recovered."}

    warning = None
    if backup_version < SCHEMA_VERSION:
        warning = f"Backup schema is older (v{backup_version} < v{SCHEMA_VERSION}). Migrations applied automatically."

    return {
        "status": "ok",
        "backup_version": backup_version,
        "current_version": SCHEMA_VERSION,
        "warning": warning,
    }
