"""Registry store backend selector."""

from __future__ import annotations

import logging

from .authority import StoreBackedRegistryAuthority
from .config import load_registry_config
from .store_base import AbstractRegistryStore
from .store_postgres import RegistryPostgresStore

_store: AbstractRegistryStore | None = None
_authority: StoreBackedRegistryAuthority | None = None
log = logging.getLogger(__name__)


def get_registry_store() -> AbstractRegistryStore:
    """Return the configured registry store backend."""
    global _store
    if _store is None:
        config = load_registry_config()
        if not config.database_url:
            raise RuntimeError("OCTOPUS_DATABASE_URL must be set before the registry can start.")
        _store = RegistryPostgresStore(config.database_url, config=config)
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
        from .postgres import close_pools

        close_pools()
    except Exception:
        log.debug("Registry store backend reset failed to close Postgres pools", exc_info=True)
