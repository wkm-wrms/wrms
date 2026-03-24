from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import json

from pilot import Pilot
from activepilot import ActivePilot
from group import Group


class Heat(BaseModel):
    session_id: str
    heat_number: int
    prep_time: int
    flight_time: int

    group_id: int

    channels: dict[str, ActivePilot]

    status: str = "PLANNED"  # PLANNED, PREP, FLIGHT, PAUSED, FINISHED
    created_at: datetime
    prep_started_at: Optional[datetime] = None
    flight_started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    remaining_seconds_at_pause: Optional[float] = None
    last_resume_at: Optional[datetime] = None

    def __init__(self, session_id: str, heat_number: int, prep_time: int, flight_time: int,
                 group_id: int = None, group: Group = None, channels: dict[str, ActivePilot] = None, status: str = "PLANNED",
                 created_at: datetime = datetime.now(),
                 prep_started_at: Optional[datetime] = None, flight_started_at: Optional[datetime] = None,
                 finished_at: Optional[datetime] = None, remaining_seconds_at_pause: Optional[float] = None,
                 last_resume_at: Optional[datetime] = None
                 ):

        if group_id is None:
            if group:
                group_id = group.group_id
            else:
                raise ValueError("Podaj albo group_id albo group")
        if channels is None:
            if group:
                channels = group.channels

        super().__init__(
            session_id=session_id,
            heat_number=heat_number,
            prep_time=prep_time,
            flight_time=flight_time,
            group_id=group_id,
            channels=channels,
            status=status,
            created_at=created_at,
            prep_started_at=prep_started_at,
            flight_started_at=flight_started_at,
            finished_at=finished_at,
            remaining_seconds_at_pause=remaining_seconds_at_pause,
            last_resume_at=last_resume_at)

    def start_prep(self):
        self.status = 'PREP'
        self.prep_started_at = datetime.now()

    def start_flight(self):
        self.status = 'FLIGHT'
        self.flight_started_at = datetime.now()

    def finish(self):
        self.status = 'FINISHED'
        self.finished_at = datetime.now()

    def pause(self):
        if self.status != 'FLIGHT':
            raise ValueError("Nie mozna zatrzymac fazy przygotowania")
        self.remaining_seconds_at_pause = self.get_remaining_seconds()
        self.status = 'PAUSED'

    def resume(self):
        self.last_resume_at = datetime.now()
        self.status = 'FLIGHT'

    def get_remaining_seconds(self):
        if self.status == 'PLANNED':
            return self.prep_time
        elif self.status == 'PREP':
            return self.prep_time - (datetime.now() - self.prep_started_at).total_seconds()
        elif self.status == 'FLIGHT':
            if self.last_resume_at is not None:
                return self.remaining_seconds_at_pause - (datetime.now() - self.last_resume_at).total_seconds()
            else:
                return self.flight_time - (datetime.now() - self.flight_started_at).total_seconds()
        elif self.status == 'PAUSED':
            return self.remaining_seconds_at_pause
        elif self.status == 'FINISHED':
            return 0

    # Getters block

    def get_status(self):
        return self.status

    def get_last_resume_at(self):
        return self.last_resume_at

    def get_flight_started_at(self):
        return self.flight_started_at

    def get_prep_started_at(self):
        return self.prep_started_at

    def remaining_seconds_at_pause(self):
        return self.remaining_seconds_at_pause

    def as_dict(self):
        return self.dict()
