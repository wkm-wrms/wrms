"""
Buzzer API Router for WRMS.

Provides a single public endpoint consumed by hardware ESP32 buzzers.
Returns upcoming alarms within a look-ahead window so the buzzer can
fire them at the correct UTC time using its NTP-synced clock.

Alarm types and patterns are defined in docs/design/BUZZER.md section 5.2.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from session import get_session

router = APIRouter(prefix="/buzzer", tags=["buzzer"])

# --------------------------------------------------------------------------- #
# Constants — hardcoded for MVP (see BUZZER.md section 7 for future config)   #
# --------------------------------------------------------------------------- #

LOOKAHEAD_SEC = 120   # Maximum seconds ahead to include alarms
GRACE_SEC = 5         # Include transition alarms up to this many seconds in the past
WARNING_AT_SEC = 30   # FLIGHT_WARNING_30 fires this many seconds before end
COUNTDOWN_FROM = 10   # COUNTDOWN alarms start this many seconds before end

# --------------------------------------------------------------------------- #
# Timezone helpers                                                             #
# --------------------------------------------------------------------------- #

def _local_to_utc(dt: datetime) -> datetime:
    """
    Convert a naive local datetime (as stored by heat.py via datetime.now())
    to a naive UTC datetime.

    Uses astimezone() which applies the host's local timezone to the naive
    datetime before converting — correct on any UTC offset.
    """
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Phase mapping                                                                #
# --------------------------------------------------------------------------- #

def _session_phase(session) -> str:
    """
    Map the current session/heat state to an API phase string.

    The ESP32 firmware uses this to decide polling frequency.
    """
    if session is None or session.current_phase in ("IDLE", "FINISHED"):
        return "IDLE"
    heat = session.current_heat
    if heat is None:
        return "IDLE"
    status = heat.get_status()
    if status == "PREP":
        return "PREP"
    if status == "FLIGHT":
        return "FLIGHT"
    if status == "PAUSED":
        # Report the phase that was active before pause so the buzzer keeps
        # its polling cadence.
        return session.phase_before_pause or "FLIGHT"
    return "IDLE"


def _poll_interval(phase: str) -> int:
    """Return recommended poll interval in seconds for each phase."""
    return {
        "FLIGHT": 5,
        "PREP":   10,
    }.get(phase, 15)


# --------------------------------------------------------------------------- #
# Alarm builders                                                               #
# --------------------------------------------------------------------------- #

def _alarm(alarm_id: str, type_str: str, fire_at: datetime) -> Dict[str, Any]:
    """Build a single alarm dict in the wire format."""
    return {
        "id":      alarm_id,
        "type":    type_str,
        "fire_at": fire_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }


def _build_alarms(session) -> List[Dict[str, Any]]:
    """
    Compute all upcoming alarms for the current heat.

    Rules (BUZZER.md section 5.3):
    - Only alarms with fire_at > now are emitted, EXCEPT transition alarms
      (PREP_START, FLIGHT_START) which carry a GRACE_SEC window so the buzzer
      can still fire them if it polls slightly late.
    - fire_at values beyond LOOKAHEAD_SEC in the future are omitted.

    Heat timestamps (prep_started_at, flight_started_at) are naive local time
    as stored by heat.py.  All comparisons use local time; wire-format fire_at
    values are converted to UTC via _local_to_utc().
    """
    alarms: List[Dict[str, Any]] = []

    if session is None or session.current_phase in ("IDLE", "FINISHED"):
        return alarms

    heat = session.current_heat
    if heat is None:
        return alarms

    # Use local time for comparisons — matches heat.py datetime.now() semantics.
    now = datetime.now()
    lookahead_limit = now + timedelta(seconds=LOOKAHEAD_SEC)
    grace_cutoff = now - timedelta(seconds=GRACE_SEC)
    heat_num = heat.heat_number
    status = heat.get_status()

    if status == "PREP":
        # PREP_START: fire when prep began (include within grace window)
        prep_started = heat.prep_started_at
        if prep_started and prep_started >= grace_cutoff:
            alarms.append(_alarm(
                f"heat-{heat_num}-PREP_START",
                "PREP_START",
                _local_to_utc(prep_started),
            ))

        # FLIGHT_START: predictable future event — prep_started + prep_time
        if prep_started:
            flight_start_at = prep_started + timedelta(seconds=heat.prep_time)
            if now < flight_start_at < lookahead_limit:
                alarms.append(_alarm(
                    f"heat-{heat_num}-FLIGHT_START",
                    "FLIGHT_START",
                    _local_to_utc(flight_start_at),
                ))

    elif status == "FLIGHT":
        # FLIGHT_START: include within grace window (buzzer may have just come online)
        flight_started = heat.flight_started_at
        if flight_started and flight_started >= grace_cutoff:
            alarms.append(_alarm(
                f"heat-{heat_num}-FLIGHT_START",
                "FLIGHT_START",
                _local_to_utc(flight_started),
            ))

        seconds_left = heat.get_remaining_seconds()
        if seconds_left is None or seconds_left < 0:
            return alarms

        # flight_ends_at in local time, then converted to UTC for output
        flight_ends_at_local = now + timedelta(seconds=seconds_left)

        # FLIGHT_WARNING_30
        fire_local = flight_ends_at_local - timedelta(seconds=WARNING_AT_SEC)
        if now < fire_local < lookahead_limit:
            alarms.append(_alarm(
                f"heat-{heat_num}-WARNING_30",
                "FLIGHT_WARNING_30",
                _local_to_utc(fire_local),
            ))

        # COUNTDOWN: individual 1-second alarms from COUNTDOWN_FROM down to 1
        for n in range(COUNTDOWN_FROM, 0, -1):
            fire_local = flight_ends_at_local - timedelta(seconds=n)
            if now < fire_local < lookahead_limit:
                alarms.append(_alarm(
                    f"heat-{heat_num}-COUNTDOWN-{n}",
                    "COUNTDOWN",
                    _local_to_utc(fire_local),
                ))

        # FLIGHT_END
        if now < flight_ends_at_local < lookahead_limit:
            alarms.append(_alarm(
                f"heat-{heat_num}-FLIGHT_END",
                "FLIGHT_END",
                _local_to_utc(flight_ends_at_local),
            ))

    return alarms


# --------------------------------------------------------------------------- #
# Response model                                                               #
# --------------------------------------------------------------------------- #

class BuzzerResponse(BaseModel):
    """Wire format returned by GET /api/buzzer."""

    status: str
    server_time: str
    phase: str
    poll_interval_sec: int
    alarms: List[Dict[str, Any]]
    message: Optional[str] = None


# --------------------------------------------------------------------------- #
# Endpoint                                                                     #
# --------------------------------------------------------------------------- #

@router.get("", response_model=BuzzerResponse)
async def get_buzzer_alarms():
    """
    Return upcoming race alarms for hardware ESP32 buzzers (BUZZER.md section 6).

    Public endpoint — no authentication required.
    Multiple buzzers can poll this endpoint simultaneously.

    Poll frequency is communicated via poll_interval_sec in the response:
      - FLIGHT phase: 5 s
      - PREP phase: 10 s
      - IDLE: 15 s
    """
    session = get_session()
    phase = _session_phase(session)
    alarms = _build_alarms(session)
    now_utc = _local_to_utc(datetime.now())

    return BuzzerResponse(
        status="ok",
        server_time=now_utc.strftime("%Y-%m-%dT%H:%M:%S.") +
                    f"{now_utc.microsecond // 1000:03d}Z",
        phase=phase,
        poll_interval_sec=_poll_interval(phase),
        alarms=alarms,
    )
