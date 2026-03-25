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
    next_heat: Optional[Dict[str, Any]] = None

# --- Funkcja Pomocnicza do Procesowania Danych ---


def process_heat_data(heat: Heat) -> Dict[str, Any]:
    """Konwertuje wiersz z bazy na słownik z wyliczonym czasem live."""
    if not heat:
        return {}

    # Logika czasu LIVE
    status = heat.get_status()
    seconds_left = heat.get_remaining_seconds()

    heat_data: dict[str, Any] = heat.as_dict()
    heat_data['live_seconds_left'] = seconds_left

    # Obsługa JSON z pilotami
    if isinstance(heat_data.get('heat_pilots_data_json'), str):
        heat_data['pilots_data'] = json.loads(
            heat_data['heat_pilots_data_json'])

    return {
        "status": heat.get_status(),
        "heat_number": heat.heat_number,

        "live_seconds_left": seconds_left,
        "channels": heat_data['channels'],

    }

# --- Endpointy ---


@router.get("", response_model=ApiResponse)
async def get_current_heat(session=Depends(get_session)):
    """Pobiera aktualny i najbliższy heat."""
    if not session:
        return ApiResponse(status="error", message="Brak aktywnej sesji")

    if not session.current_heat_number:
        return ApiResponse(status="error", message="Brak przypisanego biegu w sesji")
    heat = session.current_heat
    if not heat:
        return ApiResponse(status="error", message=f"Nie znaleziono biegu nr {session.current_heat_number}")

    return ApiResponse(status="ok", heat=process_heat_data(heat), next_heat=process_heat_data(session.next_heat))
