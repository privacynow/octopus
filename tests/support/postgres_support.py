"""Postgres test harness (Phase 12): one DB per worker, truncate between tests.

SAFETY: Truncation and schema changes must only run against a Postgres instance
that the harness started (test Docker container). We never use BOT_DATABASE_URL
or TEST_POSTGRES_BASE_URL for destructive operations, to avoid touching dev/
staging/production. When Docker is available we start a dedicated container;
when it is not, Postgres tests are skipped.

Run isolation: Container names and ports include a run-scoped id (see get_run_id)
so parallel pytest invocations (e.g. two developers or two branches) do not
kill each other's containers or bind to the same ports.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from psycopg import connect

from app.db.postgres_init import run_init

# Test-only container: prefix + worker + run_id for name; base port + worker offset + run offset for port.
TEST_POSTGRES_CONTAINER_PREFIX = "telegram_bot_test_pg"
TEST_POSTGRES_BASE_PORT = 15432
# Max port offset so base + worker_offset + run_offset stays < 65536 (worker_offset at most ~10).
_TEST_PORT_RUN_RANGE = 40000
TEST_POSTGRES_IMAGE = "postgres:16-alpine"
TEST_POSTGRES_USER = "bot"
TEST_POSTGRES_PASSWORD = "bot"
TEST_POSTGRES_DB = "bot"

# Env var set by main pytest process: path to a run-unique file containing run_id (avoids
# concurrent runs overwriting a single shared file). Workers inherit env and read that path.
_POSTGRES_RUN_ID_FILE_ENV = "TELEGRAM_BOT_TEST_RUN_ID_FILE"


def _read_run_id() -> str | None:
    """Read run id the file path in TELEGRAM_BOT_TEST_RUN_ID_FILE, if set. Returns None otherwise."""
    path = os.environ.get(_POSTGRES_RUN_ID_FILE_ENV)
    if not path:
        return None
    try:
        p = Path(path)
        if p.exists():
            return p.read_text().strip() or None
    except OSError:
        pass
    return None


def get_run_id() -> str:
    """Return a run-scoped id so container names/ports do not collide across pytest invocations.

    Main process writes run_id to a unique file (see conftest) and sets TELEGRAM_BOT_TEST_RUN_ID_FILE
    so workers inherit the path and read the same run_id. Single-process runs use the same mechanism.
    """
    rid = _read_run_id()
    if rid:
        return rid
    return f"{os.getpid()}_{int(time.time() * 1000)}"


def docker_available() -> bool:
    """True if Docker is installed and reachable; fail loudly on daemon errors."""
    last_error = ""
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except FileNotFoundError:
            return False
        except subprocess.TimeoutExpired:
            last_error = "docker info timed out"
        else:
            if r.returncode == 0:
                return True
            stderr = (r.stderr or "").strip() or "(no stderr)"
            last_error = f"docker info exited {r.returncode}: {stderr}"
        if attempt < 2:
            time.sleep(1.0)
    raise RuntimeError(
        f"docker info failed while checking test Postgres availability after 3 attempts: "
        f"{last_error or 'unknown Docker error'}"
    )


def _worker_index(worker_id: str) -> int:
    """Numeric worker index for port offset (gw0->0, gw1->1, master->0)."""
    if worker_id == "master":
        return 0
    if worker_id.startswith("gw"):
        try:
            return int(worker_id[2:])
        except ValueError:
            pass
    return 0


def _worker_port(worker_id: str, run_id: str) -> int:
    """Distinct port per worker and per run. Run offset uses hashlib so it is stable across processes."""
    worker_idx = _worker_index(worker_id)
    run_offset = (
        int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) % _TEST_PORT_RUN_RANGE
    )
    return TEST_POSTGRES_BASE_PORT + worker_idx + run_offset


def _container_name(worker_id: str, run_id: str) -> str:
    """Unique container name for this worker and run (safe for parallel pytest invocations)."""
    safe_worker = worker_id.replace("-", "_")
    safe_run = run_id.replace("-", "_")[:16]
    return f"{TEST_POSTGRES_CONTAINER_PREFIX}_{safe_worker}_{safe_run}"


def start_test_postgres_container(worker_id: str = "master", run_id: str | None = None) -> str | None:
    """Start a test-only Postgres container. Returns base URL or None only when Docker is unavailable.

    When Docker is available but container start or readiness fails, raises RuntimeError (P1:
    do not treat startup failures as skips). worker_id and run_id determine container name and
    port so xdist workers and parallel pytest runs do not collide (P2).
    """
    if not docker_available():
        return None
    rid = run_id or get_run_id()
    container_name = _container_name(worker_id, rid)
    port = _worker_port(worker_id, rid)
    # Remove any leftover container a previous crash (same run only)
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        timeout=10,
        check=False,
    )
    r = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name", container_name,
            "-p", f"127.0.0.1:{port}:5432",
            "-e", f"POSTGRES_USER={TEST_POSTGRES_USER}",
            "-e", f"POSTGRES_PASSWORD={TEST_POSTGRES_PASSWORD}",
            "-e", f"POSTGRES_DB={TEST_POSTGRES_DB}",
            TEST_POSTGRES_IMAGE,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if r.returncode != 0:
        stderr = (r.stderr or "").strip() or "(no stderr)"
        raise RuntimeError(
            f"Postgres test container failed to start (docker run exited {r.returncode}). "
            f"Container name: {container_name}. stderr: {stderr}"
        )
    base_url = f"postgresql://{TEST_POSTGRES_USER}:{TEST_POSTGRES_PASSWORD}@127.0.0.1:{port}/{TEST_POSTGRES_DB}"
    # Wait for Postgres to accept connections
    for attempt in range(50):
        try:
            conn = connect(base_url, connect_timeout=2)
            conn.close()
            return base_url
        except Exception:
            time.sleep(0.5)
    stop_test_postgres_container(worker_id, rid)
    raise RuntimeError(
        f"Postgres test container started but did not accept connections within ~25s. "
        f"Container: {container_name}, port: {port}. Check docker logs {container_name}."
    )


def stop_test_postgres_container(worker_id: str = "master", run_id: str | None = None) -> None:
    """Stop and remove the test Postgres container for this worker/run. Idempotent."""
    rid = run_id or get_run_id()
    container_name = _container_name(worker_id, rid)
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        timeout=15,
        check=False,
    )


def stop_test_postgres_containers_for_run(run_id: str) -> None:
    """Best-effort cleanup for every worker container owned by a pytest run."""
    safe_run = str(run_id or "").replace("-", "_")[:16]
    if not safe_run:
        return
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--format",
                "{{.Names}}",
                "--filter",
                f"name={TEST_POSTGRES_CONTAINER_PREFIX}_",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return
    if result.returncode != 0:
        return
    names = [
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip().startswith(f"{TEST_POSTGRES_CONTAINER_PREFIX}_")
        and line.strip().endswith(f"_{safe_run}")
    ]
    if not names:
        return
    subprocess.run(
        ["docker", "rm", "-f", *names],
        capture_output=True,
        timeout=30,
        check=False,
    )


def get_worker_id(config) -> str:
    """Return pytest worker id (e.g. gw0, gw1) or 'master' when not under xdist."""
    try:
        return config.workerinput["workerid"]
    except (AttributeError, KeyError, TypeError):
        return "master"


def _replace_db_in_url(url: str, db_name: str) -> str:
    """Return a new URL with the database name replaced."""
    parsed = urlparse(url)
    # path is like /postgres or /botdb; we want /db_name
    new_path = "/" + db_name.lstrip("/")
    new = parsed._replace(path=new_path)
    return urlunparse(new)


def create_test_database(base_url: str, db_name: str) -> None:
    """Create a database with the given name. Uses base_url for connection (autocommit)."""
    # Connect to default DB (e.g. postgres) with autocommit to run CREATE DATABASE
    conn = connect(base_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        conn.close()


_RUNTIME_TABLES = (
    "bot_runtime.control_plane_commands",
    "bot_runtime.deferred_notifications",
    "bot_runtime.work_items",
    "bot_runtime.worker_heartbeats",
    "bot_runtime.updates",
    "bot_runtime.sessions",
    "bot_runtime.usage_log",
    "bot_runtime.user_access",
)
_REGISTRY_TABLES = (
    "agent_registry.deliveries",
    "agent_registry.events",
    "agent_registry.routed_tasks",
    "agent_registry.protocol_transitions",
    "agent_registry.protocol_artifacts",
    "agent_registry.protocol_stage_executions",
    "agent_registry.protocol_run_participants",
    "agent_registry.protocol_runs",
    "agent_registry.protocol_definition_versions",
    "agent_registry.protocol_definitions",
    "agent_registry.conversations",
    "agent_registry.agents",
    "agent_registry.skills_override",
    "agent_registry.meta",
)
_CONTENT_TABLES = (
    "bot_content.skill_files",
    "bot_content.skill_approval_records",
    "bot_content.provider_guidance_approval_records",
    "bot_content.skill_revisions",
    "bot_content.provider_guidance_revisions",
    "bot_content.skill_tracks",
    "bot_content.provider_guidance_tracks",
    "bot_content.skill_namespaces",
)
_CREDENTIAL_TABLES = ("bot_credentials.credentials",)


def _truncate_tables(conn, tables: tuple[str, ...]) -> None:
    if not tables:
        return
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
    conn.commit()


def truncate_all_test_tables(conn) -> None:
    """Reset every test-owned schema group with one DB round trip."""
    _truncate_tables(
        conn,
        _RUNTIME_TABLES + _REGISTRY_TABLES + _CONTENT_TABLES + _CREDENTIAL_TABLES,
    )


def truncate_runtime_tables(conn) -> None:
    """Truncate bot_runtime tables used by runtime and transport tests.

    Must only be called for connections to the harness-started test Postgres container,
    never for dev/staging/production (see module docstring).
    """
    _truncate_tables(conn, _RUNTIME_TABLES)


def truncate_registry_tables(conn) -> None:
    """Truncate registry tables in the test schema. Safe only for harness-owned DBs."""
    _truncate_tables(conn, _REGISTRY_TABLES)


def truncate_content_tables(conn) -> None:
    """Reset the dedicated content schema in the test database."""
    _truncate_tables(conn, _CONTENT_TABLES)


def truncate_credential_tables(conn) -> None:
    """Reset the dedicated credential schema in the test database."""
    _truncate_tables(conn, _CREDENTIAL_TABLES)


def init_test_db(conn) -> list[str]:
    """Apply the current schema (run_init). Returns list of errors."""
    return run_init(conn)


def get_test_db_url(base_url: str, worker_id: str) -> str:
    """Return connection URL for the worker's test database."""
    db_name = f"test_bot_{worker_id}".replace("-", "_")
    return _replace_db_in_url(base_url, db_name)
