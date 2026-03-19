"""
Session management module for race session state and configuration.
This module provides the Session class for managing race session lifecycle, including
persistent data storage (session metadata, pilots, heats, groups) and runtime state
(timer status, current phase, transient data). Sessions can be loaded from and saved to
a database with optional auto-saving on state changes.
"""
from datetime import datetime
import uuid
import math

from pilot import Pilot
from group import Group
from heat import Heat


MAX_PILOTS_PER_GROUP = 4
ALLOWED_CHANNELS = ["R1", "R3", "R6", "R7"]


class ActivePilot:
    pilot: Pilot
    vtx: str
    is_digital: bool

    def __init__(self, pilot: Pilot, vtx: str):
        self.pilot = pilot
        self.vtx = vtx
        self.is_digital = False if vtx == "Analog" else True


class Session:
    """
    Session class for managing race session state and configuration.
    The Session class maintains both persistent session data (stored in database) and
    runtime state. Persistent data includes session metadata, pilot information, heat
    schedules, and group assignments. Runtime state includes timer status, current phase,
    and other transient information used during active sessions.
    Attributes:
        id (str): Unique identifier for the session
        name (str): Display name of the session
        flight_duration_sec (int): Duration of each flight in seconds
        prep_duration_sec (int): Duration of preparation phase in seconds
        is_active (bool): Whether the session is currently active
        active_pilots (List[Pilot]): List of pilots participating in the session
        current_heat (Heat): The heat currently being contested
        next_heat (Heat): The next heat to be contested
        groups (List[Group]): List of pilot groups for the session
        current_group (Group): The group currently competing
        timer_running (bool): Whether the session timer is currently running
        current_phase (str): Current phase of the session (IDLE, PREP, FLIGHT, PAUSED)
        phase_before_pause (str): The phase that was active before pause
    Methods for session lifecycle: load_from_db, save, autosave
    Methods for configuration: set_name, set_flight_duration, set_prep_duration
    Methods for pilot management: add_pilot, remove_pilot, get_active_pilots
    Methods for heat management: create_next_heat, set_last_heat_as_current, set_current_heat, get_current_heat, get_next_heat
    Methods for group management: set_groups, get_groups, set_current_group, get_current_group
    Methods for phase and timer management: set_current_phase, get_current_phase, set_phase_before_pause, get_phase_before_pause, set_timer_running, is_timer_running, set_timer_start_time, get_timer_start_time
    """

    # Permanent session state stored in DB, loaded on demand.
    # Changes are saved immediately (auto_save) or on demand (manual save)
    id: str
    name: str = None
    flight_duration_sec: int = None
    prep_duration_sec: int = None
    is_active: bool = False
    active_pilots: list[ActivePilot] = None
    current_heat: Heat = None
    next_heat: Heat = None
    groups: list[Pilot] = None
    current_group: Group = None
    timer_running: bool = False
    timer_start_time: datetime = None
    current_phase: str = "IDLE"  # IDLE, PREP, FLIGHT, PAUSED
    phase_before_pause: str = "PREP"

    def __init__(self, name: str, flight_duration_sec: int, prep_duration_sec: int,
                 id: str = None,
                 is_active: bool = False,
                 active_pilots: list[ActivePilot] = [],
                 current_heat: Heat = None,
                 next_heat: Heat = None,
                 groups: list[Pilot] = [],
                 current_group: Group = None,
                 timer_running=False,
                 timer_start_time: datetime = None,
                 current_phase="IDLE",
                 phase_before_pause="PREP"):
        """ Create instance of Session"""
        self.id = str(uuid.uuid4()) if id is None else id
        self.name = name
        self.flight_duration_sec = flight_duration_sec
        self.prep_duration_sec = prep_duration_sec
        self.is_active = is_active
        self.active_pilots = active_pilots
        self.current_heat = current_heat
        self.next_heat = next_heat
        self.groups = groups
        self.current_group = current_group
        self.timer_running = timer_running
        self.timer_start_time = timer_start_time
        self.current_phase = current_phase  # IDLE, PREP, FLIGHT, PAUSED
        self.phase_before_pause = phase_before_pause

    def to_json(self):
        """ Custom JSON serialization method for the Session object. 
        This method defines how the Session object should be converted to a JSON-compatible format, including all relevant attributes and related data such as pilots, groups, and heats. It is used when saving the session state to the database or when transmitting session data over a network.
        """
        return {
            "id": self.id,
            "name": self.name,
            "flight_duration_sec": self.flight_duration_sec,
            "prep_duration_sec": self.prep_duration_sec,
            "is_active": self.is_active,
            "active_pilots": [pilot.__json__() for pilot in self.active_pilots],
            "current_heat": self.current_heat.__json__() if self.current_heat else None,
            "next_heat": self.next_heat.__json__() if self.next_heat else None,
            "groups": [group.__json__() for group in self.groups],
            "current_group": self.current_group.__json__() if self.current_group else None,
            "timer_running": self.timer_running,
            "timer_start_time": self.timer_start_time.isoformat() if self.timer_start_time else None,
            "current_phase": self.current_phase,
            "phase_before_pause": self.phase_before_pause
        }

    def start(self):
        """ Start session and make it active"""
        if self.is_active:
            raise ValueError("Sesja już trwa.")
        if len(self.active_pilots) == 0:
            raise ValueError(
                "Brak pilotów. Dodaj co najmniej jednego pilota przed startem sesji.")
        self.start_timer()
        self.current_phase = "PREP"

    def stop(self):
        self.current_phase = 'FINISHED'

    def start_timer(self):
        """ Start timer """
        self.timer_start_time = datetime.now()
        self.timer_running = True

    def pause_timer(self):
        self.timer_running = False

    def add_pilot(self, pilot: Pilot, vtx: str):
        """ Adds a pilot to the session's list of active pilots and triggers auto-saving if enabled.
        This method checks if the pilot is already in the list of active pilots to prevent duplicates. If the pilot is not already active, it adds the pilot to the list and ensures that the change is persisted to the database if auto-saving is configured. It should be called whenever a new pilot needs to be added to the session.
        """
        if not any(p.pilot.id == pilot.id for p in self.active_pilots):
            self.active_pilots.append(ActivePilot(pilot, vtx))

    def remove_pilot(self, pilot_id: int):
        """ 
        Removes a pilot from the session's list of active pilots by their ID and triggers auto-saving if enabled.
        This method filters the list of active pilots to exclude the pilot with the specified ID. If the pilot is found and removed, it ensures that the change is persisted to the database if auto-saving is configured. It should be called whenever a pilot needs to be removed from the session.
        """
        before = len(self.active_pilots)
        self.active_pilots = [
            p for p in self.active_pilots if p.pilot.id != pilot_id]

    def create_next_heat(self, group: Group):
        """ Creates the next heat for the session based on the provided group and triggers auto-saving if enabled.
        This method initializes a new Heat object using the pilots from the specified group and sets it as the next heat to be contested. It ensures that the change is persisted to the database if auto-saving is configured. It should be called whenever a new heat needs to be planned based on a group of pilots.
        """
        self.next_heat = Heat(group=group, pilots=group.pilots)

    def set_last_heat_as_current(self):
        """ Sets the last planned heat as the current heat and triggers auto-saving if enabled.
        This method updates the session's current heat to be the same as the next heat that was planned. It ensures that the change is persisted to the database if auto-saving is configured. It should be called when transitioning from the preparation phase to the flight phase, or whenever the next heat becomes the current heat for competition.
        """
        self.current_heat = self.next_heat
        self.next_heat = None

    def set_current_heat(self, heat: Heat):
        """ Sets the current heat for the session and triggers auto-saving if enabled.
        This method updates the session's current heat attribute and ensures that the change is persisted to the database if auto-saving is configured. It should be called whenever the current heat needs to be changed.
        """
        self.current_heat = heat

    def get_name(self):
        """ Returns the display name of the session.        """
        return self.name

    def get_flight_duration(self):
        """ Returns the flight duration for the session in seconds.        """
        return self.flight_duration_sec

    def get_prep_duration(self):
        """ Returns the preparation duration for the session in seconds.        """
        return self.prep_duration_sec

    def is_session_active(self):
        """ Returns whether the session is currently active.        """
        return self.is_active

    def get_active_pilots(self):
        """ Returns the list of active pilots participating in the session.        """
        return self.active_pilots

    def get_current_heat(self):
        """ Returns the current heat being contested in the session.        """
        return self.current_heat

    def get_next_heat(self):
        """ Returns the next heat to be contested in the session.        """
        return self.next_heat

    def get_groups(self):
        """ Returns the list of pilot groups for the session.        """
        return self.groups

    def set_groups(self, groups: list[Group]):
        """ Sets the list of pilot groups for the session and triggers auto-saving if enabled.
        """
        self.groups = groups

    def get_current_group(self):
        """ Returns the group currently competing in the session.        """
        return self.current_group

    def set_current_group(self, group: Group):
        """ Sets the group currently competing in the session and triggers auto-saving if enabled.
        """
        self.current_group = group

    def is_timer_running(self):
        """ Returns whether the timer is currently running for the session.        """
        return self.timer_running

    def set_timer_running(self, running: bool):
        """ Sets the timer running status for the session and triggers auto-saving if enabled. """
        self.timer_running = running

    def get_current_phase(self):
        """ Returns the current phase of the session (IDLE, PREP, FLIGHT, PAUSED).        """
        return self.current_phase

    def set_current_phase(self, phase: str):
        """ Sets the current phase of the session and triggers auto-saving if enabled.        """
        self.current_phase = phase

    def get_phase_before_pause(self):
        """ Returns the phase that was active before the session was paused.        """
        return self.phase_before_pause

    def set_phase_before_pause(self, phase: str):
        """ Sets the phase that was active before the session was paused and triggers auto-saving if enabled.        """
        self.phase_before_pause = phase

    def get_timer_start_time(self):
        """ Returns the start time of the session timer.    """
        return self.timer_start_time

    def set_timer_start_time(self, time: datetime):
        """ Sets the start time of the session timer and triggers auto-saving if enabled.        """
        self.timer_start_time = time

    def rebalance_groups(self):
        total_pilots = len(self.active_pilots)
        if total_pilots == 0:
            self.groups = []
            return

        num_groups = math.ceil(total_pilots / MAX_PILOTS_PER_GROUP)
        base_size = total_pilots // num_groups
        remainder = total_pilots % num_groups
        self.groups = []
        pilot_index = 0

        for i in range(num_groups):
            current_group_size = base_size + 1 if i < remainder else base_size
            group_pilots = self.active_pilots[pilot_index: pilot_index +
                                              current_group_size]

            channels = {}
            analog_idx = 0
            digital_idx = len(ALLOWED_CHANNELS) - 1

            # cyfry dostają wysokie kanały
            for pilot in [p.pilot for p in group_pilots if p.is_digital]:
                channels[ALLOWED_CHANNELS[digital_idx]] = pilot
                digital_idx -= 1

            # analogi dostają niskie kanały
            for pilot in [p.pilot for p in group_pilots if not p.is_digital]:
                channels[ALLOWED_CHANNELS[analog_idx]] = pilot
                analog_idx += 1

            self.groups.append(Group(
                id=i + 1,
                pilots=group_pilots,
                channels=channels,
                group_sequence=i+1
            ))

            pilot_index += current_group_size
        print(
            f"Zbalansowane grupy: {[{'id': g.id, 'pilots': [p.pilot.name for p in g.pilots], 'channels': g.channels} for g in self.groups]}")


current_session: Session = None


def get_session() -> Session:
    """ Returns the current active session. 
    This function provides a way to access the session state from other parts of the application, such as API routes or background tasks. It ensures that there is a single shared session instance that can be used throughout the application lifecycle. 
    """
    global current_session
    return current_session


def set_session(session: Session):
    """ Set current, global session"""
    global current_session
    current_session = session
