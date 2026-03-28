"""
API router aggregator for WRMS.

Combines all sub-routers (pilot, session, group, heat, admin) under the /api prefix.
"""
from fastapi import APIRouter
from .pilot_api import router as pilot_api
from .session_api import router as session_api
from .group_api import router as group_api
from .heat_api import router as heat_api
from .admin_api import router as admin_api

# Main API router — all sub-routers are mounted here
api_router = APIRouter(prefix="/api")

api_router.include_router(pilot_api)
api_router.include_router(session_api)
api_router.include_router(group_api)
api_router.include_router(heat_api)
api_router.include_router(admin_api)
