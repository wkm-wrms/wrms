"""
Heat API Router for WRMS.

Provides real-time information about the current and next heats for the
dashboard. The live_seconds_left value is computed server-side on every
request so the frontend timer stays synchronised even after page reload.
"""
from typing import Optional, Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from session import get_session
from heat import Heat

router = APIRouter(prefix="/heat", tags=["heat"])


class ApiResponse(BaseModel):
    """Standard envelope for heat API responses."""

    status: str
    message: Optional[str] = None
    heat: Optional[Dict[str, Any]] = None
    next_heat: Optional[Dict[str, Any]] = None


def process_heat_data(heat: Heat) -> Dict[str, Any]:
    """
    Convert a Heat object to an API-friendly dictionary.

    Injects the live remaining seconds so the dashboard always has a fresh
    countdown value regardless of when the page was loaded (Req 3.3).

    Args:
        heat: The Heat instance to serialise.

    Returns:
        Dict containing status, heat_number, live_seconds_left, and channels.
        Returns an empty dict when heat is None.
    """
    if not heat:
        return {}

    seconds_left = heat.get_remaining_seconds()
    return {
        "status": heat.get_status(),
        "heat_number": heat.heat_number,
        "live_seconds_left": seconds_left,
        "channels": heat.model_dump()["channels"],
    }


@router.get("", response_model=ApiResponse)
async def get_current_heat():
    """
    Return the current active heat and the upcoming heat (Req 3.3).

    Returns an error envelope instead of raising HTTP exceptions so the
    dashboard JavaScript can handle the response uniformly.
    """
    session = get_session()
    if not session:
        return ApiResponse(status="error", message="No active session found.")
    if not session.current_heat_number:
        return ApiResponse(status="error", message="No heat currently assigned.")
    heat = session.current_heat
    if not heat:
        return ApiResponse(
            status="error",
            message=f"Heat {session.current_heat_number} not found.",
        )
    return ApiResponse(
        status="ok",
        heat=process_heat_data(heat),
        next_heat=process_heat_data(session.next_heat),
    )
