"""
Pilot API Router Module
This module defines FastAPI endpoints for managing pilots in the WRMS (Pilot Management System).
It provides functionality to retrieve, create, update, delete, and search for pilots.
Endpoints:
    GET    /pilot/          - Retrieve all pilots from the database
    POST   /pilot/          - Create a new pilot (admin required)
    GET    /pilot/search/{query} - Search pilots by name query
    GET    /pilot/{pilot_id}     - Retrieve a specific pilot by ID
    PUT    /pilot/{pilot_id}     - Update a pilot (admin required)
    DELETE /pilot/{pilot_id}     - Delete a pilot (admin required)

NOTE: The /search/{query} route must appear BEFORE /{pilot_id} so that FastAPI
      does not mistake the literal "search" for an integer pilot_id.
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends

from auth import require_admin
from database import get_db

router = APIRouter(
    prefix="/pilot",
    tags=["pilot"]
)

db = get_db()


class PilotCreate(BaseModel):
    """Schema for creating a new pilot profile."""
    name: str
    country: str = ""
    risk_factor: int = 3
    notes: str = ""


class PilotUpdate(BaseModel):
    """Schema for updating an existing pilot profile."""
    name: str
    country: str = ""
    risk_factor: int = 3
    notes: str = ""


@router.get("/")
async def get_all_pilots():
    """
    Fetch all pilots from the database.
    Returns an empty list if no pilots are found.
    """
    pilots = db.search_pilots("")
    return {"status": "ok", "pilots": pilots}


@router.post("/")
async def create_pilot(data: PilotCreate, _: str = Depends(require_admin)):
    """
    Add a new pilot to the database.
    Returns an error if the pilot already exists or the name is empty.
    """
    try:
        pilot_id = db.add_pilot(data.name, data.country, data.risk_factor, data.notes)
    except ValueError:
        return {"status": "error", "message": "Pilot already exists or name is empty."}
    pilot = db.get_pilot_by_id(pilot_id)
    return {"id": pilot_id, "status": "ok", "pilot": pilot}


@router.get("/search/{query}")
async def search_pilots(query: str):
    """
    Search for pilots by name.
    Returns a list of pilots whose name contains the query string (case-insensitive).
    """
    pilots = db.search_pilots(query)
    return {"status": "ok", "pilots": pilots}


@router.get("/{pilot_id}")
async def get_pilot(pilot_id: int):
    """
    Fetch a specific pilot by ID.
    Returns an error if the pilot is not found.
    """
    pilot = db.get_pilot_by_id(pilot_id)
    if not pilot:
        return {"status": "error", "message": "Pilot does not exist."}
    return {"status": "ok", "pilot": pilot}


@router.put("/{pilot_id}")
async def update_pilot(pilot_id: int, data: PilotUpdate, _: str = Depends(require_admin)):
    """
    Update an existing pilot's profile.
    Validates name and risk_factor before writing.
    Returns an error if the pilot is not found or the name is taken.
    """
    if not data.name or len(data.name.strip()) == 0:
        return {"status": "error", "message": "Pilot name cannot be empty."}
    if not (1 <= data.risk_factor <= 6):
        return {"status": "error", "message": "Risk factor must be between 1 and 6."}
    pilot = db.get_pilot_by_id(pilot_id)
    if not pilot:
        return {"status": "error", "message": "Pilot not found."}
    try:
        db.update_pilot(pilot_id, data.name.strip(), data.country, data.risk_factor, data.notes)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    updated = db.get_pilot_by_id(pilot_id)
    return {"status": "ok", "pilot": updated}


@router.delete("/{pilot_id}")
async def delete_pilot(pilot_id: int, _: str = Depends(require_admin)):
    """
    Delete a pilot record from the database.
    Returns an error if the pilot is not found or is active in the current session.
    """
    pilot = db.get_pilot_by_id(pilot_id)
    if not pilot:
        return {"status": "error", "message": "Pilot not found."}
    from session import get_session
    session = get_session()
    if session and pilot_id in session.active_pilots:
        return {"status": "error", "message": "Pilot is active in the current session."}
    db.delete_pilot(pilot_id)
    return {"status": "ok"}
