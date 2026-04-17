"""Current-schema Postgres initializer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.postgres_doctor import run_doctor
from octopus_sdk.protocol_bootstrap import ensure_builtin_protocols

_INIT_SQL_PATH = Path(__file__).resolve().parent / "init.sql"
_OCTOPUS_SCHEMAS = ("bot_runtime", "agent_registry", "bot_content", "bot_credentials")


def _existing_octopus_schemas(conn: Any) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = ANY(%s)
            """,
            (list(_OCTOPUS_SCHEMAS),),
        )
        return {str(row[0]) for row in cur.fetchall()}


def run_init(conn: Any) -> list[str]:
    """Apply the current canonical schema and verify it matches the build.

    `init.sql` is the single source of truth for additive schema bootstrap.
    Reapplying it to an existing database is allowed so newly added tables,
    indexes, and other `IF NOT EXISTS` objects can be created in place.

    Older or incompatible objects are still rejected after the apply step when
    the resulting schema does not satisfy the current doctor checks.
    """
    sql = _INIT_SQL_PATH.read_text(encoding="utf-8")
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        ensure_builtin_protocols(conn)
        errors = run_doctor(conn)
        if errors:
            conn.rollback()
            existing = _existing_octopus_schemas(conn)
            if existing:
                return [
                    "Database already contains Octopus schema objects that do not match the current build. "
                    "Reset the database volumes and rerun DB init.",
                    *errors,
                ]
            return errors
        conn.commit()
    except Exception as exc:
        conn.rollback()
        existing = _existing_octopus_schemas(conn)
        if existing:
            errors = run_doctor(conn)
            if errors:
                return [
                    "Database already contains Octopus schema objects that do not match the current build. "
                    "Reset the database volumes and rerun DB init.",
                    *errors,
                ]
        return [f"Applying init.sql: {exc}"]
    return []
