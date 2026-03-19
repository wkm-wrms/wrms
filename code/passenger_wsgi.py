from a2wsgi import ASGIMiddleware
from main import app


# To jest bolerplate dla uWSGI, który pozwala na uruchomienie aplikacji FastAPI jako aplikacji WSGI. Używamy ASGIMiddleware, aby opakować naszą aplikację FastAPI i uczynić ją kompatybilną z uWSGI.

# Ten obiekt 'application' zostanie zrozumiany przez uWSGI
application = ASGIMiddleware(app)
# Jeśli chcesz uruchomić aplikację bezpośrednio (np. do testów), możesz użyć tego kodu:
