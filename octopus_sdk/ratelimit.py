"""Shared sliding-window rate limiter."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding-window rate limiter with per-minute and per-hour limits."""

    def __init__(self, per_minute: int = 0, per_hour: int = 0):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._timestamps: dict[str, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0 or self.per_hour > 0

    def check(self, actor_key: str) -> tuple[bool, int]:
        if not self.enabled:
            return True, 0

        now = time.monotonic()
        timestamps = self._timestamps[actor_key]

        cutoff_hour = now - 3600
        while timestamps and timestamps[0] < cutoff_hour:
            timestamps.popleft()

        if self.per_minute > 0:
            cutoff_min = now - 60
            recent = sum(1 for value in timestamps if value >= cutoff_min)
            if recent >= self.per_minute:
                oldest_in_window = next(value for value in timestamps if value >= cutoff_min)
                retry = int(oldest_in_window - cutoff_min) + 1
                return False, max(retry, 1)

        if self.per_hour > 0 and len(timestamps) >= self.per_hour:
            retry = int(timestamps[0] - cutoff_hour) + 1
            return False, max(retry, 1)

        timestamps.append(now)
        return True, 0

    def clear(self, actor_key: str | None = None) -> None:
        if actor_key is not None:
            self._timestamps.pop(actor_key, None)
        else:
            self._timestamps.clear()
