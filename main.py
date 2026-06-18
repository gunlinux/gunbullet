import logging

logging.basicConfig(level=logging.INFO)

from app import create_app_asgi

app_asgi = create_app_asgi()
