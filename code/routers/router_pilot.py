from fastapi import APIRouter, Depends, HTTPException
from pilot import PilotManager, BasePilot, ActivePilot
from database import get_db

router = APIRouter(prefix="/api/pilot", tags=["pilots"])


@router.get("/search")
def search_pilots(q: str, db=Depends(get_db)):
    manager = PilotManager(db)
    return manager.search_global(q)


@router.post("/global")
def create_global_pilot(name: str, country: str = "PL", db=Depends(get_db)):
    manager = PilotManager(db)
    pilot_id = manager.add_to_global(name, country)
    return {"id": pilot_id, "status": "created"}


@router.post("/session/{session_id}/add")
def add_pilot_to_session(session_id: int, pilot_id: int, vtx_type: str, db=Depends(get_db)):
    manager = PilotManager(db)
    try:
        manager.register_to_session(session_id, pilot_id, vtx_type)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="Pilot już jest w sesji lub błąd bazy")
