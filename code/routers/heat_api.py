"""
Heat API Router Module.
Provides real-time information about the current and next heats for the dashboard.
"""
from datetime import datetime
from typing import Optional, Any, Dict
from fastapi import APIRouter, Depends

from pydantic import BaseModel

from session import get_session
from heat import Heat

router = APIRouter(prefix="/heat", tags=["heat"])

# --- Modele Wrappera (Envelope) ---


class ApiResponse(BaseModel):
    """Standard API response wrapper for heat data."""
    status: str
    message: Optional[str] = None
    heat: Optional[Dict[str, Any]] = None
    next_heat: Optional[Dict[str, Any]] = None


def process_heat_data(heat: Heat) -> Dict[str, Any]:
    """
    Converts a Heat object into a dictionary for API consumption.
    Calculates 'live' remaining seconds based on server time (Req 3.3).

    Args:
        heat (Heat): The Heat instance to process.

    Returns:
        Dict[str, Any]: Formatted heat data with status, numbers, and channels.
    """
    if not heat:
        return {}

    # LIVE Time Logic: Ensure dashboard stays in sync with server timer
    status = heat.get_status()
    seconds_left = heat.get_remaining_seconds()

    heat_data: dict[str, Any] = heat.as_dict()
    heat_data['live_seconds_left'] = seconds_left

    return {
        "status": heat.get_status(),
        "heat_number": heat.heat_number,

        "live_seconds_left": seconds_left,
        "channels": heat_data['channels'],

    }


@router.get("", response_model=ApiResponse)
async def get_current_heat(session=Depends(get_session)):
    """Retrieves the current active heat and the upcoming heat (Req 3.3)."""
    if not session:
        return ApiResponse(status="error", message="No active session found.")

    if not session.current_heat_number:
        return ApiResponse(status="error", message="No heat currently assigned in the session.")
    heat = session.current_heat
    if not heat:
        return ApiResponse(status="error", message=f"Heat number {session.current_heat_number} not found.")

    return ApiResponse(status="ok", heat=process_heat_data(heat), next_heat=process_heat_data(session.next_heat))
