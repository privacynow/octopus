"""Structural parity gates for backend store public methods."""

from __future__ import annotations

import inspect

from app.content_store_base import AbstractContentStore
from app.content_store_postgres import PostgresContentStore
from app.content_store_sqlite import SQLiteContentStore
from app.registry_service.store import RegistrySQLiteStore
from app.registry_service.store_base import AbstractRegistryStore
from app.registry_service.store_postgres import RegistryPostgresStore


def _public_methods(owner: type) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(owner, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_registry_store_backends_match_each_other_and_contract() -> None:
    contract_methods = _public_methods(AbstractRegistryStore)
    sqlite_methods = _public_methods(RegistrySQLiteStore)
    postgres_methods = _public_methods(RegistryPostgresStore)

    assert sqlite_methods == postgres_methods
    assert sqlite_methods == contract_methods


def test_content_store_backends_match_each_other_and_contract() -> None:
    contract_methods = _public_methods(AbstractContentStore)
    sqlite_methods = _public_methods(SQLiteContentStore)
    postgres_methods = _public_methods(PostgresContentStore)

    assert sqlite_methods == postgres_methods
    assert sqlite_methods == contract_methods


def test_removed_sqlite_only_store_methods_stay_gone() -> None:
    assert "publish_ui_timeline" not in _public_methods(RegistrySQLiteStore)
    assert "close" not in _public_methods(SQLiteContentStore)
