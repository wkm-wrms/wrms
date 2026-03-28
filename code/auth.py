"""
Authentication dependency for the WRMS admin API.

Provides require_admin, a FastAPI Depends callable that validates the
session_token cookie against the admin_session table in the database.

Set WRMS_SKIP_AUTH=1 to bypass authentication (used by the test suite).
"""
import os

from fastapi import Cookie, HTTPException

from database import get_db


async def require_admin(session_token: str = Cookie(default=None)) -> str:
    """
    FastAPI dependency that enforces admin authentication.

    Reads the session_token cookie, validates it against the admin_session
    table, and returns the authenticated admin's username on success.

    Set WRMS_SKIP_AUTH=1 to bypass (test mode only).

    Args:
        session_token: The HttpOnly session cookie set at login.

    Returns:
        The authenticated admin's username string.

    Raises:
        HTTPException(401): If the token is missing, expired, or invalid.
    """
    if os.environ.get("WRMS_SKIP_AUTH") == "1":
        return "test_admin"
    db = get_db()
    username = db.validate_admin_session(session_token)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return username
