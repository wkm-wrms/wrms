from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException

from session import get_session
from database import RaceDatabase, get_db

router = APIRouter(
    prefix="/groups",
    tags=["groups"]
)

db: RaceDatabase = get_db()


@router.get("")
async def get_session_groups():
    session = get_session()
    if session is None:
        raise HTTPException(
            status_code=400, detail="Brak stworzonej sesji, najpierw okresl jej parametry")
    return {"status": "ok", "groups": session.groups}


@router.post("/rebalance")
async def get_rebalance_groups():
    session = get_session()
    if session is None:
        raise HTTPException(
            status_code=400, detail="Brak stworzonej sesji, najpierw okresl jej parametry")
    session.rebalance_groups()
    db.update_groups(session)
    return {"status": "ok", "groups": session.groups}


class PilotMove(BaseModel):
    pilot_id: int
    from_channel: Optional[str]
    from_group: Optional[int]
    to_channel: Optional[str]
    to_group: Optional[int]


@router.post("/move_pilot")
async def post_move_pilot(move: PilotMove):
    session = get_session()
    if session is None:
        raise HTTPException(
            status_code=400, detail="Brak stworzonej sesji")
    # Poszukajmy czy pilot jest
    res = session.move_pilot(move.pilot_id, move.from_channel, move.from_group,
                             move.to_channel, move.to_group)
    db.update_groups(session)
    db.save_session_data(session)
    return res


@router.post("/new")
async def post_new_group():
    session = get_session()
    # Poszukajmy czy pilot jest

    res = session.add_new_group()
    db.update_groups(session)
    db.save_session_data(session)
    return res


class GroupDelete(BaseModel):
    group_sequence: int


@router.post("/delete")
async def post_delete_group(remove: GroupDelete):
    session = get_session()
    # Poszukajmy czy pilot jest

    res = session.remove_group(group_sequence=remove.group_sequence)
    db.update_groups(session)
    db.save_session_data(session)
    return res
