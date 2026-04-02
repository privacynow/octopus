"""SDK-owned deferred notification models and ports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from octopus_sdk.time_utils import utc_now, utc_now_iso


def expires_after_hours(*, hours: int) -> str:
    return (utc_now() + timedelta(hours=hours)).isoformat()


@dataclass(frozen=True)
class DeferredNotification:
    notification_id: str = field(default_factory=lambda: uuid4().hex)
    target_agent_id: str = ""
    actor_key: str = ""
    content: str = ""
    priority: str = "normal"
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: str = field(default_factory=lambda: expires_after_hours(hours=24))


@runtime_checkable
class DeferredNotificationPort(Protocol):
    def enqueue(
        self,
        data_dir: Path,
        notification: DeferredNotification,
    ) -> None: ...

    def flush(
        self,
        data_dir: Path,
        *,
        target_agent_id: str,
        actor_key: str,
        now: str | None = None,
    ) -> list[DeferredNotification]: ...

    def expire_stale(
        self,
        data_dir: Path,
        *,
        now: str | None = None,
    ) -> int: ...
