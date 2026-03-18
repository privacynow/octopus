"""Shared inbound event and admission types owned by runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.identity import telegram_actor_key, telegram_conversation_key, telegram_numeric_id


@dataclass(frozen=True)
class InboundUser:
    """Identity of the user who sent an inbound event."""

    id: str
    username: str = ""


@dataclass(frozen=True)
class InboundAttachment:
    """Locally staged attachment associated with an inbound message."""

    path: Path
    original_name: str
    is_image: bool
    mime_type: str | None = None


@dataclass(frozen=True)
class InboundMessage:
    """Normalized inbound plain message."""

    user: InboundUser
    conversation_key: str
    text: str
    attachments: tuple[InboundAttachment, ...] = ()
    source: str = "telegram"
    conversation_ref: str = ""
    routed_task_id: str = ""
    skip_approval: bool = False

    @property
    def chat_id(self) -> int:
        value = telegram_numeric_id(self.conversation_key)
        if value is None:
            raise ValueError(f"conversation_key {self.conversation_key!r} is not a Telegram chat")
        return value


@dataclass(frozen=True)
class InboundCommand:
    """Normalized inbound slash command."""

    user: InboundUser
    conversation_key: str
    command: str
    args: tuple[str, ...] = ()
    source: str = "telegram"
    conversation_ref: str = ""

    @property
    def chat_id(self) -> int:
        value = telegram_numeric_id(self.conversation_key)
        if value is None:
            raise ValueError(f"conversation_key {self.conversation_key!r} is not a Telegram chat")
        return value


@dataclass(frozen=True)
class InboundCallback:
    """Normalized inbound callback action from a channel UI."""

    user: InboundUser
    conversation_key: str
    data: str
    source: str = "telegram"
    conversation_ref: str = ""

    @property
    def chat_id(self) -> int:
        value = telegram_numeric_id(self.conversation_key)
        if value is None:
            raise ValueError(f"conversation_key {self.conversation_key!r} is not a Telegram chat")
        return value


@dataclass(frozen=True)
class InboundAction:
    """Normalized semantic worker-owned action."""

    user: InboundUser
    conversation_key: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    source: str = "telegram"
    conversation_ref: str = ""

    @property
    def chat_id(self) -> int:
        value = telegram_numeric_id(self.conversation_key)
        if value is None:
            raise ValueError(f"conversation_key {self.conversation_key!r} is not a Telegram chat")
        return value


@dataclass(frozen=True)
class InboundEnvelope:
    """Normalized inbound delivery with conversation and actor identity."""

    transport: str
    event_id: str
    conversation_key: str
    actor_key: str
    received_at: datetime
    event: InboundMessage | InboundCommand | InboundCallback | InboundAction
    conversation_ref: str = ""
    surface_binding_id: str = ""

    @property
    def kind(self) -> str:
        if isinstance(self.event, InboundMessage):
            return "message"
        if isinstance(self.event, InboundCommand):
            return "command"
        if isinstance(self.event, InboundCallback):
            return "callback"
        if isinstance(self.event, InboundAction):
            return "action"
        return "unknown"


def serialize_inbound(event: InboundMessage | InboundCommand | InboundCallback | InboundAction) -> str:
    """Serialize a normalized inbound event to durable JSON."""

    if isinstance(event, InboundMessage):
        return json.dumps(
            {
                "actor_key": event.user.id,
                "username": event.user.username,
                "conversation_key": event.conversation_key,
                "text": event.text,
                "source": event.source,
                "conversation_ref": event.conversation_ref,
                "routed_task_id": event.routed_task_id,
                "skip_approval": event.skip_approval,
                "attachments": [
                    {
                        "path": str(a.path),
                        "original_name": a.original_name,
                        "is_image": a.is_image,
                        "mime_type": a.mime_type,
                    }
                    for a in event.attachments
                ],
            }
        )
    if isinstance(event, InboundCommand):
        return json.dumps(
            {
                "actor_key": event.user.id,
                "username": event.user.username,
                "conversation_key": event.conversation_key,
                "command": event.command,
                "args": list(event.args),
                "source": event.source,
                "conversation_ref": event.conversation_ref,
            }
        )
    if isinstance(event, InboundCallback):
        return json.dumps(
            {
                "actor_key": event.user.id,
                "username": event.user.username,
                "conversation_key": event.conversation_key,
                "data": event.data,
                "source": event.source,
                "conversation_ref": event.conversation_ref,
            }
        )
    if isinstance(event, InboundAction):
        return json.dumps(
            {
                "actor_key": event.user.id,
                "username": event.user.username,
                "conversation_key": event.conversation_key,
                "action": event.action,
                "params": event.params,
                "source": event.source,
                "conversation_ref": event.conversation_ref,
            }
        )
    raise TypeError(f"Unknown inbound type: {type(event)}")


def deserialize_inbound(
    kind: str,
    payload_json: str,
) -> InboundMessage | InboundCommand | InboundCallback | InboundAction:
    """Reconstruct a normalized inbound event from stored JSON."""

    data = json.loads(payload_json)
    actor_key = data.get("actor_key")
    if not actor_key and "user_id" in data:
        actor_key = telegram_actor_key(data["user_id"])
    conversation_key = data.get("conversation_key")
    if not conversation_key and "chat_id" in data:
        conversation_key = telegram_conversation_key(data["chat_id"])
    user = InboundUser(id=str(actor_key or ""), username=data.get("username", ""))
    if kind == "message":
        attachments = tuple(
            InboundAttachment(
                path=Path(item["path"]),
                original_name=item["original_name"],
                is_image=item["is_image"],
                mime_type=item.get("mime_type"),
            )
            for item in data.get("attachments", [])
        )
        return InboundMessage(
            user=user,
            conversation_key=str(conversation_key or ""),
            text=data.get("text", ""),
            attachments=attachments,
            source=data.get("source", "telegram"),
            conversation_ref=data.get("conversation_ref", ""),
            routed_task_id=data.get("routed_task_id", ""),
            skip_approval=bool(data.get("skip_approval", False)),
        )
    if kind == "command":
        return InboundCommand(
            user=user,
            conversation_key=str(conversation_key or ""),
            command=data["command"],
            args=tuple(data.get("args", [])),
            source=data.get("source", "telegram"),
            conversation_ref=data.get("conversation_ref", ""),
        )
    if kind == "callback":
        return InboundCallback(
            user=user,
            conversation_key=str(conversation_key or ""),
            data=data.get("data", ""),
            source=data.get("source", "telegram"),
            conversation_ref=data.get("conversation_ref", ""),
        )
    if kind == "action":
        params = data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        return InboundAction(
            user=user,
            conversation_key=str(conversation_key or ""),
            action=data.get("action", ""),
            params=dict(params),
            source=data.get("source", "telegram"),
            conversation_ref=data.get("conversation_ref", ""),
        )
    raise ValueError(f"Unknown kind: {kind}")
