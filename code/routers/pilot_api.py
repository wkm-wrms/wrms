"""
Pilot API Router Module
This module defines FastAPI endpoints for managing pilots in the WRMS (Pilot Management System).
It provides functionality to retrieve, create, and search for pilots in the database.
Endpoints:
    GET /pilot/ - Retrieve all pilots from the database
    POST /pilot/ - Create a new pilot
    GET /pilot/{pilot_id} - Retrieve a specific pilot by ID
    GET /pilot/search/{query} - Search pilots by name query
The module uses a database connection to perform CRUD operations on pilot records.
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
    """Schema for creating a new pilot profile (Req 2.1)."""
    name: str
    country: str = ""


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
        pilot_id = db.add_pilot(data.name, data.country)
    except ValueError:
        return {"status": "error", "message": "Pilot already exists or name is empty."}
    pilot = db.get_pilot_by_id(pilot_id)
    return {"id": pilot_id, "status": "ok", "pilot": pilot}


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


@router.get("/search/{query}")
async def search_pilots(query: str):
    """
    Search for pilots by name.
    Returns a list of pilots whose name contains the query string (case-insensitive).
    """
    pilots = db.search_pilots(query)
    return {"status": "ok", "pilots": pilots}
