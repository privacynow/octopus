"""Explicit Telegram channel startup state."""

from __future__ import annotations

import os
import platform
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import BotConfig
from app.providers.base import Provider
from app.ratelimit import RateLimiter


@dataclass
class TelegramChannelState:
    """Startup-installed Telegram channel state."""

    config: BotConfig
    provider: Provider
    boot_id: str
    rate_limiter: RateLimiter | None
    bot_instance: Any = None


_CURRENT_STATE: TelegramChannelState | None = None


def make_boot_id() -> str:
    return f"{platform.node()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _build_rate_limiter(config: BotConfig) -> RateLimiter:
    per_minute = config.rate_limit_per_minute
    per_hour = config.rate_limit_per_hour
    if config.allow_open and per_minute == 0 and per_hour == 0:
        per_minute = 5
        per_hour = 30
    return RateLimiter(per_minute=per_minute, per_hour=per_hour)


def build_channel_state(
    config: BotConfig,
    provider: Provider,
    *,
    boot_id: str | None = None,
    bot_instance: Any = None,
) -> TelegramChannelState:
    """Construct a live Telegram channel state object."""
    return TelegramChannelState(
        config=config,
        provider=provider,
        boot_id=boot_id or make_boot_id(),
        rate_limiter=_build_rate_limiter(config),
        bot_instance=bot_instance,
    )


def install_channel_state(state: TelegramChannelState) -> None:
    """Install the live Telegram channel state."""
    global _CURRENT_STATE
    _CURRENT_STATE = state


def peek_channel_state() -> TelegramChannelState | None:
    """Return the live Telegram channel state when installed."""
    return _CURRENT_STATE


def get_channel_state() -> TelegramChannelState:
    """Return the installed Telegram channel state."""
    if _CURRENT_STATE is None:
        raise RuntimeError("Telegram channel state is not installed")
    return _CURRENT_STATE


def reset_channel_state() -> None:
    """Clear the installed Telegram channel state."""
    global _CURRENT_STATE
    _CURRENT_STATE = None


def set_bot_instance(bot_instance: Any) -> None:
    """Replace the current bot instance on the installed state."""
    get_channel_state().bot_instance = bot_instance
