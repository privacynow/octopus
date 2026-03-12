"""Postgres connection pool and lifecycle (Phase 12)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

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
            min_size=min_size,
            max_size=max_size,
            connect_timeout=connect_timeout,
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
    """Yield a connection from the pool for the given URL."""
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
