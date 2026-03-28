"""
Pilot model for WRMS — the base pilot record stored in the database.

Provides a Pydantic model and lightweight accessors used throughout the
session, group, and heat management pipeline.
"""
from typing import Optional

from pydantic import BaseModel


class Pilot(BaseModel):
    """A registered pilot with a unique name and optional country code."""

    pilot_id: int
    name: str
    country: Optional[str]

    def __init__(self, pilot_id: int, name: str, country: str = None):
        """
        Args:
            pilot_id: Database primary key.
            name:     Unique pilot callsign.
            country:  Optional two-letter country code.
        """
        super().__init__(pilot_id=pilot_id, name=name, country=country)

    def to_dict(self) -> dict:
        """Return a plain dictionary representation."""
        return self.model_dump()

    def get_pilot_id(self) -> int:
        """Return the pilot's database ID."""
        return self.pilot_id

    def get_name(self) -> str:
        """Return the pilot's callsign."""
        return self.name

    def get_country(self) -> Optional[str]:
        """Return the pilot's country code, or None if not set."""
        return self.country
