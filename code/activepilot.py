from pydantic import BaseModel
from pilot import Pilot


class ActivePilot (BaseModel):
    pilot_id: int
    pilot: Pilot
    vtx: str
    is_digital: bool

    def __init__(self,  pilot: Pilot, vtx: str,  is_digital: bool = None):
        print
        if is_digital is None:
            is_digital = (vtx != "Analog")
        super().__init__(pilot_id=pilot.get_pilot_id(),
                         pilot=pilot, vtx=vtx, is_digital=is_digital)

    def to_dict(self):
        return self.model_dump()
