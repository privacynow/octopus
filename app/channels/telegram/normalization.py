"""Telegram channel normalization.

Converts python-telegram-bot Update objects into a small set of internal
event dataclasses.  Polling and (future) webhook entrypoints both produce
the same normalized shapes before handing off to business logic.

Outbound operations (reply_text, send_action, etc.) are NOT abstracted here.
Handlers still hold a reference to the raw Telegram message/query objects for
replies.  This is intentional: the value of 5.1 is a clean *inbound* seam,
not a full transport rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.identity import (
    telegram_actor_key,
    telegram_conversation_key,
    telegram_numeric_id,
)
from app.storage import build_upload_path, is_image_path


@dataclass(frozen=True)
class InboundUser:
    """Identity of the user who sent the update."""
    id: str
    username: str = ""


@dataclass(frozen=True)
class InboundAttachment:
    """A photo or document attached to an inbound message.

    Constructed *after* the file has been downloaded to local disk.
    """
    path: Path
    original_name: str
    is_image: bool
    mime_type: str | None = None


@dataclass(frozen=True)
class InboundMessage:
    """Normalized inbound plain message (non-command, non-callback)."""
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
    """Normalized inbound slash-command."""
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
    """Normalized inbound inline-keyboard callback."""
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
    """Normalized worker-owned semantic action."""

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


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_user(tg_user) -> InboundUser | None:
    """Extract identity from a python-telegram-bot User object.

    Returns None if tg_user is None (e.g. channel posts, system messages).
    """
    if tg_user is None:
        return None
    return InboundUser(
        id=telegram_actor_key(tg_user.id),
        username=(tg_user.username or "").lower(),
    )


async def download_attachments(
    update, conversation_key: str, data_dir: Path,
) -> list[InboundAttachment]:
    """Download photos/documents from a Telegram Update to local disk.

    Returns a list of InboundAttachment with local paths.
    """
    message = update.effective_message
    attachments: list[InboundAttachment] = []

    if message.photo:
        photo = message.photo[-1]
        path = build_upload_path(data_dir, conversation_key, "photo.jpg")
        tf = await photo.get_file()
        await tf.download_to_drive(custom_path=str(path))
        attachments.append(InboundAttachment(
            path=path, original_name="photo.jpg",
            is_image=True, mime_type="image/jpeg",
        ))

    if message.document:
        doc = message.document
        name = doc.file_name or "document"
        path = build_upload_path(data_dir, conversation_key, name)
        tf = await doc.get_file()
        await tf.download_to_drive(custom_path=str(path))
        is_img = (doc.mime_type or "").startswith("image/") or is_image_path(path)
        attachments.append(InboundAttachment(
            path=path, original_name=name,
            is_image=is_img, mime_type=doc.mime_type,
        ))

    return attachments


async def normalize_message(
    update, context, data_dir: Path,
) -> InboundMessage | None:
    """Normalize a plain-message Update into an InboundMessage.

    Returns None if the update has no user or no usable content.
    Downloads attachments to disk as a side-effect.
    """
    user = normalize_user(update.effective_user)
    if user is None:
        return None
    chat_id = update.effective_chat.id
    conversation_key = telegram_conversation_key(chat_id)
    message = update.effective_message
    text = message.text or message.caption or ""

    attachments = await download_attachments(update, conversation_key, data_dir)

    if not text and not attachments:
        return None

    return InboundMessage(
        user=user,
        conversation_key=conversation_key,
        text=text,
        attachments=tuple(attachments),
    )


def normalize_command(update, context) -> InboundCommand | None:
    """Normalize a command Update into an InboundCommand.

    Returns None if the update has no user.
    """
    user = normalize_user(update.effective_user)
    if user is None:
        return None
    chat_id = update.effective_chat.id
    # Extract command name from message text (e.g. "/help topic" → "help")
    raw = (update.effective_message.text or "").split()[0] if update.effective_message.text else ""
    command = raw.lstrip("/").split("@")[0]  # strip leading / and @botname suffix
    args = tuple(context.args or [])
    return InboundCommand(
        user=user,
        conversation_key=telegram_conversation_key(chat_id),
        command=command,
        args=args,
    )


def normalize_callback(update) -> InboundCallback | None:
    """Normalize a callback-query Update into an InboundCallback.

    Returns None if the update has no user.
    """
    user = normalize_user(update.effective_user)
    if user is None:
        return None
    chat_id = update.effective_chat.id
    data = update.callback_query.data or ""
    return InboundCallback(
        user=user,
        conversation_key=telegram_conversation_key(chat_id),
        data=data,
    )


# ---------------------------------------------------------------------------
# Serialization for durable storage
# ---------------------------------------------------------------------------

import json


def serialize_inbound(event: InboundMessage | InboundCommand | InboundCallback | InboundAction) -> str:
    """Serialize a normalized inbound event to JSON for durable storage."""
    if isinstance(event, InboundMessage):
        return json.dumps({
            "actor_key": event.user.id,
            "username": event.user.username,
            "conversation_key": event.conversation_key,
            "text": event.text,
            "source": event.source,
            "conversation_ref": event.conversation_ref,
            "routed_task_id": event.routed_task_id,
            "skip_approval": event.skip_approval,
            "attachments": [
                {"path": str(a.path), "original_name": a.original_name,
                 "is_image": a.is_image, "mime_type": a.mime_type}
                for a in event.attachments
            ],
        })
    if isinstance(event, InboundCommand):
        return json.dumps({
            "actor_key": event.user.id,
            "username": event.user.username,
            "conversation_key": event.conversation_key,
            "command": event.command,
            "args": list(event.args),
            "source": event.source,
            "conversation_ref": event.conversation_ref,
        })
    if isinstance(event, InboundCallback):
        return json.dumps({
            "actor_key": event.user.id,
            "username": event.user.username,
            "conversation_key": event.conversation_key,
            "data": event.data,
            "source": event.source,
            "conversation_ref": event.conversation_ref,
        })
    if isinstance(event, InboundAction):
        return json.dumps({
            "actor_key": event.user.id,
            "username": event.user.username,
            "conversation_key": event.conversation_key,
            "action": event.action,
            "params": event.params,
            "source": event.source,
            "conversation_ref": event.conversation_ref,
        })
    raise TypeError(f"Unknown inbound type: {type(event)}")


def deserialize_inbound(
    kind: str,
    payload_json: str,
) -> InboundMessage | InboundCommand | InboundCallback | InboundAction:
    """Reconstruct a normalized inbound event from stored JSON."""
    d = json.loads(payload_json)
    actor_key = d.get("actor_key")
    if not actor_key and "user_id" in d:
        actor_key = telegram_actor_key(d["user_id"])
    conversation_key = d.get("conversation_key")
    if not conversation_key and "chat_id" in d:
        conversation_key = telegram_conversation_key(d["chat_id"])
    user = InboundUser(id=str(actor_key or ""), username=d.get("username", ""))
    if kind == "message":
        attachments = tuple(
            InboundAttachment(
                path=Path(a["path"]), original_name=a["original_name"],
                is_image=a["is_image"], mime_type=a.get("mime_type"),
            )
            for a in d.get("attachments", [])
        )
        return InboundMessage(
            user=user,
            conversation_key=str(conversation_key or ""),
            text=d.get("text", ""),
            attachments=attachments,
            source=d.get("source", "telegram"),
            conversation_ref=d.get("conversation_ref", ""),
            routed_task_id=d.get("routed_task_id", ""),
            skip_approval=bool(d.get("skip_approval", False)),
        )
    if kind == "command":
        return InboundCommand(
            user=user,
            conversation_key=str(conversation_key or ""),
            command=d["command"],
            args=tuple(d.get("args", [])),
            source=d.get("source", "telegram"),
            conversation_ref=d.get("conversation_ref", ""),
        )
    if kind == "callback":
        return InboundCallback(
            user=user,
            conversation_key=str(conversation_key or ""),
            data=d.get("data", ""),
            source=d.get("source", "telegram"),
            conversation_ref=d.get("conversation_ref", ""),
        )
    if kind == "action":
        params = d.get("params", {})
        if not isinstance(params, dict):
            params = {}
        return InboundAction(
            user=user,
            conversation_key=str(conversation_key or ""),
            action=d.get("action", ""),
            params=dict(params),
            source=d.get("source", "telegram"),
            conversation_ref=d.get("conversation_ref", ""),
        )
    raise ValueError(f"Unknown kind: {kind}")
