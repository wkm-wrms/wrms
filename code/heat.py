from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import json

from pilot import Pilot
from group import Group


class HeatModel (BaseModel):
    session_id: str
    heat_number: int
    group_id: int

    prep_time: int
    flight_time: int

    status: str = "PLANNED"  # PLANNED, PREP, FLIGHT, PAUSED, FINISHED
    pilots_data: dict
    created_at: datetime
    prep_started_at: Optional[datetime] = None
    flight_started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    remaining_seconds_at_pause: Optional[float] = None
    last_resume_at: Optional[datetime] = None


class Heat:
    data: HeatModel
    pilots: List[Pilot] = []
    channels: dict[str, Pilot]

    def __init__(self, group: Group, session_id: str, heat_number: int, prep_time: int, flight_time: int):
        pilot_data = {}
        for ch in group.channels:
            pilot_data[ch] = {
                "pilot_id": group.channels[ch].pilot_id,
                "name": group.channels[ch].name,
            }
        self.data = HeatModel(
            session_id=session_id,
            group_id=group.group_id,
            heat_number=heat_number,
            status='PLANNED',
            pilots_data=pilot_data,
            created_at=datetime.now(),
            prep_time=prep_time,
            flight_time=flight_time
        )
        self.pilots = group.pilots,
        self.channels = group.channels,

    def start_prep(self):
        self.data.status = 'PREP'
        self.data.prep_started_at = datetime.now()

    def start_flight(self):
        self.data.status = 'FLIGHT'
        self.data.flight_started_at = datetime.now()

    def finish(self):
        self.data.status = 'FINISHED'
        self.data.finished_at = datetime.now()

    def pause(self):
        if self.data.status != 'FLIGHT':
            raise ValueError("Nie mozna zatrzymac fazy przygotowania")
        self.data.remaining_seconds_at_pause = self.get_remaining_seconds()
        self.data.status = 'PAUSED'

    def resume(self):
        self.data.last_resume_at = datetime.now()
        self.data.status = 'FLIGHT'

    def get_remaining_seconds(self):
        if self.data.status == 'PLANNED':
            return self.data.prep_time
        elif self.data.status == 'PREP':
            return self.data.prep_time - (datetime.now() - self.data.prep_started_at).total_seconds()
        elif self.data.status == 'FLIGHT':
            if self.data.last_resume_at is not None:
                return self.data.remaining_seconds_at_pause - (datetime.now() - self.data.last_resume_at).total_seconds()
            else:
                return self.data.flight_time - (datetime.now() - self.data.flight_started_at).total_seconds()
        elif self.data.status == 'PAUSED':
            return self.data.remaining_seconds_at_pause
        elif self.data.status == 'FINISHED':
            return 0

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
