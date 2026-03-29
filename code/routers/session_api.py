"""
API module for managing training sessions.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_admin
from database import get_db
from session import Session, get_session, set_session
from pilot import Pilot

router = APIRouter(
    prefix="/session",
    tags=["session"]
)
db = get_db()


class SessionStart(BaseModel):
    """Input data model for creating a new session (Req 2.2)."""
    name: str
    flight_duration_sec: int
    prep_duration_sec: int


@router.post("")
async def create_session(data: SessionStart, _: str = Depends(require_admin)):
    """
    Creates a new session and persists it in the database.
    """
    if not data.name or len(data.name.strip()) == 0:
        return {"status": "error", "message": "Session name cannot be empty."}
    if data.flight_duration_sec <= 0:
        return {"status": "error", "message": "Flight duration must be greater than 0."}
    if data.prep_duration_sec <= 0:
        return {"status": "error", "message": "Preparation time must be greater than 0."}

    session = Session(
        name=data.name,
        flight_duration_sec=data.flight_duration_sec,
        prep_duration_sec=data.prep_duration_sec,
    )
    db.create_session(session)
    set_session(session)
    return {"status": "ok", "session": session}


@router.get("")
async def get_active_session():
    """Returns data for the currently active session."""
    session = get_session()
    if session is None:
        return {"status": "error",
                "message": "No session found. Please define session parameters first."}
    return {"status": "ok", "session": session}


@router.get("/groups")
async def get_session_groups_list():
    """Returns the list of groups in the active session roster."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session found."}
    return {"status": "ok", "groups": session.groups}


@router.get("/{session_id}")
async def get_session_by_id(session_id: str):
    """Retrieves a historical session from the database by ID."""
    session = db.get_session_by_id(session_id)
    if session is None:
        return {"status": "error", "message": "Session not found."}
    return {"status": "ok", "session": session}


@router.post("/start")
async def start_session(_: str = Depends(require_admin)):
    """Starts the session timer and activates the first heat (Req: Cycle Start)."""
    session = get_session()
    res = None
    if session is None:
        return {"status": "error", "message": "No session found. Please define parameters first."}
    if session.is_session_active():
        return {"status": "error", "message": "Session is already active."}
    if len(session.active_pilots) == 0:
        msg = "No pilots added. Add at least one pilot before starting."
        return {"status": "error", "message": msg}
    if len(session.groups) == 0:
        return {"status": "error", "message": "No groups created. Create groups before starting."}
    try:
        res = session.start()
    except ValueError as e:
        return {"status": "error", "message": f"Session start error: {e}"}

    db.create_or_update_heat(session.current_heat, session.active_pilots)
    db.create_or_update_heat(session.next_heat, session.active_pilots)
    db.save_session_data(session)
    return {"status": "ok", "message": f"Session {session.name} started.", "result": res}


@router.post("/stop")
async def stop_session(_: str = Depends(require_admin)):
    """Stops and closes the active session (Req: End Session)."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session found."}
    session.stop()
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    db.create_or_update_heat(session.next_heat, session.active_pilots)
    set_session(None)
    return {"status": "ok", "message": "Session finished."}


@router.post("/pause")
async def pause_timer(_: str = Depends(require_admin)):
    """Pause the active session and freeze the current heat timer."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    try:
        session.pause()
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    return {"status": "ok"}


@router.post("/resume")
async def resume_timer(_: str = Depends(require_admin)):
    """Resume a paused session and continue the heat timer from where it was frozen."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    try:
        session.resume()
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    db.save_session_data(session)
    db.create_or_update_heat(session.current_heat, session.active_pilots)
    return {"status": "ok"}


@router.post("/skip_heat")
async def skip_heat(_: str = Depends(require_admin)):
    """Skips the current heat and shifts to the next group in rotation."""
    session = get_session()
    if session is None or not session.is_session_active():
        return {"status": "error", "message": "No active session found."}

    try:
        session.skip_current_heat()
        # Persist session and heat state after rotation
        db.save_session_data(session)
        db.create_or_update_heat(session.current_heat, session.active_pilots)
        db.create_or_update_heat(session.next_heat, session.active_pilots)

        # Drain the archive queue and persist finished heats
        archived = session.pop_archived_heat()
        while archived:
            db.create_or_update_heat(archived, session.active_pilots)
            archived = session.pop_archived_heat()

    except ValueError as e:
        return {"status": "error", "message": str(e)}

    return {"status": "ok", "message": "Heat skipped, preparing next group."}


@router.get("/all")
async def get_all_sessions():
    """Retrieves a list of all historical sessions from the database."""
    sessions = db.get_all_sessions()
    return {"status": "ok", "sessions": sessions}


class SessionParamsUpdate(BaseModel):
    """Schema for updating session timing parameters mid-session."""
    flight_duration_sec: int
    prep_duration_sec: int


@router.post("/update_params")
async def update_session_params(data: SessionParamsUpdate, _: str = Depends(require_admin)):
    """
    Update flight and prep durations for the active session.

    Changes take effect from the next heat. The currently running heat
    is not affected.
    """
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    if data.flight_duration_sec <= 0:
        return {"status": "error", "message": "Flight duration must be greater than 0."}
    if data.prep_duration_sec <= 0:
        return {"status": "error", "message": "Preparation time must be greater than 0."}
    session.update_params(data.flight_duration_sec, data.prep_duration_sec)
    db.save_session_data(session)
    if session.next_heat is not None:
        db.create_or_update_heat(session.next_heat, session.active_pilots)
    return {
        "status": "ok",
        "flight_duration_sec": session.flight_duration_sec,
        "prep_duration_sec": session.prep_duration_sec,
    }


class PilotAdd(BaseModel):
    """Schema for adding a pilot to the session."""
    pilot_id: int
    vtx: str


@router.post("/add_pilot")
async def session_add_pilot(pilot_add: PilotAdd, _: str = Depends(require_admin)):
    """Adds a pilot to the active session and triggers matchmaking (Req 3.2)."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    pilot: Pilot = db.get_pilot_by_id(pilot_add.pilot_id)
    try:
        session.add_pilot(pilot, pilot_add.vtx)
        db.session_add_pilot(session.session_id,
                             pilot_add.pilot_id, pilot_add.vtx)
        db.update_groups(session)
    except ValueError:
        return {"status": "error", "message": "Pilot is already active."}
    return {"status": "ok"}


class PilotRemove(BaseModel):
    """Schema for removing a pilot from the session."""
    pilot_id: int


@router.post("/remove_pilot")
async def session_remove_pilot(pilot_remove: PilotRemove, _: str = Depends(require_admin)):
    """Removes a pilot from the session and triggers matchmaking rebalance."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session."}
    session.remove_pilot(pilot_remove.pilot_id)
    db.session_remove_pilot(session.session_id, pilot_remove.pilot_id)
    db.save_session_data(session)
    db.update_groups(session)
    return {"status": "ok"}
