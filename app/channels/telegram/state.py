"""Explicit Telegram runtime ownership."""

from __future__ import annotations

import asyncio
import contextvars
import os
import platform
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.config import BotConfig
from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.transport import BotRuntimeHandle
from octopus_sdk.providers import Provider
from app.runtime.work_admission import build_local_inbound_submitter
from app.runtime.services import BotServices
from octopus_sdk.ratelimit import RateLimiter

if TYPE_CHECKING:
    from octopus_sdk.transport_dispatcher import TransportDispatcher


def make_boot_id() -> str:
    return f"{platform.node()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _build_rate_limiter(config: BotConfig) -> RateLimiter:
    per_minute = config.rate_limit_per_minute
    per_hour = config.rate_limit_per_hour
    if config.allow_open and per_minute == 0 and per_hour == 0:
        per_minute = 5
        per_hour = 30
    return RateLimiter(per_minute=per_minute, per_hour=per_hour)


def _normalized_cancel_key(chat_id: int | str) -> int | str:
    return telegram_conversation_key(chat_id) if isinstance(chat_id, int) else chat_id


@dataclass
class TelegramCancellationRegistry:
    """Owns live per-conversation cancel events for Telegram execution."""

    _events: dict[int | str, asyncio.Event] = field(default_factory=dict)

    def get(self, chat_id: int | str) -> asyncio.Event | None:
        return self._events.get(_normalized_cancel_key(chat_id))

    def set(self, chat_id: int | str, event: asyncio.Event) -> None:
        self._events[_normalized_cancel_key(chat_id)] = event

    def pop(self, chat_id: int | str, default=None):
        return self._events.pop(_normalized_cancel_key(chat_id), default)

    def clear(self) -> None:
        self._events.clear()

    def __contains__(self, chat_id: object) -> bool:
        if not isinstance(chat_id, (int, str)):
            return False
        return _normalized_cancel_key(chat_id) in self._events

    def __getitem__(self, chat_id: int | str) -> asyncio.Event:
        return self._events[_normalized_cancel_key(chat_id)]

    def __setitem__(self, chat_id: int | str, event: asyncio.Event) -> None:
        self._events[_normalized_cancel_key(chat_id)] = event

    def __len__(self) -> int:
        return len(self._events)


@dataclass
class TelegramRuntime:
    """Bootstrap-owned Telegram runtime instance.

    This is the only authoritative owner of live Telegram runtime state.
    """

    config: BotConfig
    provider: Provider
    boot_id: str
    rate_limiter: RateLimiter | None
    submitter: BotRuntimeHandle
    services: BotServices
    bot_instance: Any = None
    cancellation_registry: TelegramCancellationRegistry = field(
        default_factory=TelegramCancellationRegistry
    )
    chat_locks: defaultdict[int | str, asyncio.Lock] = field(
        default_factory=lambda: defaultdict(asyncio.Lock)
    )
    execution_inflight: set[int | str] = field(default_factory=set)
    pending_work_items: dict[int, str] = field(default_factory=dict)
    transport_dispatcher: TransportDispatcher | None = None
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
    services: BotServices,
    transport_dispatcher: TransportDispatcher | None = None,
) -> TelegramRuntime:
    """Construct an explicit Telegram runtime instance."""

    return TelegramRuntime(
        config=config,
        provider=provider,
        boot_id=boot_id or make_boot_id(),
        rate_limiter=_build_rate_limiter(config),
        submitter=build_local_inbound_submitter(config.data_dir),
        services=services,
        bot_instance=bot_instance,
        transport_dispatcher=transport_dispatcher,
    )
