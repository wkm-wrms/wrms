from typing import Optional
from pydantic import BaseModel
"""
Pilot data models and classes for the WRMS (WKM Racing Management System).
This module provides Pydantic-based models and wrapper classes for pilot information,
including unique identifiers, names, and country codes. It serves as the core
representation of a pilot throughout the session, group, and heat management processes.
"""


class Pilot(BaseModel):
    pilot_id: int
    name: str
    country: Optional[str]

    def __init__(self, pilot_id: int, name: str, country: str = None):
        super().__init__(pilot_id=pilot_id, name=name, country=country)

    def to_dict(self):
        return self.model_dump()

    def get_pilot_id(self):
        return self.pilot_id

    def get_name(self):
        return self.name

    def get_country(self):
        return self.country
