from datetime import datetime
from typing import Optional, Any, Dict
from fastapi import APIRouter, Depends

from pydantic import BaseModel
import json

from session import get_session
from heat import Heat

router = APIRouter(prefix="/heat", tags=["heat"])

# --- Modele Wrappera (Envelope) ---


class ApiResponse(BaseModel):
    status: str
    message: Optional[str] = None
    heat: Optional[Dict[str, Any]] = None

# --- Funkcja Pomocnicza do Procesowania Danych ---


def process_heat_data(heat: Heat) -> Dict[str, Any]:
    """Konwertuje wiersz z bazy na słownik z wyliczonym czasem live."""
    if not heat:
        return {}
    now = datetime.now()

    # Logika czasu LIVE
    status = heat.get_status()
    seconds_left = None

    if status == 'FLIGHT':
        ref = heat.get_last_resume_at() or heat.get_flight_started_at()
        if ref:
            elapsed = now - ref
            remaining = heat.get_remaining_seconds_at_pause() or 0
            seconds_left = max(0, remaining - elapsed)

    elif status == 'PREP':
        start_prep = heat.get_prep_started_at()
        if start_prep:
            elapsed = now - start_prep
            seconds_left = max(0, 60.0 - elapsed)  # Przykładowe 60s

    heat_data: dict[str, Any] = heat.as_dict()
    heat_data['live_seconds_left'] = seconds_left

    # Obsługa JSON z pilotami
    if isinstance(heat_data.get('heat_pilots_data_json'), str):

        heat_data['pilots_data'] = json.loads(
            heat_data['heat_pilots_data_json'])

    return heat_data

# --- Endpointy ---


@router.get("", response_model=ApiResponse)
async def get_current_heat(session=Depends(get_session)):
    """Pobiera aktualny lub najbliższy heat."""

    if not session:
        return ApiResponse(status="ERROR", message="Brak aktywnej sesji")

    if not session.current_heat_number:
        return ApiResponse(status="ERROR", message="Brak przypisanego biegu w sesji")

    heat = session.current_heat

    if not heat:
        return ApiResponse(status="ERROR", message=f"Nie znaleziono biegu nr {session.current_heat_number}")

    return ApiResponse(status="OK", heat=process_heat_data(heat))


@router.get("/next", response_model=ApiResponse)
async def get_next_heat(session=Depends(get_session)):
    """Pobiera następny zaplanowany heat."""

    if not session:
        return ApiResponse(status="ERROR", message="Brak aktywnej sesji")

    if not session.next_heat:
        return ApiResponse(status="ERROR", message="Brak zaplanowanego następnego biegu")

    heat = session.next_heat

    return ApiResponse(status="OK", heat=process_heat_data(heat))
