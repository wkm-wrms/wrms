"""
Session management for WRMS — the core state machine for a training session.

A Session holds the live race state: active pilots, group assignments, the
current and next heat, and the phase clock. It is kept in memory as a global
singleton and persisted to SQLite via database.py on every state change.

Module-level helpers get_session() / set_session() provide controlled access
to the singleton so other modules never import the private variable directly.
"""
import math
import uuid
from typing import Optional

from pydantic import BaseModel

from pilot import Pilot
from activepilot import ActivePilot
from group import Group
from heat import Heat


MAX_PILOTS_PER_GROUP = 4
ALLOWED_CHANNELS = ["R1", "R3", "R6", "R7"]


class Session(BaseModel):  # pylint: disable=too-many-instance-attributes
    """
    Live race session: pilots, group roster, heat state machine, and phase clock.

    Persistent fields (stored in DB via database.py):
        session_id, name, flight_duration_sec, prep_duration_sec, is_active,
        active_pilots, current_heat, current_heat_number, next_heat,
        next_heat_number, groups, current_group, current_group_index,
        next_group, next_group_index, current_phase, phase_before_pause.

    Transient fields (in-memory only, rebuilt on reload):
        _dirty_list, _archive_heats.
    """

    session_id: str
    name: str
    flight_duration_sec: int
    prep_duration_sec: int
    is_active: bool = False

    active_pilots: dict[int, ActivePilot] = {}
    current_heat: Optional[Heat] = None
    current_heat_number: Optional[int] = None
    next_heat: Optional[Heat] = None
    next_heat_number: Optional[int] = None
    groups: list[Group] = []
    current_group: Optional[Group] = None
    current_group_index: Optional[int] = None
    next_group: Optional[Group] = None
    next_group_index: Optional[int] = None
    current_phase: str = "IDLE"   # IDLE, PREP, FLIGHT, PAUSED, FINISHED
    phase_before_pause: Optional[str] = None
    timer_running: bool = False
    _dirty_list: dict[str, bool] = {}
    _archive_heats: list[Heat] = []

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,dangerous-default-value
        self,
        name: str,
        flight_duration_sec: int,
        prep_duration_sec: int,
        session_id: str = None,
        is_active: bool = False,
        active_pilots: dict[int, ActivePilot] = {},
        current_heat: Heat = None,
        next_heat: Heat = None,
        current_heat_number: Optional[int] = None,
        next_heat_number: Optional[int] = None,
        groups: list[Group] = [],
        current_group: Group = None,
        current_group_index: int = None,
        next_group: Group = None,
        next_group_index: int = None,
        current_phase: str = "IDLE",
        phase_before_pause: str = "PREP",
    ):
        """
        Create a Session, auto-generating a UUID when session_id is omitted.

        Args:
            name:                 Human-readable session name.
            flight_duration_sec:  Flight phase duration for each heat (seconds).
            prep_duration_sec:    Preparation phase duration for each heat (seconds).
            session_id:           Existing UUID; generated automatically if None.
            is_active:            Whether the session has been started.
            active_pilots:        Map of pilot_id → ActivePilot.
            current_heat:         The heat currently running.
            next_heat:            The heat queued after the current one.
            current_heat_number:  Sequential number of the current heat.
            next_heat_number:     Sequential number of the next heat.
            groups:               Ordered list of training groups.
            current_group:        Group assigned to the current heat.
            current_group_index:  0-based index of current_group in groups.
            next_group:           Group assigned to the next heat.
            next_group_index:     0-based index of next_group in groups.
            current_phase:        High-level phase of the session (default 'IDLE').
            phase_before_pause:   Phase to return to on resume (default 'PREP').
        """
        session_id = str(uuid.uuid4()) if session_id is None else session_id
        super().__init__(
            name=name,
            flight_duration_sec=flight_duration_sec,
            prep_duration_sec=prep_duration_sec,
            session_id=session_id,
            is_active=is_active,
            active_pilots=active_pilots,
            current_heat=current_heat,
            next_heat=next_heat,
            current_heat_number=current_heat_number,
            next_heat_number=next_heat_number,
            groups=groups,
            current_group=current_group,
            current_group_index=current_group_index,
            next_group=next_group,
            next_group_index=next_group_index,
            current_phase=current_phase,
            phase_before_pause=phase_before_pause,
        )

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def is_session_active(self) -> bool:
        """Return True if the session has been started."""
        return self.is_active

    def dirty_list(self) -> list[str]:
        """Return list of field keys that have unsaved changes."""
        return [key for key, value in self._dirty_list.items() if value]

    def clean_dirty(self, key: str):
        """Mark a field key as saved (no pending changes)."""
        self._dirty_list[key] = False

    def loop(self) -> bool:
        """
        Advance the heat state machine by one step if a timer has expired.

        Called by the HTTP middleware on every request. Handles exactly one
        transition per call:
          - PREP timer expired  → start_flight() on current heat
          - FLIGHT timer expired → rotate_heats() (archive current, advance to next)

        Returns:
            True if a transition occurred (caller should persist to DB), else False.
        """
        if self.current_phase != "FLIGHT":
            return False
        if self.current_heat.get_remaining_seconds() <= 0:
            if self.current_heat.get_status() == "PREP":
                self.current_heat.start_flight()
            else:
                self.rotate_heats()
            return True
        return False

    def start(self) -> dict:
        """
        Start the session: set up heat #1 and #2, begin PREP phase.

        Returns:
            Dict with status 'ok' and snapshot of initial session state.

        Raises:
            ValueError: If the session is already active or has no pilots.
        """
        if self.is_active:
            raise ValueError("Session is already active.")
        if len(self.active_pilots) == 0:
            raise ValueError(
                "No pilots. Add at least one pilot before starting the session."
            )
        self.current_heat_number = 1
        self.current_group_index = 0
        self.current_group = self.groups[0]
        self.next_heat_number = 2

        self.current_heat = self.create_heat(group=self.groups[0], heat_number=1)
        print(f"Heat: {self.current_heat}")

        self.next_group_index = 1 % len(self.groups)
        self.next_group = self.groups[self.next_group_index]
        self.next_heat = self.create_heat(
            group=self.next_group, heat_number=self.next_heat_number
        )

        self.current_heat.start_prep()
        self.is_active = True
        self.current_phase = "FLIGHT"
        return {
            "status": "ok",
            "id": self.session_id,
            "name": self.name,
            "message": "Session started.",
            "current_phase": self.current_phase,
            "current_heat": self.current_heat,
            "next_heat": self.next_heat,
            "groups": self.groups,
            "current_group": self.current_group,
            "phase_before_pause": self.phase_before_pause,
        }

    def stop(self):
        """Stop the session by setting current_phase to FINISHED."""
        self.current_phase = 'FINISHED'

    def pause(self):
        """
        Pause the active session and its current heat.

        Works during both PREP and FLIGHT phases of the current heat.

        Raises:
            ValueError: If the session is not running or no pausable heat is active.
        """
        if self.current_phase != 'FLIGHT':
            raise ValueError("Cannot pause: session is not running.")
        if not self.current_heat or self.current_heat.status not in ('PREP', 'FLIGHT'):
            raise ValueError("No pausable heat active.")
        self.phase_before_pause = self.current_phase
        self.current_heat.pause()
        self.current_phase = 'PAUSED'

    def resume(self):
        """
        Resume a paused session and its current heat.

        Raises:
            ValueError: If the session is not currently paused.
        """
        if self.current_phase != 'PAUSED':
            raise ValueError("Cannot resume: session is not paused.")
        self.current_heat.resume()
        self.current_phase = self.phase_before_pause or 'FLIGHT'

    # ------------------------------------------------------------------
    # Pilot management
    # ------------------------------------------------------------------

    def add_pilot(self, pilot: Pilot, vtx: str):
        """
        Add a pilot to the active pilot roster (no-op if already present).

        Args:
            pilot: The Pilot to add.
            vtx:   VTX type string (e.g. 'Analog', 'DJI').
        """
        if pilot.pilot_id not in self.active_pilots:
            self.active_pilots[pilot.pilot_id] = ActivePilot(pilot, vtx)

    def remove_pilot(self, pilot_id: int):
        """
        Remove a pilot from the active roster and any group channel they occupy.

        Uses a two-pass approach to avoid mutating the channels dict during
        iteration: first locate the channel, then pop it.

        Args:
            pilot_id: ID of the pilot to remove.
        """
        if pilot_id in self.active_pilots:
            self.active_pilots.pop(pilot_id)
        for group in self.groups:
            ch_to_pop = None
            for ch in group.channels.keys():
                if group.channels[ch].pilot_id == pilot_id:
                    ch_to_pop = ch
                    break
            if ch_to_pop:
                group.channels.pop(ch_to_pop)

    # ------------------------------------------------------------------
    # Heat management
    # ------------------------------------------------------------------

    def rotate_heats(self):
        """
        Archive the current heat and advance to the next one in the rotation.

        Algorithm:
          1. Ensure next_heat exists (create on demand if missing).
          2. Finish and archive the current heat.
          3. Promote next_heat → current_heat, advance group index (round-robin).
          4. Pre-create a new next_heat for the following rotation.
          5. Start PREP on the newly promoted current heat.
        """
        if self.current_heat_number is None or self.current_heat_number < 0:
            self.current_heat_number = 1

        # Pre-create next_heat if it was consumed or never existed
        if not self.next_heat:
            self.next_group_index = (self.current_group_index + 1) % len(self.groups)
            self.next_heat_number = self.current_heat_number + 1
            self.next_group = self.groups[self.next_group_index]
            self.next_heat = self.create_heat(
                group=self.next_group, heat_number=self.next_heat_number
            )

        # Archive the current heat
        if self.current_heat:
            self.current_heat.finish()
            self.archive_heat(self.current_heat)

        # Emergency fallback — should not normally be reached
        if not self.next_heat:
            idx = (self.current_group_index + 1) % len(self.groups)
            self.next_heat = self.create_heat(
                self.groups[idx], self.current_heat_number + 1
            )

        # Promote next → current
        self.current_heat = self.next_heat
        self.current_heat_number = self.next_heat_number
        self.current_group_index = self.next_group_index
        self.current_group = self.next_group

        # Advance pointers for the next rotation (round-robin over groups)
        self.next_heat_number += 1
        self.next_group_index = (self.next_group_index + 1) % len(self.groups)
        self.next_group = self.groups[self.next_group_index]
        self.next_heat = self.create_heat(
            group=self.groups[self.next_group_index],
            heat_number=self.next_heat_number,
        )

        self.current_heat.start_prep()

    def archive_heat(self, heat: Heat):
        """
        Add a finished heat to the pending-archive queue.

        The queue is drained by the HTTP middleware which persists each entry
        to the database.

        Args:
            heat: The finished Heat to archive.
        """
        self._archive_heats.append(heat)
        self._dirty_list["archive_heats"] = True

    def skip_current_heat(self):
        """
        Manually skip the current heat and advance to the next group.

        Raises:
            ValueError: If there is no active heat to skip.
        """
        if not self.is_active or not self.current_heat:
            raise ValueError("No active heat to skip.")
        self.rotate_heats()

    def pop_archived_heat(self) -> Optional[Heat]:
        """
        Remove and return the most recently archived heat, or None if none pending.

        Used by the HTTP middleware and skip_heat endpoint to drain the archive
        queue and persist finished heats to the database.

        Returns:
            The most recently archived Heat, or None if the queue is empty.
        """
        return self._archive_heats.pop() if self._archive_heats else None

    def get_archive_heat(self) -> Heat:
        """
        Remove and return the most recently archived heat (raises if empty).

        Returns:
            The most recently archived Heat.
        """
        return self._archive_heats.pop()

    def create_heat(self, group: Group, heat_number: int) -> Heat:
        """
        Create a new Heat as a snapshot of the given group.

        The channels dict is copied so later group edits don't affect the heat.

        Args:
            group:       Source group whose roster is snapshotted.
            heat_number: Sequential number for the new heat.

        Returns:
            A new Heat in PLANNED status.
        """
        return Heat(
            session_id=self.session_id,
            heat_number=heat_number,
            group_sequence=group.group_sequence,
            channels=group.channels.copy(),
            prep_time=self.prep_duration_sec,
            flight_time=self.flight_duration_sec,
        )

    # ------------------------------------------------------------------
    # Group management
    # ------------------------------------------------------------------

    def move_pilot(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-return-statements
        self,
        pilot_id: int,
        from_channel: str,
        from_group: int,
        to_channel: str,
        to_group: int,
    ) -> dict:
        """
        Move a pilot between channels/groups, or to/from the unassigned pool.

        Negative group indices (< 0) are treated as paddock (unassigned).
        group values use 1-based UI sequences; they are decremented internally
        before indexing into self.groups.

        If the destination channel is occupied, the displaced pilot is silently
        returned to the paddock (no error).

        Args:
            pilot_id:     ID of the pilot to move.
            from_channel: Source channel key (e.g. 'R1'), or None for paddock.
            from_group:   1-based source group sequence, or None for paddock.
            to_channel:   Destination channel key, or None (paddock move).
            to_group:     1-based destination group sequence, or None for paddock.

        Returns:
            Dict with 'status': 'ok' and updated groups, or 'status': 'error'.
        """
        # Normalise paddock sentinel (negative → None)
        if from_group is not None and from_group < 0:
            from_group = None
        if to_group is not None and to_group < 0:
            to_group = None

        # Convert 1-based UI sequence to 0-based list index
        if from_group is not None:
            from_group -= 1
        if to_group is not None:
            to_group -= 1

        if pilot_id not in self.active_pilots:
            return {"status": "error", "message": "Pilot is not active in this session."}

        if (from_group is not None or to_group is not None) and not self.groups:
            return {"status": "error", "message": "No groups defined."}

        if from_group is not None and not 0 <= from_group < len(self.groups):
            return {"status": "error", "message": "Invalid source group."}
        if to_group is not None and not 0 <= to_group < len(self.groups):
            return {"status": "error", "message": "Invalid destination group."}

        for ch in [from_channel, to_channel]:
            if ch is not None and ch not in ALLOWED_CHANNELS:
                return {"status": "error", "message": f"Invalid channel: {ch}"}

        if from_channel is not None and from_group is not None:
            group = self.groups[from_group]
            if (from_channel not in group.channels
                    or group.channels[from_channel].pilot_id != pilot_id):
                return {"status": "error", "message": "Pilot is not at the specified source slot."}

        if to_group is not None and to_channel is None:
            return {
                "status": "error",
                "message": "A channel must be specified for the destination group.",
            }

        pilot: ActivePilot = self.active_pilots[pilot_id]

        # 1. Remove from source slot
        if from_group is not None and from_channel in self.groups[from_group].channels:
            del self.groups[from_group].channels[from_channel]

        # 2. Place in destination slot (displaces any existing occupant to paddock)
        if to_group is not None and to_channel is not None:
            self.groups[to_group].channels[to_channel] = pilot

        self._dirty_list["groups"] = True
        return {"status": "ok", "groups": self.groups}

    def add_new_group(self) -> dict:
        """
        Append a new empty group to the session roster.

        Returns:
            Dict with 'status': 'ok' and updated groups list.
        """
        if self.groups is None:
            self.groups = []
        seq = len(self.groups) + 1
        self.groups.append(Group(group_sequence=seq, channels={}))
        self._dirty_list["groups"] = True
        return {"status": "ok", "groups": self.groups}

    def remove_group(self, group_sequence: int) -> dict:
        """
        Remove a group by its 1-based sequence number.

        Renumbers all groups with higher sequence numbers to keep the list
        contiguous.

        Args:
            group_sequence: 1-based sequence of the group to remove.

        Returns:
            Dict with 'status': 'ok' or 'error'.
        """
        if self.groups is None:
            return {"status": "error", "message": "No groups defined."}
        if group_sequence < 1 or group_sequence > len(self.groups):
            return {"status": "error", "message": "Invalid group sequence number."}
        # Decrement sequence of all groups after the removed one
        index = group_sequence
        while index < len(self.groups):
            self.groups[index].group_sequence -= 1
            index += 1
        self.groups.pop(group_sequence - 1)
        self._dirty_list["groups"] = True
        return {"status": "ok", "groups": self.groups}

    def rebalance_groups(self):
        """
        Partition active pilots into balanced groups and assign channels.

        Algorithm (Matchmaking 2.0):
          1. Compute number of groups: ceil(n / MAX_PILOTS_PER_GROUP).
          2. Sort all pilots digital-first (then by score desc) so early groups
             fill with digital pilots, maximising homogeneous groups.
          3. Distribute pilots as evenly as possible (floor+1 for early groups).
          4. Within each group assign digital pilots to high channels (R7, R6, …)
             and analog pilots to low channels (R1, R3, …), each tier sorted by
             total_score() descending so higher score → higher channel number.

        Result is stored in self.groups; _dirty_list['groups'] is set so the
        caller knows to persist.
        """
        total_pilots = len(self.active_pilots)
        if total_pilots == 0:
            self.groups = []
            return

        num_groups = math.ceil(total_pilots / MAX_PILOTS_PER_GROUP)
        base_size = total_pilots // num_groups
        remainder = total_pilots % num_groups  # first `remainder` groups get +1 pilot

        # Phase 2: digital-first, then by score descending within each cohort.
        active_pilots_array = sorted(
            self.active_pilots.values(),
            key=lambda p: (0 if p.is_digital else 1, -p.total_score())
        )

        self.groups = []
        pilot_index = 0

        for i in range(num_groups):
            current_group_size = base_size + 1 if i < remainder else base_size
            group_pilots = active_pilots_array[pilot_index: pilot_index + current_group_size]

            channels: dict[str, ActivePilot] = {}
            analog_idx = 0
            digital_idx = len(ALLOWED_CHANNELS) - 1

            # Phase 4: digital pilots → high channels, sorted by score desc.
            digital_sorted = sorted(
                [p for p in group_pilots if p.is_digital],
                key=lambda p: p.total_score(), reverse=True
            )
            for pilot in digital_sorted:
                channels[ALLOWED_CHANNELS[digital_idx]] = pilot
                digital_idx -= 1

            # Phase 4: analog pilots → low channels, sorted by score asc.
            # Ascending order means lowest score fills R1, highest score fills
            # the highest available channel (R3 in mixed groups, R7 in all-analog).
            analog_sorted = sorted(
                [p for p in group_pilots if not p.is_digital],
                key=lambda p: p.total_score()
            )
            for pilot in analog_sorted:
                channels[ALLOWED_CHANNELS[analog_idx]] = pilot
                analog_idx += 1

            self.groups.append(Group(
                group_sequence=i + 1,
                channels=channels,
            ))
            pilot_index += current_group_size

        self._dirty_list["groups"] = True
        print(
            "Balanced groups: "
            + str([{'seq': g.group_sequence, 'channels': g.channels} for g in self.groups])
        )


# ---------------------------------------------------------------------------
# Module-level session singleton
# ---------------------------------------------------------------------------

_current_session: Session = None  # pylint: disable=invalid-name


def get_session() -> Session:
    """
    Return the current in-memory session singleton, or None if no session is set.

    This is the only intended access point for the session from other modules.
    """
    return _current_session


def set_session(session: Session):
    """
    Replace the current in-memory session singleton.

    Args:
        session: The new Session to activate, or None to clear.
    """
    global _current_session  # pylint: disable=global-statement
    _current_session = session
