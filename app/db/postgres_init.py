"""Current-schema Postgres initializer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.postgres_doctor import run_doctor

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
    """Initialize an empty database with the current schema.

    Existing databases are only accepted when they already match the current
    schema exactly. Older or partial schema states are rejected; there is no
    migration path.
    """
    existing = _existing_octopus_schemas(conn)
    if existing:
        errors = run_doctor(conn)
        if not errors:
            return []
        return [
            "Database already contains Octopus schema objects that do not match the current build. "
            "Reset the database volumes and rerun DB init.",
            *errors,
        ]

    sql = _INIT_SQL_PATH.read_text(encoding="utf-8")
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        errors = run_doctor(conn)
        if errors:
            conn.rollback()
            return errors
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return [f"Applying init.sql: {exc}"]
    return []
