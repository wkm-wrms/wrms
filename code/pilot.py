

class Pilot:
    id: int
    name: str

    def __init__(self, id: int, name: str, country: str = ""):
        self.id = id
        self.name = name
        self.country = country

    def __json__(self):
        return {"id": self.id, "name": self.name, "country": self.country}
