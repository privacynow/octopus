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


def _get_max_applied_version(conn: Any) -> int | None:
    """Return max version from schema_migrations, or None if table/schema missing."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(version) FROM bot_runtime.schema_migrations"
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def run_bootstrap(conn: Any) -> list[str]:
    """Apply all SQL files in order and record versions. Returns list of errors (empty if ok)."""
    errors: list[str] = []
    for version, path in _sql_files_sorted():
        try:
            sql = path.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            with conn.cursor() as cur:
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
    return errors


def run_update(conn: Any) -> list[str]:
    """Apply only pending SQL files (version > max applied). Returns list of errors."""
    errors: list[str] = []
    max_applied = _get_max_applied_version(conn)
    if max_applied is None:
        # Schema or table missing: run full bootstrap
        return run_bootstrap(conn)
    for version, path in _sql_files_sorted():
        if version <= max_applied:
            continue
        try:
            sql = path.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            with conn.cursor() as cur:
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
    return errors


def current_schema_version() -> int:
    """Return the latest schema version number (highest 000N in sql/postgres)."""
    files = _sql_files_sorted()
    return files[-1][0] if files else 0
