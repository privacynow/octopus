"""Registry store backend selector."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.registry_service.authority import StoreBackedRegistryAuthority
from app.registry_service.store_base import AbstractRegistryStore

_store: AbstractRegistryStore | None = None
_authority: StoreBackedRegistryAuthority | None = None
log = logging.getLogger(__name__)


def get_registry_store() -> AbstractRegistryStore:
    """Return the configured registry store backend."""
    global _store
    if _store is None:
        database_url = os.environ.get("REGISTRY_DATABASE_URL", "").strip()
        if database_url:
            from app.registry_service.store_postgres import RegistryPostgresStore

            _store = RegistryPostgresStore(database_url)
        else:
            db_path = Path(os.environ.get("REGISTRY_DB_PATH", "/tmp/octopus-registry/registry.sqlite3"))
            from app.registry_service.store import RegistrySQLiteStore

            _store = RegistrySQLiteStore(db_path)
    return _store


def get_registry_authority() -> StoreBackedRegistryAuthority:
    """Return the typed registry authority facade for the configured backend."""
    global _authority
    if _authority is None:
        _authority = StoreBackedRegistryAuthority(get_registry_store())
    return _authority


def reset_for_test() -> None:
    """Clear the cached registry store backend for tests."""
    global _store, _authority
    _store = None
    _authority = None
    try:
        from app.db.postgres import close_pools

        close_pools()
    except Exception:
        log.debug("Registry store backend reset failed to close Postgres pools", exc_info=True)
