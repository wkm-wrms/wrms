from __future__ import annotations
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
import json

from pilot import ActivePilot
from database import RaceDatabase


class PilotEntry(BaseModel):
    pilot_id: int
    pilot: ActivePilot
    name: str
    vtx_type: str
    channel: Optional[str] = None


class Group(BaseModel):
    group_id: int
    slots: Dict[str, Optional[PilotEntry]] = {
        "R1": None, "R3": None, "R6": None, "R7": None
    }

    def add_pilot(self, pilot: AvtivePilot, channel: str):
        if channel in self.slots:
            self.slots[channel] = PilotEntry(
                pilot_id=pilot.id, name=pilot.name, vtx_type=pilot.vtx_type, channel=channel)
        else:
            raise ValueError(f"Nieprawidłowy kanał: {channel}")


class RosterState(BaseModel):
    unassigned: List[PilotEntry] = []
    groups: List[Group] = []
    version: int = 0


class Roster:
    def __init__(self, session_id: int, state: Optional[RosterState] = None, db: Optional[RaceDatabase] = None):
        self.session_id = session_id
        self._state = state or RosterState()

    @classmethod
    def from_db(cls, session_id: str, db_handler) -> Roster:
        """Pobiera najnowszą aktywną wersję z bazy."""
        data = db_handler.get_latest_roster(session_id)
        if data:
            state = RosterState.parse_raw(data['data_json'])
            return cls(session_id, state)
        return cls(session_id)

    def to_json(self) -> str:
        return self._state.json()

    def add_to_unassigned(self, pilot_id: int, name: str, vtx_type: str):
        entry = PilotEntry(pilot_id=pilot_id, name=name, vtx_type=vtx_type)
        self._state.unassigned.append(entry)

    def move_to_group(self, pilot_id: int, to_group_id: int, to_channel: str):
        # 1. Znajdź i usuń pilota z aktualnego miejsca (unassigned lub inna grupa)
        pilot = None
        for p in self._state.unassigned:
            if p.pilot_id == pilot_id:
                pilot = p
                self._state.unassigned.remove(p)
                break

        if not pilot:
            for g in self._state.groups:
                for ch, p in g.slots.items():
                    if p and p.pilot_id == pilot_id:
                        pilot = p
                        g.slots[ch] = None
                        break

        # 2. Wstaw do nowej grupy
        if pilot:
            pilot.channel = to_channel
            target_group = next(
                (g for g in self._state.groups if g.group_id == to_group_id), None)
            if not target_group:
                target_group = Group(group_id=to_group_id)
                self._state.groups.append(target_group)
            target_group.slots[to_channel] = pilot

    def rebalance(self):
        """Logika optymalizacji: wypełnia puste sloty i usuwa puste grupy."""
        # 1. Usuń puste grupy
        self._state.groups = [
            g for g in self._state.groups if any(g.slots.values())]

        # 2. Przenieś unassigned do wolnych slotów (prosty algorytm)
        channels = ["R1", "R3", "R6", "R7"]
        for g in self._state.groups:
            for ch in channels:
                if g.slots[ch] is None and self._state.unassigned:
                    pilot = self._state.unassigned.pop(0)
                    pilot.channel = ch
                    g.slots[ch] = pilot

    def save(self, db_handler):
        """Inwaliduje stare wersje i zapisuje nową."""
        self._state.version += 1
        db_handler.save_roster(
            self.session_id, self._state.version, self.to_json())
