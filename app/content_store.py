"""Factory helpers and runtime singleton for the shared content store."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.content_store_base import AbstractContentStore

_store: AbstractContentStore | None = None
_store_key: tuple[str, str, int, int, int] | None = None
log = logging.getLogger(__name__)


def build_content_store(
    *,
    data_dir: Path,
    database_url: str = "",
    pool_min: int = 1,
    pool_max: int = 10,
    connect_timeout: int = 10,
) -> AbstractContentStore:
    if database_url:
        from app.content_store_postgres import PostgresContentStore

        return PostgresContentStore(
            database_url,
            pool_min=pool_min,
            pool_max=pool_max,
            connect_timeout=connect_timeout,
        )

    from app.content_store_sqlite import SQLiteContentStore

    return SQLiteContentStore(data_dir / "content.db")


def init_content_store(
    *,
    data_dir: Path,
    database_url: str = "",
    pool_min: int = 1,
    pool_max: int = 10,
    connect_timeout: int = 10,
) -> AbstractContentStore:
    """Initialize and seed the shared content store for the current runtime."""
    global _store, _store_key
    key = (str(data_dir), database_url, pool_min, pool_max, connect_timeout)
    if _store is None or _store_key != key:
        _store = build_content_store(
            data_dir=data_dir,
            database_url=database_url,
            pool_min=pool_min,
            pool_max=pool_max,
            connect_timeout=connect_timeout,
        )
        _store_key = key
    from app.content_seed import seed_builtin_content

    seed_builtin_content(_store)
    return _store


def init_content_store_for_config(config) -> AbstractContentStore:
    return init_content_store(
        data_dir=config.data_dir,
        database_url=config.database_url,
        pool_min=config.db_pool_min_size,
        pool_max=config.db_pool_max_size,
        connect_timeout=config.db_connect_timeout_seconds,
    )


def get_content_store() -> AbstractContentStore:
    """Return the active content store, lazily seeded runtime env when needed."""
    if _store is not None:
        return _store
    data_dir = Path(os.environ.get("BOT_DATA_DIR", "/tmp/telegram-agent-content")).expanduser()
    database_url = os.environ.get("BOT_DATABASE_URL", "").strip()
    pool_min = int(os.environ.get("BOT_DB_POOL_MIN_SIZE", "1") or "1")
    pool_max = int(os.environ.get("BOT_DB_POOL_MAX_SIZE", "10") or "10")
    connect_timeout = int(os.environ.get("BOT_DB_CONNECT_TIMEOUT_SECONDS", "10") or "10")
    return init_content_store(
        data_dir=data_dir,
        database_url=database_url,
        pool_min=pool_min,
        pool_max=pool_max,
        connect_timeout=connect_timeout,
    )


def reset_for_test() -> None:
    global _store, _store_key
    close = getattr(_store, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:
            log.debug(
                "Content-store cleanup failed during test reset: %s",
                exc.__class__.__name__,
            )
    _store = None
    _store_key = None
    try:
        from app.db.postgres import close_pools

        close_pools()
    except Exception as exc:
        log.debug(
            "Postgres pool cleanup failed during content-store test reset: %s",
            exc.__class__.__name__,
        )
