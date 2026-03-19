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
from fastapi import APIRouter, HTTPException

from database import get_db

router = APIRouter(
    prefix="/pilot",
    tags=["pilot"]
)

db = get_db()

# Definiujemy strukturę przychodzących danych


class PilotCreate(BaseModel):
    name: str
    country: str = ""


@router.get("/")
async def get_all_pilots():
    """ Pobierz wszystkich pilotów z bazy danych. Jeśli baza jest pusta, zwróć pustą listę."""
    pilots = db.search_pilots("")
    return {"status": "ok", "pilots": pilots}


@router.post("/")
async def create_pilot(data: PilotCreate):
    """ Dodaj nowego pilota do bazy danych. Jeśli pilot o tej samej nazwie już istnieje lub nazwa jest pusta, zwróć błąd."""
    try:
        pilot_id = db.add_pilot(data.name, data.country)
    except ValueError:
        return {"status": "error", "message": "Pilot juz istnieje lub nazwa jest pusta."}
    pilot = db.get_pilot_by_id(pilot_id)
    return {"id": pilot_id, "status": "ok", "pilot": pilot}


#    await manager.broadcast({"type": "groups_updated", "current_index": state.current_group_index})


@router.get("/{pilot_id}")
async def get_pilot(pilot_id: int):
    """ """
    pilot = db.get_pilot_by_id(pilot_id)
    if not pilot:
        raise HTTPException(status_code=404, detail="Pilot nie istnieje")
    return {"status": "ok", "pilot": pilot}


@router.get("/search/{query}")
async def search_pilots(query: str):
    """ Wyszukaj pilotów na podstawie zapytania. Zwróć listę pilotów, których nazwa zawiera podany ciąg znaków (niezależnie od wielkości liter). Jeśli nie znaleziono żadnych pilotów, zwróć pustą listę."""
    pilots = db.search_pilots(query)
    return {"status": "ok", "pilots": pilots}
