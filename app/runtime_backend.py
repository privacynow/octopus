"""Phase 13: Single backend seam. Owns one selected backend (session + transport). No selection state elsewhere."""

from __future__ import annotations

from typing import Any

from app.config import BotConfig

# Single backend instance. Set by init(); cleared or replaced by reset_for_test().
_backend: _Backend | None = None


class _Backend:
    """Holds session and transport store for one runtime. No backend branching outside this module."""

    __slots__ = ("session_store", "transport_store")

    def __init__(self, session_store: Any, transport_store: Any) -> None:
        self.session_store = session_store
        self.transport_store = transport_store


def session_store():
    """Return the current session store. Must call init(config) first."""
    if _backend is None:
        raise RuntimeError("runtime_backend.init(config) was not called before using session_store()")
    return _backend.session_store


def transport_store():
    """Return the current transport store. Must call init(config) first."""
    if _backend is None:
        raise RuntimeError("runtime_backend.init(config) was not called before using transport_store()")
    return _backend.transport_store


def init(config: BotConfig) -> None:
    """Select and initialize the session and transport backend from config. Call once at startup."""
    global _backend
    if config.runtime_mode != "local":
        raise ValueError(
            f"Only Local Runtime is supported (BOT_RUNTIME_MODE=local). "
            f"Got BOT_RUNTIME_MODE={config.runtime_mode!r}. "
            "Shared Runtime is not available until Phase 18."
        )
    if config.database_url:
        from app.storage_postgres import PostgresSessionStore
        from app.work_queue_postgres import PostgresTransportStore
        _backend = _Backend(
            PostgresSessionStore(
                config.database_url,
                pool_min=config.db_pool_min_size,
                pool_max=config.db_pool_max_size,
                connect_timeout=config.db_connect_timeout_seconds,
            ),
            PostgresTransportStore(
                config.database_url,
                pool_min=config.db_pool_min_size,
                pool_max=config.db_pool_max_size,
                connect_timeout=config.db_connect_timeout_seconds,
            ),
        )
    else:
        from app.storage_sqlite import SQLiteSessionStore
        from app.work_queue_sqlite import SQLiteTransportStore
        _backend = _Backend(SQLiteSessionStore(), SQLiteTransportStore())


def reset_for_test() -> None:
    """Clear current backend and install a fresh SQLite backend. For test isolation only."""
    global _backend
    if _backend is not None:
        try:
            _backend.session_store.close_all_db()
        except Exception:
            pass
        try:
            _backend.transport_store.close_all_transport_db()
        except Exception:
            pass
    from app.storage_sqlite import SQLiteSessionStore
    from app.work_queue_sqlite import SQLiteTransportStore
    _backend = _Backend(SQLiteSessionStore(), SQLiteTransportStore())
