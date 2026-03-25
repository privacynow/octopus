"""Shared inbound event and admission types owned by runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from octopus_sdk.identity import telegram_numeric_id


_SOURCE_MISSING = object()


def _validated_source(source: object) -> str:
    if source is _SOURCE_MISSING:
        raise ValueError("Inbound event source must be explicit")
    value = str(source or "").strip()
    if not value:
        raise ValueError("Inbound event source must be non-empty")
    return value


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
    source: str | object = _SOURCE_MISSING
    conversation_ref: str = ""
    external_conversation_ref: str = ""
    routed_task_id: str = ""
    authority_ref: str = ""
    skip_approval: bool = False
    transport: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _validated_source(self.source))

    @property
    def chat_id(self) -> int | str:
        value = telegram_numeric_id(self.conversation_key)
        return value if value is not None else self.conversation_key


@dataclass(frozen=True)
class InboundCommand:
    """Normalized inbound slash command."""

    user: InboundUser
    conversation_key: str
    command: str
    args: tuple[str, ...] = ()
    source: str | object = _SOURCE_MISSING
    conversation_ref: str = ""
    transport: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _validated_source(self.source))

    @property
    def chat_id(self) -> int | str:
        value = telegram_numeric_id(self.conversation_key)
        return value if value is not None else self.conversation_key


@dataclass(frozen=True)
class InboundCallback:
    """Normalized inbound callback action from a channel UI."""

    user: InboundUser
    conversation_key: str
    data: str
    source: str | object = _SOURCE_MISSING
    conversation_ref: str = ""
    transport: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _validated_source(self.source))

    @property
    def chat_id(self) -> int | str:
        value = telegram_numeric_id(self.conversation_key)
        return value if value is not None else self.conversation_key


@dataclass(frozen=True)
class InboundAction:
    """Normalized semantic worker-owned action."""

    user: InboundUser
    conversation_key: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    source: str | object = _SOURCE_MISSING
    conversation_ref: str = ""
    external_conversation_ref: str = ""
    authority_ref: str = ""
    transport: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _validated_source(self.source))

    @property
    def chat_id(self) -> int | str:
        value = telegram_numeric_id(self.conversation_key)
        return value if value is not None else self.conversation_key


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


def serialize_inbound(
    event: InboundMessage | InboundCommand | InboundCallback | InboundAction,
    *,
    transport: str = "",
) -> str:
    """Serialize a normalized inbound event to durable JSON."""

    resolved_transport = str(transport or getattr(event, "transport", "") or "")
    if isinstance(event, InboundMessage):
        return json.dumps(
            {
                "actor_key": event.user.id,
                "username": event.user.username,
                "conversation_key": event.conversation_key,
                "text": event.text,
                "source": event.source,
                "transport": resolved_transport,
                "conversation_ref": event.conversation_ref,
                "external_conversation_ref": event.external_conversation_ref,
                "routed_task_id": event.routed_task_id,
                "authority_ref": event.authority_ref,
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
                "transport": resolved_transport,
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
                "transport": resolved_transport,
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
                "transport": resolved_transport,
                "conversation_ref": event.conversation_ref,
                "external_conversation_ref": event.external_conversation_ref,
                "authority_ref": event.authority_ref,
            }
        )
    raise TypeError(f"Unknown inbound type: {type(event)}")


def deserialize_inbound(
    kind: str,
    payload_json: str,
) -> InboundMessage | InboundCommand | InboundCallback | InboundAction:
    """Reconstruct a normalized inbound event from stored JSON."""

    data = json.loads(payload_json)
    actor_key = str(data.get("actor_key", "") or "")
    conversation_key = str(data.get("conversation_key", "") or "")
    if not actor_key or not conversation_key:
        raise ValueError("Inbound payload missing canonical actor_key/conversation_key")
    user = InboundUser(id=actor_key, username=data.get("username", ""))
    # Shared runtime payloads must carry explicit provenance. Silently
    # inventing Telegram here lets malformed registry payloads bypass the
    # canonical authority_ref check below.
    source = str(data.get("source", "") or "").strip()
    if not source:
        raise ValueError("Inbound payload missing canonical source")
    # Legacy durable payloads predate explicit transport serialization. Fall
    # back to the canonical source so replay keeps the best available
    # provenance instead of dropping to blank forever.
    transport = str(data.get("transport", "") or source).strip()
    conversation_ref = str(data.get("conversation_ref", "") or "")
    external_conversation_ref = str(data.get("external_conversation_ref", "") or "")
    authority_ref = str(data.get("authority_ref", "") or "")
    if source == "registry" and kind in {"message", "action"} and not authority_ref:
        raise ValueError("Registry inbound payload missing canonical authority_ref")
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
            conversation_key=conversation_key,
            text=data.get("text", ""),
            attachments=attachments,
            source=source,
            transport=transport,
            conversation_ref=conversation_ref,
            external_conversation_ref=external_conversation_ref,
            routed_task_id=data.get("routed_task_id", ""),
            authority_ref=authority_ref,
            skip_approval=bool(data.get("skip_approval", False)),
        )
    if kind == "command":
        return InboundCommand(
            user=user,
            conversation_key=conversation_key,
            command=data["command"],
            args=tuple(data.get("args", [])),
            source=source,
            transport=transport,
            conversation_ref=conversation_ref,
        )
    if kind == "callback":
        return InboundCallback(
            user=user,
            conversation_key=conversation_key,
            data=data.get("data", ""),
            source=source,
            transport=transport,
            conversation_ref=conversation_ref,
        )
    if kind == "action":
        params = data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        return InboundAction(
            user=user,
            conversation_key=conversation_key,
            action=data.get("action", ""),
            params=dict(params),
            source=source,
            transport=transport,
            conversation_ref=conversation_ref,
            external_conversation_ref=external_conversation_ref,
            authority_ref=authority_ref,
        )
    raise ValueError(f"Unknown kind: {kind}")
