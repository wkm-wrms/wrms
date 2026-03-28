"""
Session management module for race session state and configuration.
This module provides the Session class for managing race session lifecycle, including
persistent data storage (session metadata, pilots, heats, groups) and runtime state
(timer status, current phase, transient data). Sessions can be loaded from and saved to
a database with optional auto-saving on state changes.
"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
import json
import uuid
import math

from pilot import Pilot
from activepilot import ActivePilot
from group import Group
from heat import Heat


MAX_PILOTS_PER_GROUP = 4
ALLOWED_CHANNELS = ["R1", "R3", "R6", "R7"]


class Session(BaseModel):
    """
    Session class for managing race session state and configuration.
    The Session class maintains both persistent session data (stored in database) and
    runtime state. Persistent data includes session metadata, pilot information, heat
    schedules, and group assignments. Runtime state includes timer status, current phase,
    and other transient information used during active sessions.
    """

    # Permanent session state stored in DB, loaded on demand.
    # Changes are saved immediately (auto_save) or on demand (manual save)
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
    current_phase: str = "IDLE"  # IDLE, PREP, FLIGHT, PAUSED
    phase_before_pause: Optional[str] = None
    timer_running: bool = False
    _dirty_list: dict[str, bool] = {}
    _archive_heats: list[Heat] = []

    def __init__(self, name: str, flight_duration_sec: int, prep_duration_sec: int,
                 session_id: str = None,       is_active: bool = False,
                 active_pilots: dict[int, ActivePilot] = {},
                 current_heat: Heat = None, next_heat: Heat = None,
                 current_heat_number: Optional[int] = None, next_heat_number: Optional[int] = None,
                 groups: list[Group] = [],
                 current_group: Group = None, current_group_index: int = None,
                 next_group: Group = None, next_group_index: int = None,
                 current_phase="IDLE", phase_before_pause="PREP"):
        """ Create instance of Session"""
        session_id = str(
            uuid.uuid4()) if session_id is None else session_id
        super().__init__(
            name=name, flight_duration_sec=flight_duration_sec,  prep_duration_sec=prep_duration_sec,
            session_id=session_id, is_active=is_active,
            active_pilots=active_pilots,
            current_heat=current_heat, next_heat=next_heat,
            current_heat_number=current_heat_number, next_heat_number=next_heat_number,
            groups=groups,
            current_group=current_group, current_group_index=current_group_index,
            next_group=next_group, next_group_index=next_group_index,
            current_phase=current_phase, phase_before_pause=phase_before_pause)

    def is_session_active(self) -> bool:
        """Zwraca informację, czy sesja została już rozpoczęta."""
        return self.is_active

    def dirty_list(self):
        return [key for key, value in self._dirty_list.items() if value]

    def clean_dirty(self, key):
        self._dirty_list[key] = False

    def loop(self):
        if self.current_phase != "FLIGHT":
            return False
        if self.current_heat.get_remaining_seconds() <= 0:
            if self.current_heat.get_status() == "PREP":
                self.current_heat.start_flight()
            else:
                self.rotate_heats()
            return True
        return False

    def start(self):
        """ Start session and make it active"""
        if self.is_active:
            raise ValueError("Sesja już trwa.")
        if len(self.active_pilots) == 0:
            raise ValueError(
                "Brak pilotów. Dodaj co najmniej jednego pilota przed startem sesji.")
        self.current_heat_number = 1
        self.current_group_index = 0
        self.current_group = self.groups[0]
        self.next_heat_number = 2

        # Tworzymy bieg jako snapshot pierwszej grupy
        self.current_heat = self.create_heat(
            group=self.groups[0],
            heat_number=1
        )
        print(f"Heat: {self.current_heat}")

        self.next_group_index = 1 % len(self.groups)
        self.next_group = self.groups[self.next_group_index]

        self.next_heat = self.create_heat(
            group=self.next_group, heat_number=self.next_heat_number)

        self.current_heat.start_prep()
        self.is_active = True
        self.current_phase = "FLIGHT"
        return {
            "status": "ok",
            "id": self.session_id,
            "name": self.name,
            "message": "Sesja rozpoczęta",
            "current_phase": self.current_phase,
            "current_heat": self.current_heat,
            "next_heat": self.next_heat,
            "groups": self.groups,
            "current_group": self.current_group,
            "phase_before_pause": self.phase_before_pause

        }

    def stop(self):
        self.current_phase = 'FINISHED'

    def pause(self):
        """Wstrzymuje aktualny bieg i całą sesję"""
        raise NotImplementedError(
            "Metoda pause nie jest jeszcze zaimplementowana.")

#
#
# Pilot Management
#
#

    def add_pilot(self, pilot: Pilot, vtx: str):
        """ Adds a pilot to the session's list of active pilots and triggers auto-saving if enabled.
        This method checks if the pilot is already in the list of active pilots to prevent duplicates. If the pilot is not already active, it adds the pilot to the list and ensures that the change is persisted to the database if auto-saving is configured. It should be called whenever a new pilot needs to be added to the session.
        """
        if not pilot.pilot_id in self.active_pilots:
            self.active_pilots[pilot.pilot_id] = ActivePilot(pilot, vtx)

    def remove_pilot(self, pilot_id: int):
        """
        Removes a pilot from the session's list of active pilots by their ID and triggers auto-saving if enabled.
        This method filters the list of active pilots to exclude the pilot with the specified ID. If the pilot is found and removed, it ensures that the change is persisted to the database if auto-saving is configured. It should be called whenever a pilot needs to be removed from the session.
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
#
#
# Heats Management
#
#

    def rotate_heats(self):

        if self.current_heat_number is None or self.current_heat_number < 0:
            self.current_heat_number = 1
        if not self.next_heat:
            self.next_group_index = (
                self.current_group_index+1) % len(self.groups)
            self.next_heat_number = self.current_heat_number + 1
            self.next_group = self.groups[self.next_group_index]
            self.next_heat = self.create_heat(group=self.next_group,
                                              heat_number=self.next_heat_number)

        if self.current_heat:
            self.current_heat.finish()
            self.archive_heat(self.current_heat)

        if not self.next_heat:
            # Awaryjne generowanie jeśli nie było zaplanowanego
            idx = (self.current_group_index + 1) % len(self.groups)
            self.next_heat = self.create_heat(
                self.groups[idx], self.current_heat_number + 1)

        self.current_heat = self.next_heat
        self.current_heat_number = self.next_heat_number
        self.current_group_index = self.next_group_index
        self.current_group = self.next_group

        self.next_heat_number += 1
        self.next_group_index = (
            self.next_group_index+1) % len(self.groups)
        self.next_group = self.groups[self.next_group_index]

        self.next_heat = self.create_heat(
            group=self.groups[self.next_group_index],
            heat_number=self.next_heat_number
        )
        self.current_heat.start_prep()

    def archive_heat(self, heat: Heat):
        self._archive_heats.append(heat)
        self._dirty_list["archive_heats"] = True

    def skip_current_heat(self):
        """
        Manualnie przeskakuje do następnego biegu.
        Kończy obecny bieg i wymusza rotację na następny w kolejce.
        """
        if not self.is_active or not self.current_heat:
            raise ValueError("Brak aktywnego biegu do pominięcia.")
        self.rotate_heats()

    def get_archive_heat(self):
        return self._archive_heats.pop()

    def create_heat(self, group: Group, heat_number: int):
        """ Creates the next heat for the session based on the provided group and triggers auto-saving if enabled.
        This method initializes a new Heat object using the pilots from the specified group and sets it as the next heat to be contested. It ensures that the change is persisted to the database if auto-saving is configured. It should be called whenever a new heat needs to be planned based on a group of pilots.
        """
        return Heat(
            session_id=self.session_id,
            heat_number=heat_number,
            group_id=group.group_id,
            channels=group.channels.copy(),  # KLUCZOWE: snapshot rosteru
            prep_time=self.prep_duration_sec,
            flight_time=self.flight_duration_sec
        )

    def move_pilot(self, pilot_id: int, from_channel: str, from_group: int, to_channel: str, to_group: int):

        # Specyficzna obsluga paddocka (unassigned pilots)
        if from_group is not None and from_group < 0:
            from_group = None
        if to_group is not None and to_group < 0:
            to_group = None

        # UI uzywa group_sequence (1-based). Zmniejszmy o 1 dla indeksowania listy
        if from_group is not None:
            from_group -= 1
        if to_group is not None:
            to_group -= 1

        if pilot_id not in self.active_pilots:
            return {"status": "error", "message": "Pilot nie jest aktywny"}

        # Walidacja istnienia grup i zakresów
        if (from_group is not None or to_group is not None) and not self.groups:
            return {"status": "error", "message": "Brak zdefiniowanych grup"}

        if from_group is not None and (from_group < 0 or from_group >= len(self.groups)):
            return {"status": "error", "message": "Niepoprawna grupa źródłowa"}
        if to_group is not None and (to_group < 0 or to_group >= len(self.groups)):
            return {"status": "error", "message": "Niepoprawna grupa docelowa"}

        # Walidacja kanałów
        for ch in [from_channel, to_channel]:
            if ch is not None and ch not in ALLOWED_CHANNELS:
                return {"status": "error", "message": f"Niepoprawny kanał: {ch}"}

        if from_channel is not None and from_group is not None:
            group = self.groups[from_group]
            if from_channel not in group.channels or group.channels[from_channel].pilot_id != pilot_id:
                return {"status": "error", "message": "Pilot nie znajduje się na wskazanej pozycji źródłowej"}

        # Sprawdzenie kolizji w miejscu docelowym
        if to_group is not None:
            if to_channel is None:
                return {"status": "error", "message": "Należy wskazać kanał dla docelowej grupy"}

        pilot: ActivePilot = self.active_pilots[pilot_id]

        # Logika przenoszenia:

        # 1. Usuwamy pilota z poprzedniego miejsca (jeśli je posiadał)
        if from_group is not None and from_channel in self.groups[from_group].channels:
            del self.groups[from_group].channels[from_channel]

        # 2. Wstawiamy pilota w nowe miejsce.
        # Jeśli to_channel był zajęty, poprzedni pilot zostaje nadpisany i automatycznie "spada" do paddocku.
        if to_group is not None and to_channel is not None:
            self.groups[to_group].channels[to_channel] = pilot

        self._dirty_list["groups"] = True
        return {"status": "ok", "groups": self.groups}

    def add_new_group(self):
        if self.groups is None:
            self.groups = []
        self.groups.append(Group(group_id=len(self.groups)+1,  channels={},
                           group_sequence=len(self.groups)+1))

        self._dirty_list["groups"] = True
        return {"status": "ok", "groups": self.groups}

    def remove_group(self, group_sequence: int):
        if self.groups is None:
            return {"status": "error", "message": "Brak grup"}
        if group_sequence < 1 or group_sequence > len(self.groups):
            return {"status": "error", "message": "Niepoprawna grupa"}
        index = group_sequence
        while index < len(self.groups):
            self.groups[index].group_sequence -= 1
            index += 1
        self.groups.pop(group_sequence-1)
        self._dirty_list["groups"] = True
        return {"status": "ok", "groups": self.groups}

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
            active_pilots_array = [p for p in self.active_pilots.values()]
            group_pilots = active_pilots_array[pilot_index: pilot_index +
                                               current_group_size]

            channels = {}
            analog_idx = 0
            digital_idx = len(ALLOWED_CHANNELS) - 1

            # cyfry dostają wysokie kanały
            for pilot in [p for p in group_pilots if p.is_digital]:
                channels[ALLOWED_CHANNELS[digital_idx]] = pilot
                digital_idx -= 1

            # analogi dostają niskie kanały
            for pilot in [p for p in group_pilots if not p.is_digital]:
                channels[ALLOWED_CHANNELS[analog_idx]] = pilot
                analog_idx += 1

            self.groups.append(Group(
                group_id=i + 1,
                channels=channels,
                group_sequence=i+1
            ))

            pilot_index += current_group_size
        self._dirty_list["groups"] = True
        print(
            f"Zbalansowane grupy: {[{'id': g.group_id,  'channels': g.channels} for g in self.groups]}")


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
