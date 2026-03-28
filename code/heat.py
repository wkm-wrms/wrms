"""
Heat model for WRMS — represents a single race heat within a session.

A heat is an immutable snapshot of a group roster paired with timing state.
It progresses through the state machine: PLANNED → PREP → FLIGHT → FINISHED.
Pause/resume mid-FLIGHT is supported via remaining_seconds_at_pause.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from activepilot import ActivePilot
from group import Group


class Heat(BaseModel):
    """
    A single race heat: a frozen group roster plus timing and status tracking.

    State machine:
        PLANNED → PREP  (start_prep called at session start or after rotation)
        PREP    → FLIGHT (start_flight called when prep timer expires)
        FLIGHT  → PAUSED (pause called by MC)
        PAUSED  → FLIGHT (resume called by MC)
        FLIGHT  → FINISHED (finish called by rotate_heats when flight timer expires)
    """

    session_id: str
    heat_number: int
    prep_time: int
    flight_time: int

    group_sequence: int

    channels: dict[str, ActivePilot]

    status: str = "PLANNED"  # PLANNED, PREP, FLIGHT, PAUSED, FINISHED
    created_at: datetime
    prep_started_at: Optional[datetime] = None
    flight_started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    remaining_seconds_at_pause: Optional[float] = None
    last_resume_at: Optional[datetime] = None

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session_id: str,
        heat_number: int,
        prep_time: int,
        flight_time: int,
        group_sequence: int = None,
        group: Group = None,
        channels: dict[str, ActivePilot] = None,
        status: str = "PLANNED",
        created_at: datetime = None,
        prep_started_at: Optional[datetime] = None,
        flight_started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        remaining_seconds_at_pause: Optional[float] = None,
        last_resume_at: Optional[datetime] = None,
    ):
        """
        Create a Heat, optionally deriving group_sequence and channels from a Group.

        Either group_sequence or group must be provided. When group is given and
        channels is None, channels are copied from the group (snapshot semantics).

        Args:
            session_id:                 Parent session UUID.
            heat_number:                Sequential heat number within the session.
            prep_time:                  Preparation phase duration in seconds.
            flight_time:                Flight phase duration in seconds.
            group_sequence:             1-based group position within the session.
            group:                      Source Group object; used when group_sequence is None.
            channels:                   Explicit channel map; copied from group if None.
            status:                     Initial status string (default 'PLANNED').
            created_at:                 Creation timestamp; defaults to now().
            prep_started_at:            Timestamp when PREP phase began.
            flight_started_at:          Timestamp when FLIGHT phase began.
            finished_at:                Timestamp when heat was finished.
            remaining_seconds_at_pause: Seconds left on the clock at pause time.
            last_resume_at:             Timestamp of the most recent resume.
        """
        if created_at is None:
            created_at = datetime.now()
        if group_sequence is None:
            if group:
                group_sequence = group.group_sequence
            else:
                raise ValueError("Provide either group_sequence or group.")
        if channels is None and group:
            # Copy group channels to create an immutable heat snapshot
            channels = group.channels.copy()

        super().__init__(
            session_id=session_id,
            heat_number=heat_number,
            prep_time=prep_time,
            flight_time=flight_time,
            group_sequence=group_sequence,
            channels=channels,
            status=status,
            created_at=created_at,
            prep_started_at=prep_started_at,
            flight_started_at=flight_started_at,
            finished_at=finished_at,
            remaining_seconds_at_pause=remaining_seconds_at_pause,
            last_resume_at=last_resume_at,
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def start_prep(self):
        """Transition to PREP state and record the start timestamp."""
        self.status = 'PREP'
        self.prep_started_at = datetime.now()

    def start_flight(self):
        """Transition to FLIGHT state and record the flight start timestamp."""
        self.status = 'FLIGHT'
        self.flight_started_at = datetime.now()

    def finish(self):
        """Transition to FINISHED state and record the finish timestamp."""
        self.status = 'FINISHED'
        self.finished_at = datetime.now()

    def pause(self):
        """
        Pause a FLIGHT-phase heat, preserving remaining seconds.

        Raises:
            ValueError: If the heat is not currently in FLIGHT.
        """
        if self.status != 'FLIGHT':
            raise ValueError("Cannot pause: heat is not in FLIGHT phase.")
        self.remaining_seconds_at_pause = self.get_remaining_seconds()
        self.status = 'PAUSED'

    def resume(self):
        """Resume a PAUSED heat and record the resume timestamp."""
        self.last_resume_at = datetime.now()
        self.status = 'FLIGHT'

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def get_remaining_seconds(self) -> Optional[float]:  # pylint: disable=too-many-return-statements
        """
        Calculate remaining seconds for the current phase.

        For PREP: counts down from prep_time since prep_started_at.
        For FLIGHT: counts down from flight_time (or from pause remainder).
        For PAUSED: returns the saved remainder.
        For FINISHED: returns 0.

        Returns:
            Remaining seconds as a float, 0 for FINISHED, None for PLANNED.
        """
        if self.status == 'PLANNED':
            return float(self.prep_time)
        if self.status == 'PREP':
            return self.prep_time - (datetime.now() - self.prep_started_at).total_seconds()
        if self.status == 'FLIGHT':
            if self.last_resume_at is not None:
                # After a resume, count down from the saved remainder
                elapsed = (datetime.now() - self.last_resume_at).total_seconds()
                return self.remaining_seconds_at_pause - elapsed
            return self.flight_time - (datetime.now() - self.flight_started_at).total_seconds()
        if self.status == 'PAUSED':
            return self.remaining_seconds_at_pause
        if self.status == 'FINISHED':
            return 0.0
        return None

    # ------------------------------------------------------------------
    # Getters
    # ------------------------------------------------------------------

    def get_status(self) -> str:
        """Return the current status string."""
        return self.status

    def get_last_resume_at(self) -> Optional[datetime]:
        """Return the timestamp of the most recent resume, or None."""
        return self.last_resume_at

    def get_flight_started_at(self) -> Optional[datetime]:
        """Return the timestamp when the FLIGHT phase started, or None."""
        return self.flight_started_at

    def get_prep_started_at(self) -> Optional[datetime]:
        """Return the timestamp when the PREP phase started, or None."""
        return self.prep_started_at

    def get_remaining_seconds_at_pause(self) -> Optional[float]:
        """Return the seconds remaining on the clock at the moment of pause."""
        return self.remaining_seconds_at_pause

    def as_dict(self) -> dict:
        """Return a plain dictionary representation (Pydantic model_dump)."""
        return self.model_dump()
