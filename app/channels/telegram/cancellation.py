"""Explicit Telegram live-cancel registry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class TelegramCancellationRegistry:
    """Owns live per-conversation cancel events for Telegram execution."""

    _events: dict[int | str, asyncio.Event] = field(default_factory=dict)

    def get(self, chat_id: int | str) -> asyncio.Event | None:
        return self._events.get(chat_id)

    def set(self, chat_id: int | str, event: asyncio.Event) -> None:
        self._events[chat_id] = event

    def pop(self, chat_id: int | str, default=None):
        return self._events.pop(chat_id, default)

    def clear(self) -> None:
        self._events.clear()

    def __contains__(self, chat_id: object) -> bool:
        return chat_id in self._events

    def __getitem__(self, chat_id: int | str) -> asyncio.Event:
        return self._events[chat_id]

    def __setitem__(self, chat_id: int | str, event: asyncio.Event) -> None:
        self._events[chat_id] = event

    def __len__(self) -> int:
        return len(self._events)


_REGISTRY = TelegramCancellationRegistry()


def get_cancellation_registry() -> TelegramCancellationRegistry:
    return _REGISTRY


def reset_cancellation_registry() -> None:
    _REGISTRY.clear()
