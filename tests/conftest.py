"""Pytest configuration and shared fixtures.

Priority 4: per-test handler runtime isolation. Every test gets a clean
handler-global state before and after, so no ambient leakage between cases.

Phase 12: Postgres test harness — one DB per pytest worker, truncate between
tests. Use fixture postgres_truncated when a test needs a real Postgres backend.
"""

import pytest


@pytest.fixture(autouse=True)
def reset_handler_runtime():
    """Reset handler globals and DB caches before and after each test (Priority 4)."""
    from tests.support.handler_support import reset_handler_test_runtime
    reset_handler_test_runtime()
    yield
    reset_handler_test_runtime()


# ---------------------------------------------------------------------------
# Phase 12: Postgres test harness
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def postgres_base_url():
    """Base Postgres URL for tests. Skips when TEST_POSTGRES_BASE_URL/BOT_DATABASE_URL not set."""
    from tests.support.postgres_support import get_test_postgres_base_url
    url = get_test_postgres_base_url()
    if not url:
        pytest.skip(
            "Postgres tests require TEST_POSTGRES_BASE_URL or BOT_DATABASE_URL"
        )
    return url


@pytest.fixture(scope="session")
def postgres_db_url(postgres_base_url, request):
    """One database per worker; schema applied once. Yields URL for that DB."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import (
        create_test_database,
        get_test_db_url,
        get_worker_id,
        bootstrap_test_db,
    )
    worker_id = get_worker_id(request.config)
    db_name = f"test_bot_{worker_id}".replace("-", "_")
    create_test_database(postgres_base_url, db_name)
    url = get_test_db_url(postgres_base_url, worker_id)
    with get_connection(url) as conn:
        errors = bootstrap_test_db(conn)
        if errors:
            raise RuntimeError(f"Postgres bootstrap failed: {errors}")
    yield url


@pytest.fixture
def postgres_truncated(postgres_db_url):
    """Postgres URL for current worker with runtime tables truncated (clean slate)."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import truncate_runtime_tables
    with get_connection(postgres_db_url) as conn:
        truncate_runtime_tables(conn)
    yield postgres_db_url
