"""Config-driven access and trust helpers.

This module is intentionally leaf-level: it depends only on config and
transport-normalized user identity so higher-level orchestration code can
reuse one authoritative trust/access implementation without importing the
handler layer.
"""

from __future__ import annotations

from app.config import BotConfig
from octopus_sdk.inbound_types import InboundUser


def _validated_user(user: InboundUser | None) -> InboundUser | None:
    """Require already-normalized shared identity at this boundary."""
    if user is None:
        return None
    if not isinstance(user, InboundUser):
        raise TypeError("access helpers require InboundUser")
    return user


def is_allowed_user(config: BotConfig, user: InboundUser | None) -> bool:
    """Config baseline — no DB lookup.

    Use is_allowed_user_with_override when a live DB override is needed.
    """
    inbound = _validated_user(user)
    if inbound is None:
        return False
    if config.allow_open:
        return True
    if not config.allowed_actor_keys and not config.allowed_usernames:
        return False
    return (
        inbound.id in config.allowed_actor_keys
        or inbound.username in config.allowed_usernames
    )


def is_allowed_user_with_override(
    config: BotConfig,
    user: InboundUser | None,
    override: str | None,
) -> bool:
    """Apply DB override precedence on top of the config baseline."""
    inbound = _validated_user(user)
    if inbound is None:
        return False
    if override == "blocked":
        return False
    if override == "allowed":
        return True
    return is_allowed_user(config, inbound)


def is_admin_user(config: BotConfig, user: InboundUser | None) -> bool:
    """Return True when the user is allowed to manage imported runtime skills."""
    inbound = _validated_user(user)
    if inbound is None:
        return False
    return (
        inbound.id in config.admin_actor_keys
        or inbound.username in config.admin_usernames
    )


def is_public_user(config: BotConfig, user: InboundUser | None) -> bool:
    """Return True when the user is admitted in open mode but not trusted."""
    inbound = _validated_user(user)
    if inbound is None:
        return False
    if not config.allow_open:
        return False
    if not config.allowed_actor_keys and not config.allowed_usernames:
        return True
    return (
        inbound.id not in config.allowed_actor_keys
        and inbound.username not in config.allowed_usernames
    )


def trust_tier(config: BotConfig, user: InboundUser | None) -> str:
    """Resolve the user trust tier from config and identity."""
    return "public" if is_public_user(config, user) else "trusted"
