"""Explicit Telegram runtime ownership."""

from __future__ import annotations

import asyncio
import contextvars
import os
import platform
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from app.channels.telegram.cancellation import TelegramCancellationRegistry
from app.config import BotConfig
from app.providers.base import Provider
from app.ratelimit import RateLimiter


def make_boot_id() -> str:
    return f"{platform.node()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _build_rate_limiter(config: BotConfig) -> RateLimiter:
    per_minute = config.rate_limit_per_minute
    per_hour = config.rate_limit_per_hour
    if config.allow_open and per_minute == 0 and per_hour == 0:
        per_minute = 5
        per_hour = 30
    return RateLimiter(per_minute=per_minute, per_hour=per_hour)


def _default_registry_client_factory(config: BotConfig):
    from app.agents.bridge import registry_client

    return registry_client(config)


@dataclass
class TelegramRuntime:
    """Bootstrap-owned Telegram runtime instance.

    This is the only authoritative owner of live Telegram runtime state.
    """

    config: BotConfig
    provider: Provider
    boot_id: str
    rate_limiter: RateLimiter | None
    bot_instance: Any = None
    cancellation_registry: TelegramCancellationRegistry = field(
        default_factory=TelegramCancellationRegistry
    )
    chat_locks: defaultdict[int | str, asyncio.Lock] = field(
        default_factory=lambda: defaultdict(asyncio.Lock)
    )
    pending_work_items: dict[int, str] = field(default_factory=dict)
    channel_dispatcher: Any = None
    registry_runtime: Any = None
    registry_client_factory: Callable[[BotConfig], Any | None] = field(
        default_factory=lambda: _default_registry_client_factory
    )
    current_update_id: contextvars.ContextVar[int | None] = field(
        default_factory=lambda: contextvars.ContextVar(
            "telegram_current_update_id",
            default=None,
        )
    )


def build_telegram_runtime(
    config: BotConfig,
    provider: Provider,
    *,
    boot_id: str | None = None,
    bot_instance: Any = None,
) -> TelegramRuntime:
    """Construct an explicit Telegram runtime instance."""

    return TelegramRuntime(
        config=config,
        provider=provider,
        boot_id=boot_id or make_boot_id(),
        rate_limiter=_build_rate_limiter(config),
        bot_instance=bot_instance,
    )
