"""
Main module of the WKM Racing Management System.
Initializes the FastAPI server, mounts routers, and handles session middleware.
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import uvicorn

from session import Session, get_session, set_session
from database import get_db
from routers import api_router

db = get_db()

# Inicjalizacja sesji przy starcie
active_session: Session = db.get_active_session()
if active_session:
    set_session(active_session)

MAX_PILOTS_PER_GROUP = 4
ALLOWED_CHANNELS = ["R1", "R3", "R6", "R7"]

app = FastAPI(title="WKM Racing Management System API")
app.include_router(api_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return all HTTP errors as consistent JSON (status/message dict)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail},
    )

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def session_persistence_middleware(request, call_next):
    """
    Middleware zarządzający pętlą sesji i automatycznym zapisem stanu do bazy danych.
    """
    session = get_session()
    if session:
        res = session.loop()
        if res:
            db.create_or_update_heat(session.current_heat, session.active_pilots)
            db.create_or_update_heat(session.next_heat, session.active_pilots)
            archived = session.pop_archived_heat()
            if archived:
                db.create_or_update_heat(archived, session.active_pilots)
    response = await call_next(request)
    return response


@app.get("/")
async def serve_frontend():
    """Serves the main dashboard panel (Public View/Kiosk)."""
    return FileResponse("static/dashboard.html")


@app.get("/index.html")
async def serve_frontend2():
    """Alias for the home page."""
    return FileResponse("static/dashboard.html")


@app.get("/display")
async def serve_display_view():
    """Serves the public display view."""
    return FileResponse("static/dashboard.html")


@app.get("/admin")
async def serve_admin_view():
    """Serves the administrator panel."""
    return FileResponse("static/session.html")


@app.get("/pilots.html")
async def serve_pilots_manager():
    """Serves the pilot management panel (loaded inside an iframe)."""
    return FileResponse("static/pilots.html")


@app.get("/backup.html")
async def serve_backup_manager():
    """Serves the backup/restore panel (loaded inside an iframe)."""
    return FileResponse("static/backup.html")


@app.get("/pilot/{session_id}")
async def serve_pilot_view(session_id: str):
    """Serves the public pilot view (Frontend 2), accessible via QR code.

    Returns 404 if the session_id does not match the currently active session.
    """
    session = get_session()
    if session is None or session.session_id != session_id or session.current_phase == "FINISHED":
        return HTMLResponse(
            status_code=404,
            content=(
                "<!DOCTYPE html><html lang='pl'><head><meta charset='UTF-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>404 — WKM Race</title>"
                "<style>"
                "body{margin:0;display:flex;align-items:center;justify-content:center;"
                "height:100dvh;background:#0a0a0a;color:#eee;"
                "font-family:'Segoe UI',system-ui,sans-serif;text-align:center;}"
                "h1{font-size:4rem;color:#00d4ff;margin:0;}"
                "p{color:#888;font-size:1.1rem;margin-top:12px;}"
                "</style></head><body>"
                "<div><h1>404</h1><p>Session is not active.</p></div>"
                "</body></html>"
            ),
        )
    return FileResponse("static/pilot.html")


@app.get("/favicon.ico")
async def serve_favicon():
    """Serves the site icon."""
    return FileResponse("static/wkm.ico")


class Main:  # pylint: disable=too-few-public-methods
    """Helper class to run the uvicorn server."""
    @staticmethod
    def run(port=8000, reload=True):
        """Starts the FastAPI application."""
        print(f"Dashboard running at http://localhost:{port}/")
        print(f"Admin panel running at http://localhost:{port}/admin")
        uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)


if __name__ == "__main__":
    main = Main()
    main.run()
