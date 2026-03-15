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

    # Required partial unique index: exactly UNIQUE ON (chat_id) WHERE (state = 'claimed')
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.oid,
                   i.indisunique,
                   pg_get_expr(i.indpred, i.indrelid) AS pred
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = %s
            JOIN pg_index i ON i.indexrelid = c.oid
            JOIN pg_class t ON t.oid = i.indrelid AND t.relname = 'work_items'
            WHERE c.relkind = 'i' AND c.relname = %s
            """,
            (_REQUIRED_SCHEMA, _REQUIRED_INDEX),
        )
        row = cur.fetchone()
    if row is None:
        errors.append(
            f"Index bot_runtime.work_items.{_REQUIRED_INDEX} missing. Run DB bootstrap."
        )
        return errors
    index_oid, is_unique, pred = row[0], row[1], (row[2] or "")
    if not is_unique:
        errors.append(
            f"Index bot_runtime.work_items.{_REQUIRED_INDEX} must be UNIQUE. Run DB bootstrap."
        )
    # Exact column list: must be exactly (chat_id), no extra columns
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT array_agg(a.attname) AS cols
            FROM pg_index i, pg_attribute a
            WHERE i.indexrelid = %s AND a.attrelid = i.indrelid
              AND a.attnum = ANY(i.indkey) AND a.attnum > 0 AND NOT a.attisdropped
            """,
            (index_oid,),
        )
        col_row = cur.fetchone()
    cols = sorted(col_row[0]) if col_row and col_row[0] else []
    if cols != ["chat_id"]:
        errors.append(
            f"Index bot_runtime.work_items.{_REQUIRED_INDEX} must be on (chat_id) only, got {cols}. Run DB bootstrap."
        )
    # Exact predicate: WHERE (state = 'claimed') only (Postgres may show (state = 'claimed'::text))
    pred_normalized = " ".join((pred or "").split()).strip()
    pred_canonical = pred_normalized.replace("::text", "").replace("::character varying", "")
    if pred_canonical != "(state = 'claimed')":
        errors.append(
            f"Index bot_runtime.work_items.{_REQUIRED_INDEX} must be partial WHERE (state = 'claimed') only, got {pred!r}. Run DB bootstrap."
        )

    return errors
