"""Tests for the sliding-window rate limiter."""

import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.support.assertions import Checks
from app.ratelimit import RateLimiter

checks = Checks()

# --- disabled by default ---
print("\n=== disabled when limits are zero ===")
rl = RateLimiter()
checks.check("disabled by default", rl.enabled, False)
ok, retry = rl.check(1)
checks.check("always allowed when disabled", ok, True)
checks.check("no retry when disabled", retry, 0)

# --- per-minute limit ---
print("\n=== per-minute limit ===")
rl = RateLimiter(per_minute=3)
checks.check("enabled with per_minute", rl.enabled, True)
ok1, _ = rl.check(1)
ok2, _ = rl.check(1)
ok3, _ = rl.check(1)
ok4, retry4 = rl.check(1)
checks.check("first 3 allowed", all([ok1, ok2, ok3]), True)
checks.check("4th blocked", ok4, False)
checks.check("retry > 0", retry4 > 0, True)

# --- per-hour limit ---
print("\n=== per-hour limit ===")
rl = RateLimiter(per_hour=2)
ok1, _ = rl.check(1)
ok2, _ = rl.check(1)
ok3, retry3 = rl.check(1)
checks.check("first 2 allowed", all([ok1, ok2]), True)
checks.check("3rd blocked by hour limit", ok3, False)
checks.check("hour retry > 0", retry3 > 0, True)

# --- user isolation ---
print("\n=== user isolation ===")
rl = RateLimiter(per_minute=1)
ok_a, _ = rl.check(100)
ok_b, _ = rl.check(200)
ok_a2, _ = rl.check(100)
checks.check("user 100 first allowed", ok_a, True)
checks.check("user 200 first allowed", ok_b, True)
checks.check("user 100 second blocked", ok_a2, False)

# --- clear specific user ---
print("\n=== clear specific user ===")
rl = RateLimiter(per_minute=1)
rl.check(1)
rl.check(2)
rl.clear(1)
ok1, _ = rl.check(1)
ok2, _ = rl.check(2)
checks.check("user 1 cleared, allowed again", ok1, True)
checks.check("user 2 still blocked", ok2, False)

# --- clear all ---
print("\n=== clear all ===")
rl = RateLimiter(per_minute=1)
rl.check(1)
rl.check(2)
rl.clear()
ok1, _ = rl.check(1)
ok2, _ = rl.check(2)
checks.check("all cleared, user 1 allowed", ok1, True)
checks.check("all cleared, user 2 allowed", ok2, True)

# --- sliding window expires ---
print("\n=== sliding window expiry ===")
rl = RateLimiter(per_minute=1)
# Fake time: first request at T=0, second at T=61
base = time.monotonic()
with patch("app.ratelimit.time") as mock_time:
    mock_time.monotonic.return_value = base
    rl.check(1)
    # Blocked at T=0
    ok_blocked, _ = rl.check(1)
    checks.check("blocked at same time", ok_blocked, False)
    # Allowed at T=61 (outside 60s window)
    mock_time.monotonic.return_value = base + 61
    ok_after, _ = rl.check(1)
    checks.check("allowed after window expires", ok_after, True)

# --- both limits ---
print("\n=== both limits enforced ===")
rl = RateLimiter(per_minute=10, per_hour=3)
ok1, _ = rl.check(1)
ok2, _ = rl.check(1)
ok3, _ = rl.check(1)
ok4, retry = rl.check(1)
checks.check("3 allowed under hour cap", all([ok1, ok2, ok3]), True)
checks.check("4th blocked by hour limit", ok4, False)

checks.run_and_exit()
