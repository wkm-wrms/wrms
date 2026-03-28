"""
Admin API Router Module.

Handles admin authentication (login, logout, me) and admin account management
(register, set_password, list, remove).

Public endpoints: login, register (when no admins exist).
Protected endpoints: logout, me, set_password, list, remove.
"""
import os
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel

from auth import require_admin
from database import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
db = get_db()


class LoginRequest(BaseModel):
    """Credentials for admin login."""
    username: str
    password: str


class RegisterRequest(BaseModel):
    """Credentials for creating a new admin account."""
    username: str
    password: str


class SetPasswordRequest(BaseModel):
    """Request body for changing an admin password."""
    username: str
    new_password: str


class RemoveAdminRequest(BaseModel):
    """Request body for removing an admin account."""
    username: str


@router.post("/login")
async def login(data: LoginRequest, response: Response):
    """
    Validate credentials and set a session cookie on success.

    Returns status ok with username, or error on bad credentials.
    """
    if not db.verify_admin(data.username, data.password):
        return {"status": "error", "message": "Invalid username or password."}
    token = db.create_admin_session(data.username)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="strict",
    )
    return {"status": "ok", "username": data.username}


@router.post("/logout")
async def logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None),
    _: str = Depends(require_admin),
):
    """
    Invalidate the current session token and clear the cookie.
    """
    if session_token:
        db.delete_admin_session(session_token)
    response.delete_cookie(key="session_token")
    return {"status": "ok"}


@router.get("/me")
async def get_me(session_token: Optional[str] = Cookie(default=None)):
    """
    Return the current admin's username.

    Called by the frontend on every page load to determine auth state.
    Returns first_setup=True when the user table is empty so the frontend
    can show the registration form instead of the login form.
    """
    if os.environ.get("WRMS_SKIP_AUTH") == "1":
        return {"status": "ok", "username": "test_admin"}
    username = db.validate_admin_session(session_token)
    if not username:
        first_setup = not db.has_any_admin()
        return {"status": "error", "first_setup": first_setup}
    return {"status": "ok", "username": username}


@router.post("/register")
async def register(
    data: RegisterRequest,
    session_token: Optional[str] = Cookie(default=None),
):
    """
    Create a new admin account.

    Public when no admins exist (first-time setup).
    Requires authentication when at least one admin already exists.
    """
    if os.environ.get("WRMS_SKIP_AUTH") != "1" and db.has_any_admin():
        username = db.validate_admin_session(session_token)
        if not username:
            return {"status": "error", "message": "Authentication required."}
    if not data.username or not data.username.strip():
        return {"status": "error", "message": "Username cannot be empty."}
    if not data.password:
        return {"status": "error", "message": "Password cannot be empty."}
    success = db.add_admin(data.username.strip(), data.password)
    if not success:
        return {"status": "error", "message": "Username already exists."}
    return {"status": "ok", "username": data.username.strip()}


@router.post("/set_password")
async def set_password(
    data: SetPasswordRequest,
    _: str = Depends(require_admin),
):
    """
    Change the password for any admin account (including others).

    Requires authentication. Any admin can change any other admin's password.
    """
    if not data.username or not data.new_password:
        return {"status": "error", "message": "Username and new password are required."}
    success = db.set_admin_password(data.username, data.new_password)
    if not success:
        return {"status": "error", "message": "Admin not found."}
    return {"status": "ok"}


@router.get("/list")
async def list_admins(_: str = Depends(require_admin)):
    """Return all admin accounts (username and created_at, no password hash)."""
    admins = db.list_admins()
    return {"status": "ok", "admins": admins}


@router.delete("/remove")
async def remove_admin(
    data: RemoveAdminRequest,
    current_admin: str = Depends(require_admin),
):
    """
    Remove an admin account.

    Cannot remove the currently authenticated account.
    """
    if data.username == current_admin:
        return {"status": "error", "message": "Cannot remove your own account."}
    success = db.remove_admin(data.username)
    if not success:
        return {"status": "error", "message": "Admin not found."}
    return {"status": "ok"}
