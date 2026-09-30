"""Convenience ASGI entrypoint, e.g. `daphne campusconnect.server:app`."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusconnect.settings")

from campusconnect.asgi import application as app  # noqa: E402
