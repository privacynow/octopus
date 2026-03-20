"""Shared channel-neutral identity helpers.

Durable runtime storage uses text keys so multiple channels can coexist
without Telegram-specific integer assumptions. Telegram keys keep a stable
``tg:`` prefix and preserve legacy numeric filesystem layout where needed.
"""

from __future__ import annotations

import hashlib
import re


_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _prefixed(prefix: str, value: int | str) -> str:
    raw = str(value).strip()
    if raw.startswith(f"{prefix}:"):
        return raw
    return f"{prefix}:{raw}"


def telegram_actor_key(user_id: int | str) -> str:
    return _prefixed("tg", user_id)


def telegram_conversation_key(chat_id: int | str) -> str:
    return _prefixed("tg", chat_id)


def telegram_event_id(update_id: int | str) -> str:
    return _prefixed("tg", update_id)


def parse_actor_key(raw: str | int) -> str:
    """Parse config/user input into an actor key.

    Bare integers are treated as Telegram user IDs for backward compatibility.
    Already-prefixed identities pass through unchanged.
    """

    token = str(raw).strip()
    if not token:
        return ""
    if ":" in token:
        return token
    if token.isdigit():
        return telegram_actor_key(token)
    return token


def parse_conversation_key(raw: str | int) -> str:
    """Parse CLI/admin input into a conversation key.

    Bare integers are treated as Telegram conversation IDs for backward
    compatibility. Already-prefixed identities pass through unchanged.
    """

    token = str(raw).strip()
    if not token:
        return ""
    if ":" in token:
        return token
    if token.isdigit():
        return telegram_conversation_key(token)
    return token


def telegram_numeric_id(key: str) -> int | None:
    if not isinstance(key, str) or not key.startswith("tg:"):
        return None
    suffix = key[3:]
    if not suffix.isdigit():
        return None
    return int(suffix)


def telegram_chat_id_from_ref(conversation_ref: str) -> int | None:
    if not isinstance(conversation_ref, str):
        return None
    parts = conversation_ref.split(":", 2)
    if len(parts) != 3 or parts[0] != "telegram":
        return None
    chat_id = parts[2]
    if not chat_id.isdigit():
        return None
    return int(chat_id)


def filesystem_component_for_key(key: str | int) -> str:
    """Return a stable filesystem-safe component for a conversation/actor key."""

    raw = str(key).strip()
    numeric = telegram_numeric_id(raw)
    if numeric is not None:
        return str(numeric)
    if raw.isdigit():
        return raw
    safe = _SAFE_COMPONENT_RE.sub("_", raw).strip("._")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    if safe:
        safe = safe[:32]
        return f"{safe}-{digest}"
    return digest
