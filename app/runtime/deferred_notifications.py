"""App adapter for SDK deferred notifications."""

from __future__ import annotations

from pathlib import Path

from app.storage import (
    enqueue_deferred_notification,
    expire_stale_deferred_notifications,
    flush_deferred_notifications,
)
from octopus_sdk.deferred_notifications import DeferredNotification, DeferredNotificationPort


class LocalDeferredNotifications(DeferredNotificationPort):
    def enqueue(
        self,
        data_dir: Path,
        notification: DeferredNotification,
    ) -> None:
        enqueue_deferred_notification(data_dir, notification)

    def flush(
        self,
        data_dir: Path,
        *,
        target_agent_id: str,
        actor_key: str,
        now: str | None = None,
    ) -> list[DeferredNotification]:
        return flush_deferred_notifications(
            data_dir,
            target_agent_id=target_agent_id,
            actor_key=actor_key,
            now=now,
        )

    def expire_stale(
        self,
        data_dir: Path,
        *,
        now: str | None = None,
    ) -> int:
        return expire_stale_deferred_notifications(data_dir, now=now)
