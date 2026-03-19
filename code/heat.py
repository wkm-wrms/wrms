from typing import List

from pilot import Pilot


class Heat:
    heat_id: int
    group_id: int
    pilots: List[Pilot]
    channels_map: dict[str, Pilot]  # kanał -> Pilot
    phase: str  # PREP, FLIGHT, ARCHIVE
    time_start: int
    time_end: int
    time_left_sec: int

    def __init__(self, group_id: int, pilots: List[Pilot],
                 channels_map: dict[str, Pilot],
                 phase: str, time_start: int, time_end: int, heat_id: int = None):
        self.group_id = group_id
        self.pilots = pilots
        self.channels_map = channels_map
        self.phase = phase
        self.time_start = time_start
        self.time_end = time_end
        self.heat_id = heat_id

    def set_id(self, heat_id: int):
        self.heat_id = heat_id
