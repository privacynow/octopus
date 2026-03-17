"""Factory helpers for runtime content-store selection."""

from __future__ import annotations

from pathlib import Path

from app.content_store_base import AbstractContentStore


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
