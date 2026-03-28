"""
Group model for WRMS — represents a training group within a session.

A group is a named set of channel-to-pilot assignments. It acts as the
source snapshot for a Heat and is managed by the matchmaking algorithm.
"""
from pydantic import BaseModel
from activepilot import ActivePilot


class Group(BaseModel):
    """
    A training group: an ordered set of channel assignments for one heat slot.

    Attributes:
        group_id:       In-memory sequential identifier (1-based). Note: this
                        does NOT correspond to the AUTOINCREMENT session_group.group_id
                        in the database — see TODO for planned refactor.
        channels:       Map of channel name (e.g. 'R1') to ActivePilot.
        group_sequence: Display order within the session, 1-based.
    """

    group_id: int
    channels: dict[str, ActivePilot] = {}
    group_sequence: int

    def __init__(self, group_id: int, channels: dict[str, ActivePilot], group_sequence: int):
        """
        Args:
            group_id:       Sequential in-memory identifier.
            channels:       Channel-to-pilot mapping (snapshot or live roster).
            group_sequence: 1-based display order within the session.
        """
        super().__init__(group_id=group_id, channels=channels, group_sequence=group_sequence)
