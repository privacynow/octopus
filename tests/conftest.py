"""Pytest configuration and shared fixtures.

Priority 4: per-test handler runtime isolation. Every test gets a clean
handler-global state before and after, so no ambient leakage between cases.

Phase 12: Postgres test harness — one DB per pytest worker, truncate between
tests. Use fixture postgres_truncated when a test needs a real Postgres backend.
"""

import os
import time
import uuid

import pytest

# Env var used by postgres_support.get_run_id(); value is path to run-unique file.
_POSTGRES_RUN_ID_FILE_ENV = "TELEGRAM_BOT_TEST_RUN_ID_FILE"


def pytest_configure(config):
    """Write run-scoped id to a unique file and set env so workers read the same id (no shared global file)."""
    if not hasattr(config, "workerinput"):
        run_id = f"{os.getpid()}_{int(time.time() * 1000)}"
        run_id_file = os.path.join(
            os.path.dirname(__file__), f".postgres_run_id.{uuid.uuid4().hex}"
        )
        try:
            with open(run_id_file, "w") as f:
                f.write(run_id)
            os.environ[_POSTGRES_RUN_ID_FILE_ENV] = run_id_file
            config._postgres_run_id_file = run_id_file  # for cleanup
        except OSError:
            pass


def pytest_unconfigure(config):
    """Remove the run-id file created by this invocation so concurrent runs don't read it later."""
    path = getattr(config, "_postgres_run_id_file", None)
    if path and os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            pass
        if os.environ.get(_POSTGRES_RUN_ID_FILE_ENV) == path:
            os.environ.pop(_POSTGRES_RUN_ID_FILE_ENV, None)


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
# Postgres URL comes only from a test container we start (never BOT_DATABASE_URL
# or env), so truncate/bootstrap never touch dev/staging/production.

@pytest.fixture(scope="session")
def postgres_base_url(request):
    """Base Postgres URL from a harness-started test container. Skips only when Docker unavailable.

    When Docker is available but container start/readiness fails, we fail loudly (P1), not skip.
    Run-scoped container name/port (P2) avoid collisions across parallel pytest invocations.
    """
    from tests.support.postgres_support import (
        get_run_id,
        get_worker_id,
        start_test_postgres_container,
        stop_test_postgres_container,
    )
    worker_id = get_worker_id(request.config)
    run_id = get_run_id()
    url = start_test_postgres_container(worker_id, run_id)
    if not url:
        pytest.skip(
            "Postgres tests require Docker (to run a test-only Postgres container). "
            "We do not use BOT_DATABASE_URL/TEST_POSTGRES_BASE_URL to avoid touching dev/staging/prod."
        )
    yield url
    stop_test_postgres_container(worker_id, run_id)


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
