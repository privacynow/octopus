"""Tests for the sliding-window rate limiter."""

import time
from unittest.mock import patch

from app.ratelimit import RateLimiter


# --- disabled by default ---

def test_disabled_when_limits_are_zero():
    rl = RateLimiter()
    assert rl.enabled == False
    ok, retry = rl.check(1)
    assert ok == True
    assert retry == 0


# --- per-minute limit ---

def test_per_minute_limit():
    rl = RateLimiter(per_minute=3)
    assert rl.enabled == True
    ok1, _ = rl.check(1)
    ok2, _ = rl.check(1)
    ok3, _ = rl.check(1)
    ok4, retry4 = rl.check(1)
    assert all([ok1, ok2, ok3]) == True
    assert ok4 == False
    assert retry4 > 0


# --- per-hour limit ---

def test_per_hour_limit():
    rl = RateLimiter(per_hour=2)
    ok1, _ = rl.check(1)
    ok2, _ = rl.check(1)
    ok3, retry3 = rl.check(1)
    assert all([ok1, ok2]) == True
    assert ok3 == False
    assert retry3 > 0


# --- user isolation ---

def test_user_isolation():
    rl = RateLimiter(per_minute=1)
    ok_a, _ = rl.check(100)
    ok_b, _ = rl.check(200)
    ok_a2, _ = rl.check(100)
    assert ok_a == True
    assert ok_b == True
    assert ok_a2 == False


# --- clear specific user ---

def test_clear_specific_user():
    rl = RateLimiter(per_minute=1)
    rl.check(1)
    rl.check(2)
    rl.clear(1)
    ok1, _ = rl.check(1)
    ok2, _ = rl.check(2)
    assert ok1 == True
    assert ok2 == False


# --- clear all ---

def test_clear_all():
    rl = RateLimiter(per_minute=1)
    rl.check(1)
    rl.check(2)
    rl.clear()
    ok1, _ = rl.check(1)
    ok2, _ = rl.check(2)
    assert ok1 == True
    assert ok2 == True


# --- sliding window expires ---

def test_sliding_window_expiry():
    rl = RateLimiter(per_minute=1)
    # Fake time: first request at T=0, second at T=61
    base = time.monotonic()
    with patch("app.ratelimit.time") as mock_time:
        mock_time.monotonic.return_value = base
        rl.check(1)
        # Blocked at T=0
        ok_blocked, _ = rl.check(1)
        assert ok_blocked == False
        # Allowed at T=61 (outside 60s window)
        mock_time.monotonic.return_value = base + 61
        ok_after, _ = rl.check(1)
        assert ok_after == True


# --- both limits ---

def test_both_limits_enforced():
    rl = RateLimiter(per_minute=10, per_hour=3)
    ok1, _ = rl.check(1)
    ok2, _ = rl.check(1)
    ok3, _ = rl.check(1)
    ok4, retry = rl.check(1)
    assert all([ok1, ok2, ok3]) == True
    assert ok4 == False
