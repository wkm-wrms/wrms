"""
ActivePilot model for WRMS — represents a pilot registered in an active session.

Wraps a Pilot with session-specific data: VTX type and the derived
is_digital flag used by the matchmaking algorithm to assign channels.
"""
from pydantic import BaseModel
from pilot import Pilot

# Matchmaking vision-system points per VTX type.
# Any vtx value not listed here falls back to 1 (lowest score, treated as digital).
VTX_POINTS: dict[str, int] = {
    "Analog":    1,
    "DJI":       4,
    "Walksnail": 4,
    "HD0":       5,
}


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
            vtx: VTX system type — one of 'Analog', 'DJI', 'HD0', 'Walksnail'.
            is_digital: Overrides auto-detection when provided explicitly.
        """
        if is_digital is None:
            is_digital = vtx != "Analog"
        super().__init__(pilot_id=pilot.get_pilot_id(),
                         pilot=pilot, vtx=vtx, is_digital=is_digital)

    def total_score(self) -> int:
        """Return matchmaking score: vision_points(vtx) + pilot.risk_factor.

        Used by rebalance_groups() to sort pilots within channels.
        Higher score → higher channel number within the pilot's tier.
        """
        return VTX_POINTS.get(self.vtx, 1) + self.pilot.risk_factor

    def to_dict(self):
        """Return a plain dictionary representation of this active pilot."""
        return self.model_dump()
