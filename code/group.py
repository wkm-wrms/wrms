from pydantic import BaseModel
from pilot import Pilot


class Group:
    group_id: int
    pilots: list[Pilot]
    channels: dict[str, Pilot] = {}  # mapa kanał -> Pilot
    group_sequence: int

    def __init__(self, group_id: int, pilots: list[Pilot], channels: dict[str, Pilot], group_sequence: int):
        self.group_id = group_id
        self.pilots = pilots
        self.channels = channels
        self.group_sequence = group_sequence
