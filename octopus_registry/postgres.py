"""Registry-local Postgres connection pool helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from psycopg_pool import ConnectionPool

_pools: dict[str, ConnectionPool] = {}


def get_pool(
    database_url: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
    connect_timeout: int = 10,
) -> ConnectionPool:
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
    pool = get_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        connect_timeout=connect_timeout,
    )
    with pool.connection() as conn:
        yield conn


def close_pools() -> None:
    for database_url in list(_pools.keys()):
        pool = _pools.pop(database_url, None)
        if pool is not None:
            pool.close()
