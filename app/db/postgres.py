"""Postgres connection pool and lifecycle (Phase 12)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from psycopg import connect
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Module-level pool cache: one pool per connection string.
_pools: dict[str, ConnectionPool] = {}


def get_pool(
    database_url: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
    connect_timeout: int = 10,
) -> ConnectionPool:
    """Return a connection pool for the given URL. Creates and caches if needed."""
    if database_url not in _pools:
        _pools[database_url] = ConnectionPool(
            conninfo=database_url,
            kwargs={"connect_timeout": connect_timeout},
            min_size=min_size,
            max_size=max_size,
            open=True,
        )
    return _pools[database_url]


@contextmanager
def get_connection(
    database_url: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
    connect_timeout: int = 10,
) -> Generator:
    """Yield a connection the pool for the given URL."""
    pool = get_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        connect_timeout=connect_timeout,
    )
    with pool.connection() as conn:
        yield conn


def close_pools() -> None:
    """Close all cached connection pools (for shutdown or test isolation)."""
    for url in list(_pools.keys()):
        pool = _pools.pop(url, None)
        if pool is not None:
            pool.close()


def _normalize_debug_sql(sql: str) -> str:
    """Translate simple qmark placeholders used by legacy debug-query tests."""
    return sql.replace("?", "%s")


class _DebugCursor:
    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def close(self) -> None:
        self._cursor.close()


class PostgresDebugConnection:
    """Small test-facing adapter that preserves the old debug_connection shape."""

    def __init__(self, database_url: str, *, search_path: str = "bot_runtime") -> None:
        self._conn = connect(database_url)
        self.row_factory = None
        with self._conn.cursor() as cur:
            cur.execute(f"SET search_path TO {search_path}")

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor(row_factory=dict_row)
        cur.execute(_normalize_debug_sql(sql), params)
        return _DebugCursor(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
