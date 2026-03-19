
from pilot import Pilot


class Group:
    id: int
    pilots: list[Pilot]
    channels: dict[str, Pilot] = {}  # mapa kanał -> Pilot
    group_sequence: int

    def __init__(self, id: int, pilots: list[Pilot], channels: dict[str, Pilot], group_sequence: int):
        self.id = id
        self.pilots = pilots
        self.channels = channels
        self.group_sequence = group_sequence
