from fastapi import APIRouter
from .pilot_api import router as pilot_api
from .session_api import router as session_api
from .group_api import router as group_api

# from .heat import router as heat
# from .sse import router as sse

# Tworzymy jeden główny ruter dla całego API
api_router = APIRouter(prefix="/api")

# Podpinamy podstrony (sub-routers)
api_router.include_router(pilot_api)
api_router.include_router(session_api)
api_router.include_router(group_api)

# api_router.include_router(heats)
# api_router.include_router(sse)
