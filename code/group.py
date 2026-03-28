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
        group_sequence: 1-based display order within the session. This is the
                        sole in-memory identifier for a group. The database
                        stores an AUTOINCREMENT group_id internally, but that
                        key never surfaces in the model.
        channels:       Map of channel name (e.g. 'R1') to ActivePilot.
    """

    group_sequence: int
    channels: dict[str, ActivePilot] = {}

    def __init__(self, group_sequence: int, channels: dict[str, ActivePilot]):
        """
        Args:
            group_sequence: 1-based display order within the session.
            channels:       Channel-to-pilot mapping (snapshot or live roster).
        """
        super().__init__(group_sequence=group_sequence, channels=channels)
