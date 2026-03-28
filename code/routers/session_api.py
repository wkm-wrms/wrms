from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from session import Session, get_session, set_session
from pilot import Pilot


router = APIRouter(
    prefix="/session",
    tags=["session"]
)

db = get_db()


class SessionStart (BaseModel):
    name: str
    flight_duration_sec: int
    prep_duration_sec: int


@router.post("")
async def create_session(data: SessionStart):
    if not data.name or len(data.name.strip()) == 0:
        raise HTTPException(
            status_code=400, detail="Nazwa sesji nie może być pusta.")
    if data.flight_duration_sec <= 0:
        raise HTTPException(
            status_code=400, detail="Czas przelotu musi być większy niż 0.")
    if data.prep_duration_sec <= 0:
        raise HTTPException(
            status_code=400, detail="Czas przygotowania musi być większy niż 0.")

    session = Session(
        name=data.name, flight_duration_sec=data.flight_duration_sec, prep_duration_sec=data.prep_duration_sec)
    db.create_session(session)
    set_session(session)
    return {"status": "ok", "session": session, "get_session": get_session()}


@router.get("")
async def get_active_session():
    session = get_session()
    if session is None:
        raise HTTPException(
            status_code=400, detail="Brak stworzonej sesji, najpierw okresl jej parametry")
    return {"status": "ok", "session": session}


@router.get("/groups")
async def get_session_groups():
    session = get_session()
    if session is None:
        raise HTTPException(
            status_code=400, detail="Brak stworzonej sesji, najpierw okresl jej parametry")
    return {"status": "ok", "groups": session.groups}


@router.get("/{session_id}")
async def get_session_by_id(session_id: str):
    session = db.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(
            status_code=400, detail="Nie odnaleziona sesja")
    return {"status": "ok", "session": session}


@router.post("/start")
async def start_session():
    session = get_session()
    res = None
    if session is None:
        return {"status": "error", "message": "Brak stworzonej sesji, najpierw okresl jej parametry"}
    if session.is_session_active():
        return {"status": "error", "message": "Sesja już trwa."}
    if len(session.active_pilots) == 0:
        return {"status": "error", "message": "Brak pilotów. Dodaj co najmniej jednego pilota przed startem sesji."}
    if len(session.groups) == 0:
        return {"status": "error", "message": "Brak grup. Stwórz grupy przed startem sesji."}
    try:
        res = session.start()
    except ValueError as e:
        return {"status": "error", "message": f"Błąd startu sesji: {e}"}
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    db.create_or_update_heat(session.next_heat, session.active_pilots)
    db.save_session_data(session)

    return {"status": "ok", "message": f"Sesja {session.name} rozpoczęta.", "result": res}


@router.post("/stop")
async def stop_session():
    session = get_session()
    session.stop()
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    db.create_or_update_heat(session.next_heat, session.active_pilots)
    current_session = None
    set_session(None)
    return {"status": "ok", "message": "Sesja zakończona."}


@router.post("/pause")
async def pause_timer():
    raise HTTPException(
        status_code=501, detail="Pauza nie jest jeszcze zaimplementowana.")


@router.post("/resume")
async def resume_timer():
    raise HTTPException(
        status_code=501, detail="Wznowienie nie jest jeszcze zaimplementowane.")


@router.post("/skip_heat")
async def skip_heat():
    session = get_session()
    if session is None or not session.is_session_active():
        raise HTTPException(
            status_code=400, detail="Brak aktywnej sesji.")

    try:
        session.skip_current_heat()
        # Zapisujemy stan sesji i biegów po rotacji
        db.save_session_data(session)
        db.create_or_update_heat(session.current_heat, session.active_pilots)
        db.create_or_update_heat(session.next_heat, session.active_pilots)

        # Jeśli rotacja wrzuciła coś do archiwum, zapisujemy to w bazie
        while session._archive_heats:
            db.create_or_update_heat(
                session._archive_heats.pop(), session.active_pilots)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok", "message": "Bieg został pominięty, rozpoczynam przygotowania do kolejnego."}


@router.get("/all")
async def get_all_sessions():
    sessions = db.get_all_sessions()
    return {"status": "ok", "sessions": sessions}


class PilotAdd(BaseModel):
    pilot_id: int
    vtx: str


@router.post("/add_pilot")
async def session_add_pilot(pilot_add: PilotAdd):
    session = get_session()
    pilot: Pilot = db.get_pilot_by_id(pilot_add.pilot_id)
    try:
        session.add_pilot(pilot, pilot_add.vtx)
        db.session_add_pilot(session.session_id,
                             pilot_add.pilot_id, pilot_add.vtx)
        db.update_groups(session)
    except ValueError:
        return {"status": "error", "message": "Pilot juz jest aktywny"}
    return {"status": "ok"}


class PilotRemove(BaseModel):
    pilot_id: int


@router.post("/remove_pilot")
async def session_remove_pilot(pilot_remove: PilotRemove):
    session = get_session()
    session.remove_pilot(pilot_remove.pilot_id)
    db.session_remove_pilot(session.session_id, pilot_remove.pilot_id)
    db.save_session_data(session)
    db.update_groups(session)
    return {"status": "ok"}
