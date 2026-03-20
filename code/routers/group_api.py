from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    groups = session.groups
    paddock = []
#    for g in session.groups:
#        groups.append(g)
#        print(f"{g}")
    # skalkulu paddock, czyli pilotow bez przypisania
#    pilots_by_id = {}
#    for pilot in session.active_pilots:
#        pilots_by_id[pilot.pilot.id] = pilot
#    for group in session.groups:
#        print(
#            f"groups: {str(type(session.groups))}, group: {str(type(group))}")
#        for pilot in group.pilots:
#            del pilots_by_id[pilot.id]
#    paddock: list[Pilot] = [pilots_by_id[k] for k in pilots_by_id]

    return {"status": "ok", "groups": session.groups, "paddock": paddock}


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
    from_channel: str
    from_group: int
    to_channel: str
    to_group: int


@router.post("/move_pilot")
async def post_move_pilot(move: PilotMove):
    if move.pilot_id is None or move.from_channel is None or move.from_group is None:
        raise HTTPException(status_code=404, detail="Nieokreślony pilot")
    session = get_session()
    # Poszukajmy czy pilot jest
    groups = session.groups

    for group in groups:
        print(
            f"group: {str(type(group))} {group}, groups: {str(type(session.groups))}")
#        for pilot in group.pilots:
#            if pilot.id == move.pilot_id:
#                group_from = group
#    if group_from is None:
#        raise HTTPException(
#            status_code=404, detail="Pilot nie jest w zadnej grupie")
    return {"status": "ok", "groups": session.groups}
