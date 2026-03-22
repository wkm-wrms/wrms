from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json

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
    print(f"Creating new session: {data}")
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
    print("sukces?")
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
    db.save_session_data(session)
    return {"status": "ok", "message": f"Sesja {session.name} rozpoczęta.", "result": res}


@router.post("/stop")
async def stop_session():
    session = get_session()
    session.stop()
    db.save_session_data(session)
    set_session(None)
    return {"status": "ok", "message": "Sesja zakończona."}


@router.post("/pause")
async def pause_timer():
    session = get_session()
    if not session.is_session_active:
        raise HTTPException(status_code=400, detail="Brak aktywnej sesji.")
    if session.current_phase == "PAUSED":
        return {"status": "ok", "message": "Sesja już jest w pauzie."}

    session.pause()
    db.save_session_data(session)
    return {"status": "ok", "message": "Sesja wstrzymana."}
    if state.current_phase in ("PREP", "FLIGHT"):
        state.phase_before_pause = state.current_phase
    else:
        state.phase_before_pause = "PREP"

    state.timer_running = False
    state.current_phase = "PAUSED"
    await manager.broadcast({"type": "session_paused"})
    return {"status": "ok", "message": "Sesja zapauzowana."}


@router.post("/api/cycle/resume")
async def resume_timer():
    if not state.is_session_active:
        raise HTTPException(status_code=400, detail="Brak aktywnej sesji.")
    if state.current_phase != "PAUSED":
        return {"status": "ok", "message": "Sesja nie jest w pauzie."}
    if len(state.groups) == 0:
        raise HTTPException(status_code=400, detail="Brak grup do wznowienia.")

    state.current_phase = state.phase_before_pause if state.phase_before_pause in (
        "PREP", "FLIGHT") else "PREP"
    state.timer_running = True
    await manager.broadcast({"type": "session_resumed"})
    return {"status": "ok", "message": "Sesja wznowiona."}


@router.post("/api/cycle/skip")
async def skip_phase():
    if not state.is_session_active:
        raise HTTPException(status_code=400, detail="Brak aktywnej sesji.")
    if state.current_phase not in ("PREP", "FLIGHT"):
        raise HTTPException(
            status_code=400, detail="Nie można pominąć obecną fazę. Sesja musi być w PREP lub FLIGHT.")
    if len(state.groups) == 0:
        raise HTTPException(status_code=400, detail="Brak grup.")

    if state.current_phase == "PREP":
        state.current_phase = "FLIGHT"
        message = "Pominięto przygotowanie, przechodzę do przelotu."
    elif state.current_phase == "FLIGHT":
        state.current_group_index = (
            state.current_group_index + 1) % len(state.groups)
        state.current_phase = "PREP"
        message = "Pominięto przelot, przechodzę do następnej grupy."

    await manager.broadcast({"type": "phase_skipped"})
    return {"status": "ok", "message": message}


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
    db.update_groups(session)
    return {"status": "ok"}
