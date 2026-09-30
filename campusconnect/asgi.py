"""
ASGI config for campusconnect project.

It exposes the ASGI callable as a module-level variable named ``application``.
Wires in Django Channels so WebSocket chat traffic is routed alongside
regular HTTP requests.
"""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusconnect.settings")
django_asgi_app = get_asgi_application()

from dating.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
