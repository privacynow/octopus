"""UTC-aware time helpers for durable timestamps.

Supports both legacy epoch-float timestamps and ISO 8601 strings so runtime
code can compare ages safely while storage formats evolve.
"""

from __future__ import annotations

import datetime
from typing import Any


def utc_now() -> datetime.datetime:
    """Return the current UTC time as an aware datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def utc_now_timestamp() -> float:
    """Return the current UTC time as Unix epoch seconds."""
    return utc_now().timestamp()


def coerce_utc_datetime(value: Any) -> datetime.datetime | None:
    """Parse an epoch float/int or ISO 8601 string into an aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value), tz=datetime.timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)
    return None


def age_seconds(value: Any, *, now: datetime.datetime | None = None) -> float | None:
    """Return age in seconds for a supported timestamp value."""
    parsed = coerce_utc_datetime(value)
    if parsed is None:
        return None
    current = now or utc_now()
    return max(0.0, (current - parsed).total_seconds())
