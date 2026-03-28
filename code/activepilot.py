"""
ActivePilot model for WRMS — represents a pilot registered in an active session.

Wraps a Pilot with session-specific data: VTX type and the derived
is_digital flag used by the matchmaking algorithm to assign channels.
"""
from pydantic import BaseModel
from pilot import Pilot


class ActivePilot(BaseModel):
    """A pilot actively participating in a session, with VTX configuration."""

    pilot_id: int
    pilot: Pilot
    vtx: str
    is_digital: bool

    def __init__(self, pilot: Pilot, vtx: str, is_digital: bool = None):
        """
        Create an ActivePilot from a Pilot and VTX type string.

        Args:
            pilot: The base Pilot record.
            vtx: VTX system type, e.g. 'Analog' or 'DJI'.
            is_digital: Overrides auto-detection when provided explicitly.
        """
        if is_digital is None:
            is_digital = vtx != "Analog"
        super().__init__(pilot_id=pilot.get_pilot_id(),
                         pilot=pilot, vtx=vtx, is_digital=is_digital)

    def to_dict(self):
        """Return a plain dictionary representation of this active pilot."""
        return self.model_dump()
