"""Config-driven access and trust helpers.

This module is intentionally leaf-level: it depends only on config and
transport-normalized user identity so higher-level orchestration code can
reuse one authoritative trust/access implementation without importing the
handler layer.
"""

from __future__ import annotations

from app.config import BotConfig
from app.transport import InboundUser, normalize_user


def to_inbound_user(user) -> InboundUser | None:
    """Coerce a raw Telegram user or InboundUser to InboundUser."""
    if user is None:
        return None
    if isinstance(user, InboundUser):
        return user
    return normalize_user(user)


def is_allowed_user(config: BotConfig, user) -> bool:
    """Return True when the user is allowed to interact with the bot."""
    inbound = to_inbound_user(user)
    if inbound is None:
        return False
    if config.allow_open:
        return True
    if not config.allowed_user_ids and not config.allowed_usernames:
        return False
    return (
        inbound.id in config.allowed_user_ids
        or inbound.username in config.allowed_usernames
    )


def is_admin_user(config: BotConfig, user) -> bool:
    """Return True when the user is allowed to manage store skills."""
    inbound = to_inbound_user(user)
    if inbound is None:
        return False
    return (
        inbound.id in config.admin_user_ids
        or inbound.username in config.admin_usernames
    )


def is_public_user(config: BotConfig, user) -> bool:
    """Return True when the user is admitted in open mode but not trusted."""
    inbound = to_inbound_user(user)
    if inbound is None:
        return False
    if not config.allow_open:
        return False
    if not config.allowed_user_ids and not config.allowed_usernames:
        return True
    return (
        inbound.id not in config.allowed_user_ids
        and inbound.username not in config.allowed_usernames
    )


def trust_tier(config: BotConfig, user) -> str:
    """Resolve the user trust tier from config and identity."""
    return "public" if is_public_user(config, user) else "trusted"
