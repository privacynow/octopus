"""In-memory deferred notification store for SDK-only tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from octopus_sdk.deferred_notifications import DeferredNotification, DeferredNotificationPort


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class InMemoryDeferredNotificationStore(DeferredNotificationPort):
    _states: dict[str, list[DeferredNotification]] = field(default_factory=dict)

    def _state(self, data_dir: Path) -> list[DeferredNotification]:
        return self._states.setdefault(str(data_dir), [])

    def enqueue(
        self,
        data_dir: Path,
        notification: DeferredNotification,
    ) -> None:
        self._state(data_dir).append(notification)

    def flush(
        self,
        data_dir: Path,
        *,
        target_agent_id: str,
        actor_key: str,
        now: str | None = None,
    ) -> list[DeferredNotification]:
        state = self._state(data_dir)
        current = _as_datetime(now) if now else datetime.now(timezone.utc)
        delivered: list[DeferredNotification] = []
        remaining: list[DeferredNotification] = []
        for notification in state:
            if _as_datetime(notification.expires_at) <= current:
                continue
            if notification.target_agent_id == target_agent_id and notification.actor_key == actor_key:
                delivered.append(notification)
            else:
                remaining.append(notification)
        self._states[str(data_dir)] = remaining
        return delivered

    def expire_stale(
        self,
        data_dir: Path,
        *,
        now: str | None = None,
    ) -> int:
        state = self._state(data_dir)
        current = _as_datetime(now) if now else datetime.now(timezone.utc)
        remaining = [notification for notification in state if _as_datetime(notification.expires_at) > current]
        expired = len(state) - len(remaining)
        self._states[str(data_dir)] = remaining
        return expired
