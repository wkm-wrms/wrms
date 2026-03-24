from pydantic import BaseModel
from pilot import Pilot
from activepilot import ActivePilot


class Group(BaseModel):
    group_id: int
#    pilots: dict[int, ActivePilot]
    channels: dict[str, ActivePilot] = {}  # mapa kanał -> Pilot
    group_sequence: int

    def __init__(self, group_id: int,  channels: dict[str, Pilot], group_sequence: int):
        super().__init__(group_id=group_id,
                         channels=channels, group_sequence=group_sequence)
