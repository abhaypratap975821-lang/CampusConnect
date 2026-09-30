import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db.models import Q
from .models import BlockedUser, Conversation, ConversationMember, Message, StudyGroup, StudyGroupMember


def _is_blocked(user_a_id, user_b_id):
    return BlockedUser.objects.filter(
        Q(blocker_id=user_a_id, blocked_id=user_b_id) | Q(blocker_id=user_b_id, blocked_id=user_a_id)
    ).exists()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.room_group_name = f"chat_{self.conversation_id}"

        if not self.scope["user"].is_authenticated:
            await self.close()
            return

        if not await self.can_access_chat():
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name,
            )

    async def receive(self, text_data):
        if not await self.can_access_chat():
            await self.close()
            return

        try:
            data = json.loads(text_data)
        except (TypeError, ValueError):
            return

        body = str(data.get("body", "")).strip()

        if not body:
            return

        message = await self.save_message(body)

        if message is None:
            await self.close()
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "message": message,
            },
        )

    async def chat_message(self, event):
        await self.send(
            text_data=json.dumps(event["message"])
        )

    @database_sync_to_async
    def can_access_chat(self):
        conversation = (
            Conversation.objects
            .select_related("match", "study_group")
            .filter(id=self.conversation_id)
            .first()
        )

        if not conversation:
            return False

        # Study-group chat: existing member-based access remains unchanged.
        if conversation.study_group_id is not None:
            return ConversationMember.objects.filter(
                conversation_id=conversation.id,
                user=self.scope["user"],
            ).exists()

        # Private chat must always belong to an active Match.
        if conversation.match_id is None or conversation.match is None:
            return False

        # User must be one of the two matched users.
        if self.scope["user"].id not in (
            conversation.match.user_a_id,
            conversation.match.user_b_id,
        ):
            return False

        # A block (in either direction) shuts down the private chat, even
        # if the underlying Match row hasn't been cleaned up yet.
        other_id = conversation.match.other(self.scope["user"]).id
        if _is_blocked(self.scope["user"].id, other_id):
            return False

        # Keep the conversation membership check as an additional safeguard.
        return ConversationMember.objects.filter(
            conversation_id=conversation.id,
            user=self.scope["user"],
        ).exists()

    @database_sync_to_async
    def save_message(self, body):
        conversation = (
            Conversation.objects
            .select_related("match", "study_group")
            .filter(id=self.conversation_id)
            .first()
        )

        if not conversation:
            return None

        # Private Match chat: verify Match is still active and user is a participant.
        if conversation.study_group_id is None:
            if conversation.match_id is None or conversation.match is None:
                return None

            if self.scope["user"].id not in (
                conversation.match.user_a_id,
                conversation.match.user_b_id,
            ):
                return None

            other_id = conversation.match.other(self.scope["user"]).id
            if _is_blocked(self.scope["user"].id, other_id):
                return None

            if not ConversationMember.objects.filter(
                conversation_id=conversation.id,
                user=self.scope["user"],
            ).exists():
                return None

        # Study-group chat remains member-based.
        else:
            if not ConversationMember.objects.filter(
                conversation_id=conversation.id,
                user=self.scope["user"],
            ).exists():
                return None

        msg = Message.objects.create(
            conversation=conversation,
            sender=self.scope["user"],
            body=body,
        )
        conversation.save(update_fields=["updated_at"])

        if conversation.study_group_id is None and conversation.match is not None:
            from .views import notify_new_message
            notify_new_message(conversation, self.scope["user"], conversation.match.other(self.scope["user"]))

        return {
            "id": msg.id,
            "body": msg.body,
            "sender": msg.sender.get_full_name() or msg.sender.username,
            "sender_id": msg.sender_id,
            "created_at": msg.created_at.isoformat(),
        }


class StudyCallConsumer(AsyncWebsocketConsumer):
    """WebRTC signaling relay for a StudyMatch group video call.

    This does not carry media itself (that's peer-to-peer WebRTC between
    browsers); it only relays offer/answer/ICE-candidate signaling messages
    between members of the same study group, and lets the group owner end
    the call for everyone. Only current members of the group may connect.
    """

    async def connect(self):
        self.group_id = self.scope["url_route"]["kwargs"]["group_id"]
        self.room_group_name = f"study_call_{self.group_id}"
        self.joined = False

        if not self.scope["user"].is_authenticated:
            await self.close()
            return

        self.is_owner = await self.is_group_owner()

        if not await self.is_group_member():
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        self.joined = True
        await self.accept()

        # Tell everyone already in the call that a new peer has joined, so
        # each existing peer can initiate a connection to them.
        await self.channel_layer.group_send(self.room_group_name, {
            "type": "peer_event",
            "event": "peer-joined",
            "peer_id": self.channel_name,
            "user_id": self.scope["user"].id,
            "name": self.scope["user"].get_full_name() or self.scope["user"].username,
            "is_owner": self.is_owner,
            "exclude": None,
        })

    async def disconnect(self, close_code):
        if getattr(self, "joined", False):
            await self.channel_layer.group_send(self.room_group_name, {
                "type": "peer_event",
                "event": "peer-left",
                "peer_id": self.channel_name,
                "user_id": self.scope["user"].id if self.scope["user"].is_authenticated else None,
                "name": "",
                "is_owner": False,
                "exclude": None,
            })
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        if not await self.is_group_member():
            await self.close()
            return

        try:
            data = json.loads(text_data)
        except (TypeError, ValueError):
            return

        msg_type = data.get("type")

        if msg_type == "end-call":
            if not self.is_owner:
                return
            await self.channel_layer.group_send(self.room_group_name, {
                "type": "peer_event",
                "event": "call-ended",
                "peer_id": self.channel_name,
                "user_id": self.scope["user"].id,
                "name": "",
                "is_owner": True,
                "exclude": None,
            })
            return

        # Point-to-point signaling relay (offer / answer / ice-candidate):
        # forwarded only to the specific peer it targets, never broadcast.
        target = data.get("target")
        if msg_type in ("offer", "answer", "ice-candidate") and target:
            await self.channel_layer.send(target, {
                "type": "signal_message",
                "payload": {
                    "type": msg_type,
                    "from": self.channel_name,
                    "sdp": data.get("sdp"),
                    "candidate": data.get("candidate"),
                },
            })

    async def peer_event(self, event):
        if event["peer_id"] == self.channel_name and event["event"] == "peer-joined":
            return  # don't notify a client about its own join
        await self.send(text_data=json.dumps({
            "type": event["event"],
            "peer_id": event["peer_id"],
            "user_id": event["user_id"],
            "name": event["name"],
            "is_owner": event["is_owner"],
        }))

    async def signal_message(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    @database_sync_to_async
    def is_group_member(self):
        return StudyGroupMember.objects.filter(group_id=self.group_id, user=self.scope["user"]).exists()

    @database_sync_to_async
    def is_group_owner(self):
        return StudyGroup.objects.filter(id=self.group_id, owner=self.scope["user"]).exists()
