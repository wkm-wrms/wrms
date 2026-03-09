from fastapi import FastAPI, WebSocket,WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
from contextlib import asynccontextmanager
import asyncio
import math
import uvicorn

class Pilot(BaseModel):
    id: int
    name: str
    is_active: bool = True
    digital: bool = False

class PilotCreate(BaseModel):
    name: str
    is_active: bool = True
    digital: bool = False

class Group(BaseModel):
    id: int
    pilots: List[Pilot]
    channels: dict #mapa pilotId->kanał

class SessionConfig(BaseModel):
    name: str
    flight_duration_sec: int
    prep_duration_sec: int


class RaceState:
    def __init__(self):
        self.is_session_active = False
        self.config = None
        self.active_pilots = []
        self.groups = []
        self.current_group_index = 0
        self.timer_running = False
        self.current_phase = "IDLE" # IDLE, PREP, FLIGHT, PAUSED
        self.phase_before_pause = "PREP"


state = RaceState()

MAX_PILOTS_PER_GROUP = 4
ALLOWED_CHANNELS = ["R1", "R3", "R6", "R7"]

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

def get_next_pilot_id() -> int:
    if not state.active_pilots:
        return 1
    return max(p.id for p in state.active_pilots) + 1



def rebalance_groups(active_pilots: List[Pilot]) -> List[Group]:
    total_pilots = len(active_pilots)
    if total_pilots == 0:
        return []

    num_groups = math.ceil(total_pilots / MAX_PILOTS_PER_GROUP)
    base_size = total_pilots // num_groups
    remainder = total_pilots % num_groups

    new_groups = []
    pilot_index = 0

    for i in range(num_groups):
        current_group_size = base_size + 1 if i < remainder else base_size
        group_pilots = active_pilots[pilot_index: pilot_index + current_group_size]

        channels = {}
        analog_idx = 0
        digital_idx = len(ALLOWED_CHANNELS) - 1

        #cyfry dostają wysokie kanały
        for pilot in [p for p in group_pilots if p.digital]:
            channels[pilot.id] = ALLOWED_CHANNELS[digital_idx]
            digital_idx -= 1

        #analogi dostają niskie kanały
        for pilot in [p for p in group_pilots if not p.digital]:
            channels[pilot.id] = ALLOWED_CHANNELS[analog_idx]
            analog_idx += 1

        new_groups.append(Group(
            id=i + 1,
            pilots=group_pilots,
            channels=channels
        ))

        pilot_index += current_group_size

    return new_groups


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop_task = asyncio.create_task(training_cycle_loop())
    yield
    loop_task.cancel()
app = FastAPI(title="WKM Racing Management System API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")

@app.get("/display")
async def serve_display():
    return FileResponse("static/display.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/session/start")
async def start_session(config: SessionConfig):
    if state.is_session_active:
        raise HTTPException(status_code=400, detail="Sesja już trwa.")
    if len(state.active_pilots) == 0:
        raise HTTPException(status_code=400, detail="Brak pilotów. Dodaj co najmniej jednego pilota przed startem sesji.")

    state.is_session_active = True
    state.config = config

    state.timer_running = True
    state.current_phase = "PREP"

    return {"status": "ok", "message": f"Sesja {config.name} rozpoczęta."}

@app.post("/api/session/stop")
async def stop_session():
    state.is_session_active = False
    state.timer_running = False
    state.current_phase = "IDLE"
    return {"status": "ok", "message": "Sesja zakończona."}


@app.post("/api/pilots")
async def add_pilot(pilot: PilotCreate):
    new_pilot = Pilot(
        id=get_next_pilot_id(),
        name=pilot.name,
        is_active=pilot.is_active,
        digital=pilot.digital
    )

    state.active_pilots.append(new_pilot)
    state.groups = rebalance_groups(state.active_pilots)

    await manager.broadcast({"type": "groups_updated"})

    return {"status": "ok", "pilot": new_pilot, "pilots": state.active_pilots}

@app.delete("/api/pilots/{pilot_id}")
async def remove_pilot(pilot_id: int):
    pilot_exists = any(p.id == pilot_id for p in state.active_pilots)
    if not pilot_exists:
        raise HTTPException(status_code=404, detail="Pilot nie istnieje w sesji.")

    state.active_pilots = [p for p in state.active_pilots if p.id != pilot_id]
    state.groups = rebalance_groups(state.active_pilots)

    # Utrzymaj poprawny indeks aktualnej grupy po zmianie liczby grup.
    if len(state.groups) == 0:
        state.current_group_index = 0
        state.current_phase = "IDLE" if not state.is_session_active else "PREP"
    else:
        state.current_group_index = min(state.current_group_index, len(state.groups) - 1)

    await manager.broadcast({"type": "groups_updated"})

    return {
        "status": "ok",
        "message": f"Usunięto pilota o ID {pilot_id}.",
        "pilots": state.active_pilots
    }

@app.get("/api/groups")
async def get_groups():
    return {"groups": state.groups, "current_index": state.current_group_index}

@app.post("/api/cycle/pause")
async def pause_timer():
    if not state.is_session_active:
        raise HTTPException(status_code=400, detail="Brak aktywnej sesji.")
    if state.current_phase == "PAUSED":
        return {"status": "ok", "message": "Sesja już jest w pauzie."}

    if state.current_phase in ("PREP", "FLIGHT"):
        state.phase_before_pause = state.current_phase
    else:
        state.phase_before_pause = "PREP"

    state.timer_running = False
    state.current_phase = "PAUSED"
    await manager.broadcast({"type": "session_paused"})
    return {"status": "ok", "message": "Sesja zapauzowana."}

@app.post("/api/cycle/resume")
async def resume_timer():
    if not state.is_session_active:
        raise HTTPException(status_code=400, detail="Brak aktywnej sesji.")
    if state.current_phase != "PAUSED":
        return {"status": "ok", "message": "Sesja nie jest w pauzie."}
    if len(state.groups) == 0:
        raise HTTPException(status_code=400, detail="Brak grup do wznowienia.")

    state.current_phase = state.phase_before_pause if state.phase_before_pause in ("PREP", "FLIGHT") else "PREP"
    state.timer_running = True
    await manager.broadcast({"type": "session_resumed"})
    return {"status": "ok", "message": "Sesja wznowiona."}

@app.post("/api/cycle/skip")
async def skip_phase():
    if not state.is_session_active:
        raise HTTPException(status_code=400, detail="Brak aktywnej sesji.")
    if state.current_phase not in ("PREP", "FLIGHT"):
        raise HTTPException(status_code=400, detail="Nie można pominąć obecną fazę. Sesja musi być w PREP lub FLIGHT.")
    if len(state.groups) == 0:
        raise HTTPException(status_code=400, detail="Brak grup.")

    if state.current_phase == "PREP":
        state.current_phase = "FLIGHT"
        message = "Pominięto przygotowanie, przechodzę do przelotu."
    elif state.current_phase == "FLIGHT":
        state.current_group_index = (state.current_group_index + 1) % len(state.groups)
        state.current_phase = "PREP"
        message = "Pominięto przelot, przechodzę do następnej grupy."

    await manager.broadcast({"type": "phase_skipped"})
    return {"status": "ok", "message": message}



async def training_cycle_loop():
    while True:
        if state.timer_running and len(state.groups) > 0:
            current_group = state.groups[state.current_group_index]

            if state.current_phase == "PREP":
                time_left = state.config.prep_duration_sec

                while time_left > 0 and state.timer_running and state.current_phase == "PREP":
                    await manager.broadcast({
                        "type": "timer",
                        "phase": "Przygotowanie",
                        "time_left": time_left,
                        "group_id": current_group.id
                    })
                    await asyncio.sleep(1)
                    time_left -= 1

                if state.timer_running and state.current_phase == "PREP":
                    state.current_phase = "FLIGHT"

            elif state.current_phase == "FLIGHT":
                flight_time = state.config.flight_duration_sec
                warning_time = 10
                time_left = flight_time

                while time_left > 0 and state.timer_running and state.current_phase == "FLIGHT":
                    if time_left == warning_time:
                        await manager.broadcast({"type": "warning", "message": "10 sekund do końca!"})

                    await manager.broadcast({
                        "type": "timer",
                        "phase": "Przelot",
                        "time_left": time_left,
                        "group_id": current_group.id
                    })
                    await asyncio.sleep(1)
                    time_left -= 1

                # Koniec przelotu
                if state.timer_running and state.current_phase == "FLIGHT":
                    await manager.broadcast({"type": "flight_ended", "group_id": current_group.id})
                    state.current_group_index = (state.current_group_index + 1) % len(state.groups)
                    state.current_phase = "PREP"
        else:

            if state.is_session_active:
                await manager.broadcast({
                    "type": "timer",
                    "phase": "Oczekiwanie / Pauza",
                    "time_left": 0,
                    "group_id": "-"
                })
            await asyncio.sleep(1)

if __name__ == "__main__":
    print("Serwer uruchomiony na http://localhost:8000")
    print("Panel uruchomiony na http://localhost:8000/display")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)