"""Single runtime backend seam.

Owns one selected session + transport backend pair. Shared Runtime and Local
Runtime both use this selector; runtime mode changes ingress/worker ownership,
not the storage backend choice.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import BotConfig

# Single backend instance. Set by init(); cleared or replaced by reset_for_test().
_backend: _Backend | None = None
log = logging.getLogger(__name__)


class _Backend:
    """Holds session, transport, and control-plane stores for one runtime."""

    __slots__ = (
        "session_store",
        "transport_store",
        "control_plane_store",
        "database_url",
        "pool_min",
        "pool_max",
        "connect_timeout",
    )

    def __init__(
        self,
        session_store: Any,
        transport_store: Any,
        control_plane_store: Any,
        *,
        database_url: str,
        pool_min: int,
        pool_max: int,
        connect_timeout: int,
    ) -> None:
        self.session_store = session_store
        self.transport_store = transport_store
        self.control_plane_store = control_plane_store
        self.database_url = database_url
        self.pool_min = pool_min
        self.pool_max = pool_max
        self.connect_timeout = connect_timeout


def is_initialized() -> bool:
    """Return whether the runtime backend has been initialized."""
    return _backend is not None


def _matches_config(config: BotConfig) -> bool:
    return (
        _backend is not None
        and _backend.database_url == config.database_url
        and _backend.pool_min == config.db_pool_min_size
        and _backend.pool_max == config.db_pool_max_size
        and _backend.connect_timeout == config.db_connect_timeout_seconds
    )


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


def control_plane_store():
    """Return the current control-plane store. Must call init(config) first."""
    if _backend is None:
        raise RuntimeError("runtime_backend.init(config) was not called before using control_plane_store()")
    return _backend.control_plane_store


def init(config: BotConfig) -> None:
    """Select and initialize the session and transport backend config. Call once at startup."""
    global _backend
    if not config.database_url:
        raise RuntimeError("OCTOPUS_DATABASE_URL must be set before runtime_backend.init(config)")
    if _matches_config(config):
        return
    if _backend is not None:
        reset_for_test()
    from app.control_plane.postgres_impl import PostgresControlPlaneStore
    from app.storage_postgres import PostgresSessionStore
    from app.work_queue_postgres_impl import PostgresTransportStore

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
        PostgresControlPlaneStore(
            config.database_url,
            pool_min=config.db_pool_min_size,
            pool_max=config.db_pool_max_size,
            connect_timeout=config.db_connect_timeout_seconds,
        ),
        database_url=config.database_url,
        pool_min=config.db_pool_min_size,
        pool_max=config.db_pool_max_size,
        connect_timeout=config.db_connect_timeout_seconds,
    )


def reset_for_test() -> None:
    """Clear current backend and close Postgres pools. For test isolation only."""
    global _backend
    if _backend is not None:
        try:
            _backend.session_store.close_all_db()
        except Exception:
            log.debug("Session store close failed during reset", exc_info=True)
        try:
            _backend.transport_store.close_all_transport_db()
        except Exception:
            log.debug("Transport store close failed during reset", exc_info=True)
        try:
            _backend.control_plane_store.close_all_control_plane_db()
        except Exception:
            log.debug("Control-plane store close failed during reset", exc_info=True)
    _backend = None
    try:
        from app.db.postgres import close_pools

        close_pools()
    except Exception:
        log.debug("Postgres pool close failed during reset", exc_info=True)
