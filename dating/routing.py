from django.urls import path

from .consumers import ChatConsumer, StudyCallConsumer

websocket_urlpatterns = [
    path("ws/chat/<int:conversation_id>/", ChatConsumer.as_asgi()),
    path("ws/study/<int:group_id>/call/", StudyCallConsumer.as_asgi()),
]
