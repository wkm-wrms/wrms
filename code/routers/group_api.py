"""
Group API Router Module.
Handles group management, matchmaking (rebalancing), and manual pilot movement.
"""
from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter

from session import get_session
from database import RaceDatabase, get_db

router = APIRouter(
    prefix="/groups",
    tags=["groups"]
)

db: RaceDatabase = get_db()


@router.get("")
async def get_session_groups():
    """Retrieves all groups defined in the current session."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session found."}
    return {"status": "ok", "groups": session.groups}


@router.post("/rebalance")
async def get_rebalance_groups():
    """
    Triggers the matchmaking algorithm (Req 3.1).
    Sorts pilots based on vision system and risk factor to optimize group composition.
    """
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session found."}
    session.rebalance_groups()
    db.update_groups(session)
    return {"status": "ok", "groups": session.groups}


class PilotMove(BaseModel):
    """Schema for moving a pilot between groups/channels."""
    pilot_id: int
    from_channel: Optional[str] = None
    from_group: Optional[int] = None
    to_channel: Optional[str] = None
    to_group: Optional[int] = None


@router.post("/move_pilot")
async def post_move_pilot(move: PilotMove):
    """
    Manually overrides pilot placement (Req 3.2).
    Allows administrators to move pilots regardless of the matchmaking algorithm.
    """
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session found."}
    # Move the pilot within the session object
    res = session.move_pilot(move.pilot_id, move.from_channel, move.from_group,
                             move.to_channel, move.to_group)
    db.update_groups(session)
    db.save_session_data(session)
    return res


@router.post("/new")
async def post_new_group():
    """Adds a new empty group to the session roster."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session found."}
    res = session.add_new_group()
    db.update_groups(session)
    db.save_session_data(session)
    return res


class GroupDelete(BaseModel):
    """Schema for deleting a specific group."""
    group_sequence: int


@router.post("/delete")
async def post_delete_group(remove: GroupDelete):
    """Removes a group and returns its pilots to the unassigned pool."""
    session = get_session()
    if session is None:
        return {"status": "error", "message": "No active session found."}
    res = session.remove_group(group_sequence=remove.group_sequence)
    db.update_groups(session)
    db.save_session_data(session)
    return res
