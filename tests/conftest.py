"""Pytest configuration and shared fixtures.

Priority 4: per-test handler runtime isolation. Every test gets a clean
handler-global state before and after, so no ambient leakage between cases.
"""

import pytest


@pytest.fixture(autouse=True)
def reset_handler_runtime():
    """Reset handler globals and DB caches before and after each test (Priority 4)."""
    from tests.support.handler_support import reset_handler_test_runtime
    reset_handler_test_runtime()
    yield
    reset_handler_test_runtime()
