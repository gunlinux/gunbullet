"""Entry point for ASGI/RSGI servers.

uv run uvicorn example.main:app_asgi
uv run granian --interface rsgi example.main:app_asgi --workers 1 --no-ws
"""

import logging

# Configure logging before building the app so anything logged during startup
# is captured by this config rather than the default lastResort handler.
logging.basicConfig(level=logging.INFO)

from example import create_app_asgi  # noqa: E402

app_asgi = create_app_asgi()
