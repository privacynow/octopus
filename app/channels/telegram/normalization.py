"""Telegram-native normalization helpers.

Telegram parsing and attachment download live here. Shared inbound event types
and durable serialization live under ``app.runtime.inbound_types``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from app import user_messages as _msg
from app.identity import (
    telegram_actor_key,
    telegram_conversation_key,
    telegram_conversation_ref,
)
from app.runtime.inbound_types import (
    InboundAttachment,
    InboundCallback,
    InboundCommand,
    InboundMessage,
    InboundUser,
)
from app.storage import build_upload_path, is_image_path


MAX_TELEGRAM_DOWNLOAD_BYTES = 20 * 1024 * 1024


class TelegramAttachmentTooLarge(ValueError):
    """Raised when a Telegram attachment exceeds the local download limit."""

    def __init__(self, original_name: str, file_size: int, *, max_bytes: int) -> None:
        self.original_name = original_name
        self.file_size = file_size
        self.max_bytes = max_bytes
        super().__init__(
            _msg.attachment_too_large(
                original_name,
                max_mebibytes=max_bytes // (1024 * 1024),
            )
        )


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


def _validate_attachment_size(original_name: str, file_size: object) -> None:
    try:
        size = int(file_size or 0)
    except (TypeError, ValueError):
        return
    if size > MAX_TELEGRAM_DOWNLOAD_BYTES:
        raise TelegramAttachmentTooLarge(
            original_name,
            size,
            max_bytes=MAX_TELEGRAM_DOWNLOAD_BYTES,
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
        _validate_attachment_size("photo.jpg", getattr(photo, "file_size", 0))
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
        _validate_attachment_size(name, getattr(doc, "file_size", 0))
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
        source="telegram",
        transport="telegram",
    )


def normalize_message_with_conversation_ref(message: InboundMessage, *, config, chat_id: int) -> InboundMessage:
    if message.conversation_ref:
        return message
    return dataclasses.replace(
        message,
        conversation_ref=telegram_conversation_ref(config, chat_id),
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
        source="telegram",
        transport="telegram",
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
        source="telegram",
        transport="telegram",
    )
