"""Postgres test harness (Phase 12): one DB per worker, truncate between tests."""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

from psycopg import connect

from app.db.postgres_migrate import run_bootstrap


def get_test_postgres_base_url() -> str | None:
    """Return base Postgres URL for tests, or None if not configured.

    Use TEST_POSTGRES_BASE_URL or BOT_DATABASE_URL. Should point to a server
    where the test runner can create databases (e.g. postgresql://localhost/postgres).
    """
    url = (
        os.environ.get("TEST_POSTGRES_BASE_URL", "").strip()
        or os.environ.get("BOT_DATABASE_URL", "").strip()
    )
    if not url or not url.startswith("postgresql"):
        return None
    return url


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


def truncate_runtime_tables(conn) -> None:
    """Truncate bot_runtime tables (sessions, updates, work_items). Do not truncate schema_migrations."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE bot_runtime.work_items CASCADE")
        cur.execute("TRUNCATE TABLE bot_runtime.updates CASCADE")
        cur.execute("TRUNCATE TABLE bot_runtime.sessions CASCADE")
    conn.commit()


def bootstrap_test_db(conn) -> list[str]:
    """Apply full schema (run_bootstrap). Returns list of errors."""
    return run_bootstrap(conn)


def get_test_db_url(base_url: str, worker_id: str) -> str:
    """Return connection URL for the worker's test database."""
    db_name = f"test_bot_{worker_id}".replace("-", "_")
    return _replace_db_in_url(base_url, db_name)
