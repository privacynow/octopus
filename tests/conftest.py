"""Pytest configuration and shared fixtures.

Priority 4: per-test handler runtime isolation. Every test gets a clean
handler-global state before and after, so no ambient leakage between cases.

Phase 12: Postgres test harness — one DB per pytest worker, truncate only for
tests that need Postgres. Use fixture postgres_truncated when a test needs a
real Postgres backend.
"""

import os
import time
import uuid
from pathlib import Path

import pytest

# Env var used by postgres_support.get_run_id(); value is path to run-unique file.
_POSTGRES_RUN_ID_FILE_ENV = "TELEGRAM_BOT_TEST_RUN_ID_FILE"
_RUNTIME_ENV_PREFIXES = (
    "BOT_",
    "TELEGRAM_",
    "OCTOPUS_",
    "REGISTRY_",
    "CLAUDE_",
    "CODEX_",
)
_POSTGRES_FIXTURE_NAMES = frozenset(
    {
        "postgres_db_url",
        "postgres_truncated",
        "postgres_registry_truncated",
        "postgres_content_truncated",
        "postgres_credentials_truncated",
    }
)
_POSTGRES_TRUNCATING_FIXTURE_NAMES = frozenset(
    {
        "postgres_truncated",
        "postgres_registry_truncated",
        "postgres_content_truncated",
        "postgres_credentials_truncated",
    }
)
_POSTGRES_ENV_DEFAULT_FILES = frozenset(
    {
        # These tests exercise FastAPI/runtime paths that read OCTOPUS_DATABASE_URL
        # through application config instead of declaring a DB fixture on each case.
        "tests/test_artifact_runtime.py",
        "tests/test_agents.py",
        "tests/test_cancel.py",
        "tests/test_channel_egress_factory.py",
        "tests/test_control_plane_ports.py",
        "tests/test_doctor.py",
        "tests/test_execution_context.py",
        "tests/test_handlers.py",
        "tests/test_handlers_admin.py",
        "tests/test_handlers_approval.py",
        "tests/test_handlers_codex.py",
        "tests/test_handlers_credentials.py",
        "tests/test_handlers_delegation.py",
        "tests/test_handlers_export.py",
        "tests/test_handlers_output.py",
        "tests/test_handlers_ratelimit.py",
        "tests/test_handlers_store.py",
        "tests/test_invariants.py",
        "tests/test_lifecycle_workflows.py",
        "tests/test_protocol_telegram.py",
        "tests/test_registry.py",
        "tests/test_registry_adapter.py",
        "tests/test_registry_mirroring.py",
        "tests/test_registry_service.py",
        "tests/test_request_flow.py",
        "tests/test_runtime_health.py",
        "tests/test_runtime_process_profile.py",
        "tests/test_runtime_dispatch_boundary.py",
        "tests/test_runtime_skill_use_cases.py",
        "tests/test_sdk_certification_profiles.py",
        "tests/test_sdk_composition.py",
        "tests/test_session_runtime.py",
        "tests/test_shared_runtime.py",
        "tests/test_skill_inspection.py",
        "tests/test_skills.py",
        "tests/test_store.py",
        "tests/test_store_e2e.py",
        "tests/test_telegram_channel_egress.py",
        "tests/test_telegram_channel_state.py",
        "tests/test_telegram_delegation_channel.py",
        "tests/test_telegram_progress_module.py",
        "tests/test_telegram_runtime_skills.py",
        "tests/test_transport.py",
        "tests/test_worker_workflows.py",
        "tests/test_workitem_integration.py",
    }
)


def _repo_relative_test_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()



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


def pytest_collection_modifyitems(config, items):
    """Mark Postgres-backed tests from their declared fixtures or legacy module needs."""
    del config
    postgres_marker = pytest.mark.postgres
    for item in items:
        path = _repo_relative_test_path(item.path)
        if (
            _POSTGRES_FIXTURE_NAMES.intersection(getattr(item, "fixturenames", ()))
            or path in _POSTGRES_ENV_DEFAULT_FILES
        ):
            item.add_marker(postgres_marker)


def pytest_unconfigure(config):
    """Remove the run-id file created by this invocation so concurrent runs don't read it later."""
    path = getattr(config, "_postgres_run_id_file", None)
    run_id = None
    if path and os.path.isfile(path):
        try:
            with open(path) as f:
                run_id = f.read().strip() or None
        except OSError:
            run_id = None
    if run_id:
        try:
            from tests.support.postgres_support import stop_test_postgres_containers_for_run

            stop_test_postgres_containers_for_run(run_id)
        except Exception:
            pass
    if path and os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            pass
        if os.environ.get(_POSTGRES_RUN_ID_FILE_ENV) == path:
            os.environ.pop(_POSTGRES_RUN_ID_FILE_ENV, None)


@pytest.fixture(autouse=True)
def reset_handler_runtime():
    """Reset handler globals before and after each test without forcing DB startup."""
    from tests.support.handler_support import reset_handler_test_runtime
    from octopus_registry.backend import reset_for_test as reset_registry_store

    reset_registry_store()
    reset_handler_test_runtime()
    yield
    reset_handler_test_runtime()
    reset_registry_store()


@pytest.fixture(autouse=True)
def restore_runtime_env():
    """Restore runtime-related env vars after each test to prevent cross-test leaks."""
    before = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(_RUNTIME_ENV_PREFIXES)
    }
    yield
    current_keys = [
        key
        for key in os.environ
        if key.startswith(_RUNTIME_ENV_PREFIXES)
    ]
    for key in current_keys:
        if key not in before:
            os.environ.pop(key, None)
    for key, value in before.items():
        os.environ[key] = value


@pytest.fixture(autouse=True)
def postgres_env_for_db_tests(request):
    """Expose and reset the harness-owned DB only for tests that actually use it.

    Most tests in this repository are pure unit or contract tests. Pulling in
    postgres_db_url from a global autouse fixture makes all of them start Docker
    and pay truncation cost. This fixture keeps the old safety contract for DB
    tests while letting pure tests stay pure.
    """
    fixturenames = set(getattr(request, "fixturenames", ()))
    uses_postgres = bool(
        _POSTGRES_FIXTURE_NAMES.intersection(fixturenames)
        or request.node.get_closest_marker("postgres")
    )
    if not uses_postgres:
        yield
        return

    database_url = request.getfixturevalue("postgres_db_url")
    previous = os.environ.get("OCTOPUS_DATABASE_URL")
    os.environ["OCTOPUS_DATABASE_URL"] = database_url

    should_default_truncate = (
        "postgres_db_url" in fixturenames
        and not _POSTGRES_TRUNCATING_FIXTURE_NAMES.intersection(fixturenames)
    ) or _repo_relative_test_path(request.node.path) in _POSTGRES_ENV_DEFAULT_FILES
    if should_default_truncate:
        from app.db.postgres import get_connection
        from tests.support.postgres_support import truncate_all_test_tables

        with get_connection(database_url) as conn:
            truncate_all_test_tables(conn)

    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OCTOPUS_DATABASE_URL", None)
        else:
            os.environ["OCTOPUS_DATABASE_URL"] = previous


# ---------------------------------------------------------------------------
# Phase 12: Postgres test harness
# ---------------------------------------------------------------------------
# Postgres URL comes only a test container we start (never BOT_DATABASE_URL
# or env), so truncate/init never touch dev/staging/production.

@pytest.fixture(scope="session")
def postgres_base_url(request):
    """Base Postgres URL a harness-started test container. Skips only when Docker unavailable.

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
        init_test_db,
    )
    worker_id = get_worker_id(request.config)
    db_name = f"test_bot_{worker_id}".replace("-", "_")
    create_test_database(postgres_base_url, db_name)
    url = get_test_db_url(postgres_base_url, worker_id)
    with get_connection(url) as conn:
        errors = init_test_db(conn)
        if errors:
            raise RuntimeError(f"Postgres init failed: {errors}")
    yield url


@pytest.fixture
def postgres_truncated(postgres_db_url):
    """Postgres URL for current worker with runtime tables truncated (clean slate)."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import truncate_runtime_tables
    with get_connection(postgres_db_url) as conn:
        truncate_runtime_tables(conn)
    yield postgres_db_url


@pytest.fixture
def postgres_registry_truncated(postgres_db_url):
    """Postgres URL for current worker with registry tables truncated (clean slate)."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import truncate_registry_tables

    with get_connection(postgres_db_url) as conn:
        truncate_registry_tables(conn)
    yield postgres_db_url


@pytest.fixture
def postgres_content_truncated(postgres_db_url):
    """Postgres URL for current worker with dedicated content schema reset."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import truncate_content_tables

    with get_connection(postgres_db_url) as conn:
        truncate_content_tables(conn)
    yield postgres_db_url


@pytest.fixture
def postgres_credentials_truncated(postgres_db_url):
    """Postgres URL for current worker with dedicated credential schema reset."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import truncate_credential_tables

    with get_connection(postgres_db_url) as conn:
        truncate_credential_tables(conn)
    yield postgres_db_url
