

class Pilot:
    pilot_id: int
    name: str

    def __init__(self, pilot_id: int, name: str, country: str = ""):
        self.pilot_id = pilot_id
        self.name = name
        self.country = country

    def __json__(self):
        return {"pilot_id": self.pilot_id, "name": self.name, "country": self.country}
