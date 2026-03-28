"""
WSGI entry point for shared-hosting deployments (e.g. Passenger/uWSGI).

Wraps the FastAPI ASGI application in an ASGIMiddleware so it can be served
by a WSGI server. The 'application' object is the standard WSGI entry point
recognised by Passenger and compatible servers.
"""
from a2wsgi import ASGIMiddleware
from main import app

application = ASGIMiddleware(app)
