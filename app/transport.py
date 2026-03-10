"""Thin inbound transport normalization.

Converts python-telegram-bot Update objects into a small set of internal
event dataclasses.  Polling and (future) webhook entrypoints both produce
the same normalized shapes before handing off to business logic.

Outbound operations (reply_text, send_action, etc.) are NOT abstracted here.
Handlers still hold a reference to the raw Telegram message/query objects for
replies.  This is intentional: the value of 5.1 is a clean *inbound* seam,
not a full transport rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.storage import build_upload_path, is_image_path


@dataclass(frozen=True)
class InboundUser:
    """Identity of the user who sent the update."""
    id: int
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
    chat_id: int
    text: str
    attachments: tuple[InboundAttachment, ...] = ()


@dataclass(frozen=True)
class InboundCommand:
    """Normalized inbound slash-command."""
    user: InboundUser
    chat_id: int
    command: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class InboundCallback:
    """Normalized inbound inline-keyboard callback."""
    user: InboundUser
    chat_id: int
    data: str


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
        id=tg_user.id,
        username=(tg_user.username or "").lower(),
    )


async def download_attachments(
    update, chat_id: int, data_dir: Path,
) -> list[InboundAttachment]:
    """Download photos/documents from a Telegram Update to local disk.

    Returns a list of InboundAttachment with local paths.
    """
    message = update.effective_message
    attachments: list[InboundAttachment] = []

    if message.photo:
        photo = message.photo[-1]
        path = build_upload_path(data_dir, chat_id, "photo.jpg")
        tf = await photo.get_file()
        await tf.download_to_drive(custom_path=str(path))
        attachments.append(InboundAttachment(
            path=path, original_name="photo.jpg",
            is_image=True, mime_type="image/jpeg",
        ))

    if message.document:
        doc = message.document
        name = doc.file_name or "document"
        path = build_upload_path(data_dir, chat_id, name)
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
    message = update.effective_message
    text = message.text or message.caption or ""

    attachments = await download_attachments(update, chat_id, data_dir)

    if not text and not attachments:
        return None

    return InboundMessage(
        user=user,
        chat_id=chat_id,
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
    return InboundCommand(user=user, chat_id=chat_id, command=command, args=args)


def normalize_callback(update) -> InboundCallback | None:
    """Normalize a callback-query Update into an InboundCallback.

    Returns None if the update has no user.
    """
    user = normalize_user(update.effective_user)
    if user is None:
        return None
    chat_id = update.effective_chat.id
    data = update.callback_query.data or ""
    return InboundCallback(user=user, chat_id=chat_id, data=data)


# ---------------------------------------------------------------------------
# Serialization for durable storage
# ---------------------------------------------------------------------------

import json


def serialize_inbound(event: InboundMessage | InboundCommand | InboundCallback) -> str:
    """Serialize a normalized inbound event to JSON for durable storage."""
    if isinstance(event, InboundMessage):
        return json.dumps({
            "user_id": event.user.id,
            "username": event.user.username,
            "chat_id": event.chat_id,
            "text": event.text,
            "attachments": [
                {"path": str(a.path), "original_name": a.original_name,
                 "is_image": a.is_image, "mime_type": a.mime_type}
                for a in event.attachments
            ],
        })
    if isinstance(event, InboundCommand):
        return json.dumps({
            "user_id": event.user.id,
            "username": event.user.username,
            "chat_id": event.chat_id,
            "command": event.command,
            "args": list(event.args),
        })
    if isinstance(event, InboundCallback):
        return json.dumps({
            "user_id": event.user.id,
            "username": event.user.username,
            "chat_id": event.chat_id,
            "data": event.data,
        })
    raise TypeError(f"Unknown inbound type: {type(event)}")


def deserialize_inbound(kind: str, payload_json: str) -> InboundMessage | InboundCommand | InboundCallback:
    """Reconstruct a normalized inbound event from stored JSON."""
    d = json.loads(payload_json)
    user = InboundUser(id=d["user_id"], username=d.get("username", ""))
    if kind == "message":
        attachments = tuple(
            InboundAttachment(
                path=Path(a["path"]), original_name=a["original_name"],
                is_image=a["is_image"], mime_type=a.get("mime_type"),
            )
            for a in d.get("attachments", [])
        )
        return InboundMessage(user=user, chat_id=d["chat_id"], text=d.get("text", ""),
                              attachments=attachments)
    if kind == "command":
        return InboundCommand(user=user, chat_id=d["chat_id"],
                              command=d["command"], args=tuple(d.get("args", [])))
    if kind == "callback":
        return InboundCallback(user=user, chat_id=d["chat_id"], data=d.get("data", ""))
    raise ValueError(f"Unknown kind: {kind}")
