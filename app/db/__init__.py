"""Postgres runtime backend (Phase 12).

- postgres: connection pool and lifecycle
- postgres_migrate: versioned SQL runner (bootstrap / update)
- postgres_doctor: connectivity and schema validation
"""

from app.db.postgres import get_pool, get_connection, close_pools

__all__ = ["get_pool", "get_connection", "close_pools"]
