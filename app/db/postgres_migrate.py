"""Versioned SQL runner for Postgres bootstrap and update (Phase 12)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# SQL files live in repo sql/postgres/; names 0001_*.sql, 0002_*.sql, etc.
_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "sql" / "postgres"
_VERSION_RE = re.compile(r"^(\d+)_(.+)\.sql$")


def _sql_files_sorted() -> list[tuple[int, Path]]:
    """Return (version, path) for each SQL file, sorted by version."""
    if not _SQL_DIR.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for p in _SQL_DIR.iterdir():
        if not p.is_file() or not p.suffix == ".sql":
            continue
        m = _VERSION_RE.match(p.name)
        if m:
            out.append((int(m.group(1)), p))
    out.sort(key=lambda x: x[0])
    return out


# PostgreSQL sqlstate: only these "missing object" cases map to None; others surface.
_MISSING_OBJECT_SQLSTATES = ("42P01", "3F000")  # undefined_table, invalid_schema_name


def _get_max_applied_version(conn: Any) -> int | None:
    """Return max version from schema_migrations, or None only if schema/table is missing.
    Permission errors, connection failures, and other catalog problems are not swallowed."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(version) FROM bot_runtime.schema_migrations"
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None
    except Exception as e:
        sqlstate = getattr(e, "sqlstate", None)
        if sqlstate in _MISSING_OBJECT_SQLSTATES:
            return None
        raise


def run_bootstrap(conn: Any) -> list[str]:
    """Apply all SQL files in order and record versions in the same transaction per file.
    One transaction per migration: SQL + version insert commit together. Stop at first error."""
    errors: list[str] = []
    for version, path in _sql_files_sorted():
        try:
            sql = path.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    """
                    INSERT INTO bot_runtime.schema_migrations (version, applied_at)
                    VALUES (%s, (NOW() AT TIME ZONE 'utc'))
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (version,),
                )
            conn.commit()
        except Exception as e:
            errors.append(f"Applying {path.name}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return errors  # Stop at first failed migration
    return errors


def run_update(conn: Any) -> list[str]:
    """Apply only pending SQL files (version > max applied). One transaction per migration.
    Stop at first error. Does not bootstrap; when schema/table is missing, fail and tell
    operator to run DB bootstrap first."""
    errors: list[str] = []
    max_applied = _get_max_applied_version(conn)
    if max_applied is None:
        return [
            "Schema or schema_migrations table missing. Run DB bootstrap first "
            "(scripts/db_bootstrap.sh or python -m app.db.cli bootstrap)."
        ]
    for version, path in _sql_files_sorted():
        if version <= max_applied:
            continue
        try:
            sql = path.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    """
                    INSERT INTO bot_runtime.schema_migrations (version, applied_at)
                    VALUES (%s, (NOW() AT TIME ZONE 'utc'))
                    """,
                    (version,),
                )
            conn.commit()
        except Exception as e:
            errors.append(f"Applying {path.name}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return errors  # Stop at first failed migration
    return errors


def current_schema_version() -> int:
    """Return the latest schema version number (highest 000N in sql/postgres)."""
    files = _sql_files_sorted()
    return files[-1][0] if files else 0
