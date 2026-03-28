from contextlib import asynccontextmanager
from typing import List
import asyncio
import json

from fastapi import FastAPI, BackgroundTasks, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse


import uvicorn

from pilot import Pilot
from group import Group
from heat import Heat
from session import Session, get_session, set_session


from database import RaceDatabase, get_db

# Importujemy rutery
from routers import api_router

db = get_db()

session: Session = db.get_active_session()
if (session):
    set_session(session)

MAX_PILOTS_PER_GROUP = 4
ALLOWED_CHANNELS = ["R1", "R3", "R6", "R7"]


app = FastAPI(title="WKM Racing Management System API")
app.include_router(api_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def add_process_loop(request, call_next):
    session = get_session()
    if session:
        res = session.loop()
        if res:
            db.create_or_update_heat(
                session.current_heat, session.active_pilots)
            db.create_or_update_heat(session.next_heat, session.active_pilots)
            if len(session._archive_heats) > 0:
                db.create_or_update_heat(
                    session._archive_heats.pop(), session.active_pilots)
    response = await call_next(request)
    return response


@app.get("/")
async def serve_frontend():
    return FileResponse("static/dashboard.html")


@app.get("/index.html")
async def serve_frontend2():
    return FileResponse("static/dashboard.html")


@app.get("/display")
async def serve_display():
    return FileResponse("static/dashboard.html")


@app.get("/admin")
async def serve_display():
    return FileResponse("static/session.html")


@app.get("/favicon.ico")
async def serve_favicon():
    return FileResponse("static/wkm.ico")


class Main:
    def run(self, port=8000, reload=True):
        print(f"Panel uruchomiony na http://localhost:{port}/")
        print(f"Panel admina http://localhost:{port}/admin")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    import uvicorn
    main = Main()
    main.run()
