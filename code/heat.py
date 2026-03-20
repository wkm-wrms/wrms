from typing import List
from pydantic import BaseModel
from datetime import datetime
import json

from pilot import Pilot
from group import Group


class HeatModel (BaseModel):
    session_id: str
    heat_number: int
    group_id: int

    status: str = "PLANNED"  # PLANNED, PREP, FLIGHT, PAUSED, FINISHED
#    pilots_data_json: str
    created_at: datetime
    prep_started_at: datetime
    flight_started_at: datetime
    finished_at: datetime

    remaining_seconds_at_pause: float
    last_resume_at: datetime


class Heat:
    data: HeatModel
    pilots: List[Pilot] = []
    channels_map: dict[str, Pilot]

    def __init__(self, group: Group, session_id: str, heat_number: int):
        self.data = HeatModel(
            session_id=session_id,
            group_id=group.id,
            heat_number=heat_number,
            status='PLANNED',
            #            pilots_data_json=json.dumps(group.pilots),
            created_at=datetime.now(),
        )
        self.pilots = group.pilots,
        self.channels_map = group.channels_map,

# Getters block

    def get_status(self):
        return self.data.status

    def get_last_resume_at(self):
        return self.data.last_resume_at

    def get_flight_started_at(self):
        return self.data.flight_started_at

    def get_prep_started_at(self):
        return self.data.prep_started_at

    def remaining_seconds_at_pause(self):
        return self.data.remaining_seconds_at_pause

    def as_dict(self):
        return self.data.dict()
