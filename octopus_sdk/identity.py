"""Shared channel-neutral identity helpers.

Durable runtime storage uses text keys so multiple channels can coexist
without Telegram-specific integer assumptions. Telegram keys keep a stable
``tg:`` prefix and preserve legacy numeric filesystem layout where needed.
"""

from __future__ import annotations

import json
import logging
import hashlib
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from octopus_sdk.config import BotConfigBase

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotIdentityState:
    bot_id: str
    created_at: str


class ConversationScopedEvent(Protocol):
    conversation_ref: str
    conversation_key: str

    @property
    def chat_id(self) -> int | str: ...


def _prefixed(prefix: str, value: int | str) -> str:
    raw = str(value).strip()
    if raw.startswith(f"{prefix}:"):
        return raw
    return f"{prefix}:{raw}"


def event_id_for_conversation_key(conversation_key: str, raw_event_id: str | int) -> str:
    """Prefix a bare event id to match the conversation-key namespace."""

    token = str(raw_event_id).strip()
    if not token or ":" in token:
        return token
    prefix, _, _ = str(conversation_key).partition(":")
    if not prefix:
        return token
    return f"{prefix}:{token}"


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


def bot_identity_path(data_dir: Path) -> Path:
    return data_dir / "agent" / "bot_identity.json"


def _new_bot_identity() -> BotIdentityState:
    return BotIdentityState(
        bot_id=uuid4().hex,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def _atomic_write_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp_path.chmod(0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _save_bot_identity_state(path: Path, state: BotIdentityState) -> None:
    _atomic_write_private_json(path, asdict(state))


def load_bot_identity_state(data_dir: Path) -> BotIdentityState:
    path = bot_identity_path(data_dir)
    if not path.exists():
        state = _new_bot_identity()
        _save_bot_identity_state(path, state)
        return state
    try:
        raw = json.loads(path.read_text())
        bot_id = str(raw.get("bot_id", "")).strip()
        created_at = str(raw.get("created_at", "")).strip()
        if bot_id and created_at:
            return BotIdentityState(bot_id=bot_id, created_at=created_at)
        raise ValueError("missing required bot identity fields")
    except Exception:
        log.warning("Bot identity load failed, regenerating", exc_info=True)
        state = _new_bot_identity()
        _save_bot_identity_state(path, state)
        return state


def bot_identity(data_dir: Path) -> str:
    return load_bot_identity_state(data_dir).bot_id


def telegram_conversation_ref(config: BotConfigBase, chat_id: int | str) -> str:
    return f"telegram:{bot_identity(Path(config.data_dir))}:{chat_id}"


def conversation_key_for_ref(conversation_ref: str) -> str:
    chat_id = telegram_chat_id_from_ref(conversation_ref)
    if chat_id is not None:
        return telegram_conversation_key(chat_id)
    # Collapse registry conversation refs across registries:
    # registry:<id>:conversation:<cid> → registry:conversation:<cid>
    # but keep task refs un-collapsed:
    # registry:<id>:task:<tid> stays as-is
    if conversation_ref.startswith("registry:"):
        parts = conversation_ref.split(":", 3)
        if len(parts) == 4 and parts[2] == "conversation":
            return f"registry:conversation:{parts[3]}"
    return conversation_ref


def resolve_delegation_parent_identity(
    *,
    parent_transport_ref: str = "",
    parent_external_conversation_ref: str = "",
    parent_conversation_id: str = "",
) -> tuple[str, str]:
    """Return the best parent transport ref plus the session key derived from it.

    Delegation results should resume the originating transport chat, not the
    registry coordination conversation. The explicit transport ref carried on
    the routed-task protocol is the primary source. The mirrored conversation
    external ref is the fallback. The registry conversation id is last resort.
    """

    for candidate in (
        parent_transport_ref,
        parent_external_conversation_ref,
        parent_conversation_id,
    ):
        conversation_ref = str(candidate or "").strip()
        if not conversation_ref:
            continue
        return conversation_ref, conversation_key_for_ref(conversation_ref)
    return "", ""


def resolve_event_conversation_ref(*, config: BotConfigBase, event: ConversationScopedEvent) -> str:
    conversation_ref = str(getattr(event, "conversation_ref", "") or "")
    if conversation_ref:
        return conversation_ref
    conversation_key = str(getattr(event, "conversation_key", "") or "")
    try:
        chat_id = getattr(event, "chat_id")
    except AttributeError:
        chat_id = None
    except ValueError:
        if conversation_key:
            chat_id = None
        else:
            raise
    if isinstance(chat_id, int):
        return telegram_conversation_ref(config, chat_id)
    numeric_chat_id = telegram_numeric_id(conversation_key)
    if numeric_chat_id is not None:
        return telegram_conversation_ref(config, numeric_chat_id)
    if not conversation_key:
        raise ValueError("event missing conversation_ref/conversation_key")
    return conversation_key


def normalize_conversation_id(raw: str) -> str:
    """Extract bare conversation_id from possibly-prefixed refs.

    Handles:
      "registry:local:conversation:abc123" → "abc123"
      "registry:conversation:abc123"       → "abc123"
      "abc123"                              → "abc123"
    """
    parts = raw.split(":")
    # registry:<id>:conversation:<cid> or registry:conversation:<cid>
    if len(parts) >= 3 and parts[0] == "registry":
        for i, part in enumerate(parts):
            if part == "conversation" and i + 1 < len(parts):
                return parts[i + 1]
    return raw


def delegation_session_key(origin_agent_id: str, parent_conversation_id: str) -> str:
    """Stable session key for delegated work on a target bot.

    All tasks delegated from the same parent conversation by the same origin
    agent share one provider session on the target, so the target bot has
    conversational context across multiple delegations.
    """
    return f"delegation:{origin_agent_id}:{parent_conversation_id}"


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
