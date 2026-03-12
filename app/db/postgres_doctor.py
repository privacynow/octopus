"""Postgres connectivity and schema validation (Phase 12)."""

from __future__ import annotations

from typing import Any

from app.db.postgres_migrate import current_schema_version, _get_max_applied_version

# Required runtime objects (plan: bot_runtime schema, tables, idx_one_claimed_per_chat)
_REQUIRED_SCHEMA = "bot_runtime"
_REQUIRED_TABLES = ("sessions", "updates", "work_items", "schema_migrations")
_REQUIRED_INDEX = "idx_one_claimed_per_chat"


def run_doctor(conn: Any) -> list[str]:
    """Validate connectivity, schema version, and required tables/indexes. Returns list of errors."""
    errors: list[str] = []

    # Schema exists
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.schemata
            WHERE schema_name = %s
            """,
            (_REQUIRED_SCHEMA,),
        )
        if cur.fetchone() is None:
            errors.append(f"Schema '{_REQUIRED_SCHEMA}' does not exist. Run DB bootstrap.")
            return errors  # No point checking tables

    # schema_migrations exists and has current version
    max_applied = _get_max_applied_version(conn)
    expected = current_schema_version()
    if max_applied is None:
        errors.append(
            "Table bot_runtime.schema_migrations missing or empty. Run DB bootstrap."
        )
        return errors
    if max_applied < expected:
        errors.append(
            f"Schema version {max_applied} is behind current build ({expected}). Run DB update."
        )
    if max_applied > expected:
        errors.append(
            f"Schema version {max_applied} is newer than supported ({expected}). Upgrade the bot."
        )

    # Required tables
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s
            """,
            (_REQUIRED_SCHEMA,),
        )
        existing = {row[0] for row in cur.fetchall()}
    for table in _REQUIRED_TABLES:
        if table not in existing:
            errors.append(f"Table bot_runtime.{table} missing. Run DB bootstrap.")

    # Required partial unique index (one claimed per chat)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM pg_indexes
            WHERE schemaname = %s AND tablename = 'work_items' AND indexname = %s
            """,
            (_REQUIRED_SCHEMA, _REQUIRED_INDEX),
        )
        if cur.fetchone() is None:
            errors.append(
                f"Index bot_runtime.work_items.{_REQUIRED_INDEX} missing. Run DB bootstrap."
            )

    return errors
