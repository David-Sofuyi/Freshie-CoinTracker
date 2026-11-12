"""
ASGI entrypoint.

FastAPI is the outer app and serves everything under /api (REST + WebSocket).
Django is mounted at "/" and serves the dashboard, admin and static files.
Both share the same process, settings and database.

Run:  uvicorn config.asgi:application --reload
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

# Must run before importing anything that touches Django models.
django_asgi_app = get_asgi_application()

from api.main import create_app  # noqa: E402

application = create_app(django_asgi_app)
