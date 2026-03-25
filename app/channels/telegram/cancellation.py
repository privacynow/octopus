"""Telegram live-cancel registry types."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from octopus_sdk.identity import telegram_conversation_key


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
