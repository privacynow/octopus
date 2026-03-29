"""App compatibility wrapper over SDK UTC-aware time helpers."""

from __future__ import annotations

from octopus_sdk.time_utils import age_seconds, coerce_utc_datetime, utc_now, utc_now_timestamp

__all__ = [
    "age_seconds",
    "coerce_utc_datetime",
    "utc_now",
    "utc_now_timestamp",
]
