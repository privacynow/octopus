"""Per-user sliding-window rate limiter.

Tracks request timestamps per user and enforces per-minute and per-hour limits.
All state is in-memory — resets on restart, which is the right default for a
rate limiter (no stale state after deploy).
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding-window rate limiter with per-minute and per-hour limits."""

    def __init__(self, per_minute: int = 0, per_hour: int = 0):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._timestamps: dict[int, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0 or self.per_hour > 0

    def check(self, user_id: int) -> tuple[bool, int]:
        """Check if a request is allowed.

        Returns (allowed, retry_after_seconds).
        If allowed, the request is recorded.  If not, retry_after is the
        number of seconds the caller should wait.
        """
        if not self.enabled:
            return True, 0

        now = time.monotonic()
        ts = self._timestamps[user_id]

        # Prune entries older than 1 hour
        cutoff_hour = now - 3600
        while ts and ts[0] < cutoff_hour:
            ts.popleft()

        # Check per-minute limit
        if self.per_minute > 0:
            cutoff_min = now - 60
            recent = sum(1 for t in ts if t >= cutoff_min)
            if recent >= self.per_minute:
                oldest_in_window = next(t for t in ts if t >= cutoff_min)
                retry = int(oldest_in_window - cutoff_min) + 1
                return False, max(retry, 1)

        # Check per-hour limit
        if self.per_hour > 0:
            if len(ts) >= self.per_hour:
                retry = int(ts[0] - cutoff_hour) + 1
                return False, max(retry, 1)

        ts.append(now)
        return True, 0

    def clear(self, user_id: int | None = None) -> None:
        """Clear rate limit state. If user_id given, clear only that user."""
        if user_id is not None:
            self._timestamps.pop(user_id, None)
        else:
            self._timestamps.clear()
