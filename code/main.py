from contextlib import asynccontextmanager
from typing import List
import asyncio
import math

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse


import uvicorn

from pilot import Pilot
from group import Group
from heat import Heat
from session import Session, get_session, set_session

from connectionmanager import ConnectionManager
from database import RaceDatabase, get_db

# Importujemy rutery
from routers import api_router

manager = ConnectionManager()
db = get_db()

session: Session = db.get_active_session()
if (session):
    set_session(session)


MAX_PILOTS_PER_GROUP = 4
ALLOWED_CHANNELS = ["R1", "R3", "R6", "R7", "LB"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop_task = asyncio.create_task(training_cycle_loop())
    yield
    loop_task.cancel()


app = FastAPI(title="WKM Racing Management System API", lifespan=lifespan)
app.include_router(api_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")


@app.get("/index.html")
async def serve_frontend2():
    return FileResponse("static/index.html")


@app.get("/display")
async def serve_display():
    return FileResponse("static/display.html")


@app.get("/admin")
async def serve_display():
    return FileResponse("static/session.html")


@app.get("/favicon.ico")
async def serve_favicon():
    return FileResponse("static/wkm.ico")


async def training_cycle_loop():
    """Główna pętla zarządzająca cyklem treningowym. Działa w tle i co sekundę sprawdza stan sesji, aktualizuje timer i wysyła odpowiednie komunikaty do klientów.
    - Jeśli timer jest uruchomiony i są grupy, zarządza fazami PREP i FLIGHT, odliczając czas i wysyłając aktualizacje do klientów.
    - Jeśli timer nie jest uruchomiony lub nie ma grup, wysyła komunikat
    o oczekiwaniu/pauzie.
    """
    None
"""
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
                        "group_id": current_group.id,
                        "time_display": f"{time_left // 60:02d}:{time_left % 60:02d}"
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
                        await manager.broadcast({"type": "warning", "message": "10 sekund do końca!", "display_for": 5, "color": "green"})

                    await manager.broadcast({
                        "type": "timer",
                        "phase": "Przelot",
                        "time_left": time_left,
                        "time_display": f"{time_left // 60:02d}:{time_left % 60:02d}",
                        "group_id": current_group.id
                    })
                    await asyncio.sleep(1)
                    time_left -= 1

                # Koniec przelotu
                if state.timer_running and state.current_phase == "FLIGHT":
                    await manager.broadcast({"type": "flight_ended", "group_id": current_group.id})
                    state.current_group_index = (
                        state.current_group_index + 1) % len(state.groups)
                    state.current_phase = "PREP"
        else:

            if state.is_session_active:
                await manager.broadcast({
                    "type": "timer",
                    "phase": "Oczekiwanie / Pauza",
                    "time_left": 0,
                    "time_display": f"00:00",
                    "group_id": "-"
                })
            await asyncio.sleep(1)

"""

if __name__ == "__main__":
    print("Serwer uruchomiony na http://localhost:8000")
    print("Panel uruchomiony na http://localhost:8000/display")
    print("Panel admina http://localhost:8000/admin")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
