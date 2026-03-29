"""SQLite transport implementation with conn-based API (same shape as work_queue_postgres_impl)."""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from octopus_sdk.work_queue import (
    QueueSnapshot,
    UsageRecord,
    UserAccessRecord,
    WorkItemRecord,
    WorkerHeartbeat,
)
from octopus_sdk.work_queue import (
    ApplyResult,
    CancelRequestResult,
    DiscardResult,
    ReclaimBlocked,
    coerce_usage_records,
    coerce_user_access_records,
    coerce_work_item_record,
    coerce_work_item_records,
    _validate_work_item_row,
)
from octopus_sdk.workflows.recovery_machine import (
    TRANSPORT_STATES,
    TransportWorkflowModel,
    run_transport_event,
)
from octopus_sdk.work_queue import TransportDisposition, TransportStateCorruption

log = logging.getLogger(__name__)


class _DuplicateUpdate(Exception):
    """Signals duplicate event_id in record_and_admit_message (rollback and return duplicate, None)."""


_SCHEMA_VERSION = 8

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS updates (
    event_id          TEXT PRIMARY KEY,
    conversation_key  TEXT NOT NULL,
    actor_key         TEXT NOT NULL,
    kind              TEXT NOT NULL,
    payload           TEXT NOT NULL DEFAULT '{}',
    received_at       TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'received'
);
CREATE INDEX IF NOT EXISTS idx_updates_conv ON updates (conversation_key, received_at);

CREATE TABLE IF NOT EXISTS work_items (
    id                TEXT PRIMARY KEY,
    conversation_key  TEXT NOT NULL,
    event_id          TEXT NOT NULL UNIQUE REFERENCES updates(event_id),
    state             TEXT NOT NULL DEFAULT 'queued',
    worker_id         TEXT,
    claimed_at        TEXT,
    completed_at      TEXT,
    error             TEXT,
    created_at        TEXT NOT NULL,
    dispatch_mode     TEXT NOT NULL DEFAULT 'fresh',
    cancel_requested_at TEXT,
    cancel_requested_by TEXT NOT NULL DEFAULT '',
    cancel_request_event_id TEXT NOT NULL DEFAULT '',
    CHECK (state IN ('queued','claimed','pending_recovery','done','failed')),
    CHECK (state != 'claimed' OR worker_id IS NOT NULL),
    CHECK (state != 'claimed' OR claimed_at IS NOT NULL),
    CHECK (dispatch_mode IN ('fresh', 'recovery'))
);
CREATE INDEX IF NOT EXISTS idx_work_items_state ON work_items (state, conversation_key);
CREATE INDEX IF NOT EXISTS idx_work_items_conv  ON work_items (conversation_key, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_claimed_per_conv ON work_items(conversation_key) WHERE state = 'claimed';

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id                TEXT PRIMARY KEY,
    process_role             TEXT NOT NULL,
    started_at               TEXT NOT NULL,
    last_seen_at             TEXT NOT NULL,
    current_item_id          TEXT NOT NULL DEFAULT '',
    current_conversation_key TEXT NOT NULL DEFAULT '',
    current_kind             TEXT NOT NULL DEFAULT '',
    items_processed          INTEGER NOT NULL DEFAULT 0,
    stale_recoveries_seen    INTEGER NOT NULL DEFAULT 0,
    last_error               TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_seen ON worker_heartbeats (last_seen_at);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_key TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_log_conv ON usage_log(conversation_key);
CREATE INDEX IF NOT EXISTS idx_usage_log_recorded_at ON usage_log(recorded_at);

CREATE TABLE IF NOT EXISTS user_access (
    actor_key TEXT PRIMARY KEY,
    access TEXT NOT NULL CHECK(access IN ('allowed', 'blocked')),
    reason TEXT NOT NULL DEFAULT '',
    granted_by TEXT NOT NULL DEFAULT '',
    granted_at REAL NOT NULL
);
"""

_UNSUPPORTED_SCHEMA_MSG = "Unsupported transport.db schema/layout for this build"
_EXPECTED_TABLES = ("updates", "work_items", "worker_heartbeats", "meta", "usage_log", "user_access")
_EXPECTED_COLUMNS: dict[str, set[str]] = {
    "updates": {"event_id", "conversation_key", "actor_key", "kind", "payload", "received_at", "state"},
    "work_items": {
        "id", "conversation_key", "event_id", "state", "worker_id", "claimed_at", "completed_at",
        "error", "created_at", "dispatch_mode", "cancel_requested_at", "cancel_requested_by",
        "cancel_request_event_id",
    },
    "meta": {"key", "value"},
    "worker_heartbeats": {
        "worker_id",
        "process_role",
        "started_at",
        "last_seen_at",
        "current_item_id",
        "current_conversation_key",
        "current_kind",
        "items_processed",
        "stale_recoveries_seen",
        "last_error",
    },
    "usage_log": {"id", "conversation_key", "work_item_id", "provider", "prompt_tokens", "completion_tokens", "cost_usd", "recorded_at"},
    "user_access": {"actor_key", "access", "reason", "granted_by", "granted_at"},
}
_REQUIRED_INDEX = "idx_one_claimed_per_conv"

_MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = ()


def _execute_sql_script(conn: sqlite3.Connection, script: str) -> None:
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                conn.execute(statement)
            buffer = ""
    statement = buffer.strip()
    if statement:
        conn.execute(statement)


def _run_migration_step(
    conn: sqlite3.Connection,
    version: int,
    migration: Callable[[sqlite3.Connection], None],
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        migration(conn)
        _set_schema_version(conn, version)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _create_new_transport_db(conn: sqlite3.Connection) -> None:
    """Initialize a brand-new transport DB. Call only when the file has no tables."""
    conn.executescript(_CREATE_SQL)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.commit()


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Migrate transport DB schema version 2 to 3: add dispatch_mode to work_items."""
    try:
        conn.execute(
            "ALTER TABLE work_items ADD COLUMN dispatch_mode TEXT NOT NULL DEFAULT 'fresh'"
        )
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Migrate transport DB schema version 3 to 4: add usage_log table."""
    _execute_sql_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            work_item_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            recorded_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_usage_log_chat ON usage_log(chat_id);
        CREATE INDEX IF NOT EXISTS idx_usage_log_recorded_at ON usage_log(recorded_at);
        """,
    )


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """Migrate transport DB schema version 4 to 5: add user_access table."""
    _execute_sql_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS user_access (
            user_id INTEGER PRIMARY KEY,
            access TEXT NOT NULL CHECK(access IN ('allowed', 'blocked')),
            reason TEXT NOT NULL DEFAULT '',
            granted_by INTEGER NOT NULL DEFAULT 0,
            granted_at REAL NOT NULL
        );
        """,
    )


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """Migrate transport DB schema version 5 to 6: channel-neutral text identities."""
    _execute_sql_script(
        conn,
        """
        CREATE TABLE updates_v2 (
            event_id          TEXT PRIMARY KEY,
            conversation_key  TEXT NOT NULL,
            actor_key         TEXT NOT NULL,
            kind              TEXT NOT NULL,
            payload           TEXT NOT NULL DEFAULT '{}',
            received_at       TEXT NOT NULL,
            state             TEXT NOT NULL DEFAULT 'received'
        );
        INSERT INTO updates_v2 (event_id, conversation_key, actor_key, kind, payload, received_at, state)
            SELECT
                'tg:' || CAST(update_id AS TEXT),
                'tg:' || CAST(chat_id AS TEXT),
                'tg:' || CAST(user_id AS TEXT),
                kind, payload, received_at, state
            FROM updates;
        DROP TABLE updates;
        ALTER TABLE updates_v2 RENAME TO updates;
        CREATE INDEX idx_updates_conv ON updates (conversation_key, received_at);

        CREATE TABLE work_items_v2 (
            id                TEXT PRIMARY KEY,
            conversation_key  TEXT NOT NULL,
            event_id          TEXT NOT NULL UNIQUE REFERENCES updates(event_id),
            state             TEXT NOT NULL DEFAULT 'queued',
            worker_id         TEXT,
            claimed_at        TEXT,
            completed_at      TEXT,
            error             TEXT,
            created_at        TEXT NOT NULL,
            dispatch_mode     TEXT NOT NULL DEFAULT 'fresh',
            CHECK (state IN ('queued','claimed','pending_recovery','done','failed')),
            CHECK (state != 'claimed' OR worker_id IS NOT NULL),
            CHECK (state != 'claimed' OR claimed_at IS NOT NULL),
            CHECK (dispatch_mode IN ('fresh', 'recovery'))
        );
        INSERT INTO work_items_v2 (
            id, conversation_key, event_id, state, worker_id,
            claimed_at, completed_at, error, created_at, dispatch_mode
        )
            SELECT
                id,
                'tg:' || CAST(chat_id AS TEXT),
                'tg:' || CAST(update_id AS TEXT),
                state, worker_id, claimed_at, completed_at, error, created_at, dispatch_mode
            FROM work_items;
        DROP TABLE work_items;
        ALTER TABLE work_items_v2 RENAME TO work_items;
        CREATE INDEX idx_work_items_state ON work_items (state, conversation_key);
        CREATE INDEX idx_work_items_conv ON work_items (conversation_key, state);
        CREATE UNIQUE INDEX idx_one_claimed_per_conv ON work_items(conversation_key) WHERE state = 'claimed';

        CREATE TABLE usage_log_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_key TEXT NOT NULL,
            work_item_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            recorded_at REAL NOT NULL
        );
        INSERT INTO usage_log_v2 (
            id, conversation_key, work_item_id, provider, prompt_tokens,
            completion_tokens, cost_usd, recorded_at
        )
            SELECT
                id,
                'tg:' || CAST(chat_id AS TEXT),
                work_item_id, provider, prompt_tokens, completion_tokens, cost_usd, recorded_at
            FROM usage_log;
        DROP TABLE usage_log;
        ALTER TABLE usage_log_v2 RENAME TO usage_log;
        CREATE INDEX idx_usage_log_conv ON usage_log(conversation_key);
        CREATE INDEX idx_usage_log_recorded_at ON usage_log(recorded_at);

        CREATE TABLE user_access_v2 (
            actor_key TEXT PRIMARY KEY,
            access TEXT NOT NULL CHECK(access IN ('allowed', 'blocked')),
            reason TEXT NOT NULL DEFAULT '',
            granted_by TEXT NOT NULL DEFAULT '',
            granted_at REAL NOT NULL
        );
        INSERT INTO user_access_v2 (actor_key, access, reason, granted_by, granted_at)
            SELECT
                'tg:' || CAST(user_id AS TEXT),
                access,
                reason,
                CASE
                    WHEN granted_by = 0 THEN ''
                    ELSE 'tg:' || CAST(granted_by AS TEXT)
                END,
                granted_at
            FROM user_access;
        DROP TABLE user_access;
        ALTER TABLE user_access_v2 RENAME TO user_access;
        """,
    )


def _migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """Migrate transport DB schema version 6 to 7: durable cancel metadata."""
    _execute_sql_script(
        conn,
        """
        ALTER TABLE work_items ADD COLUMN cancel_requested_at TEXT;
        ALTER TABLE work_items ADD COLUMN cancel_requested_by TEXT NOT NULL DEFAULT '';
        ALTER TABLE work_items ADD COLUMN cancel_request_event_id TEXT NOT NULL DEFAULT '';
        """,
    )


def _migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """Migrate transport DB schema version 7 to 8: durable worker heartbeats."""
    _execute_sql_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_id                TEXT PRIMARY KEY,
            process_role             TEXT NOT NULL,
            started_at               TEXT NOT NULL,
            last_seen_at             TEXT NOT NULL,
            current_item_id          TEXT NOT NULL DEFAULT '',
            current_conversation_key TEXT NOT NULL DEFAULT '',
            current_kind             TEXT NOT NULL DEFAULT '',
            items_processed          INTEGER NOT NULL DEFAULT 0,
            stale_recoveries_seen    INTEGER NOT NULL DEFAULT 0,
            last_error               TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_seen ON worker_heartbeats (last_seen_at);
        """,
    )


_MIGRATIONS = (
    (3, _migrate_v2_to_v3),
    (4, _migrate_v3_to_v4),
    (5, _migrate_v4_to_v5),
    (6, _migrate_v5_to_v6),
    (7, _migrate_v6_to_v7),
    (8, _migrate_v7_to_v8),
)


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(version),),
    )


def _validate_existing_transport_db(conn: sqlite3.Connection) -> None:
    """Verify an existing transport DB has the supported schema/layout. Does not mutate."""
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    if any(table not in tables for table in _EXPECTED_TABLES):
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    for table in _EXPECTED_TABLES:
        cursor = conn.execute("PRAGMA table_info(" + table + ")")
        infos = cursor.fetchall()
        cols = set()
        for r in infos:
            if hasattr(r, "keys") and "name" in r.keys():
                cols.add(r["name"])
            else:
                cols.add(r[1])
        if _EXPECTED_COLUMNS[table] - cols:
            raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    index_list = conn.execute("PRAGMA index_list(work_items)").fetchall()
    idx_row = None
    for r in index_list:
        name = r["name"] if hasattr(r, "keys") and "name" in r.keys() else r[1]
        if name == _REQUIRED_INDEX:
            idx_row = r
            break
    if idx_row is None:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    unique = idx_row["unique"] if hasattr(idx_row, "keys") and "unique" in idx_row.keys() else idx_row[2]
    if unique != 1:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    partial = idx_row["partial"] if hasattr(idx_row, "keys") and "partial" in idx_row.keys() else (idx_row[4] if len(idx_row) > 4 else 0)
    if partial != 1:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    info_rows = conn.execute("PRAGMA index_info(" + _REQUIRED_INDEX + ")").fetchall()
    index_cols = []
    for r in info_rows:
        col = r["name"] if hasattr(r, "keys") and "name" in r.keys() else r[2]
        index_cols.append(col)
    if index_cols != ["conversation_key"]:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
        (_REQUIRED_INDEX,),
    ).fetchone()
    if sql_row is None:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    index_sql = (sql_row["sql"] if hasattr(sql_row, "keys") and "sql" in sql_row.keys() else sql_row[0]) or ""
    where_i = index_sql.lower().find(" where ")
    if where_i == -1:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    predicate = index_sql[where_i + 7 :].strip()
    normalized = re.sub(r"\s+", " ", predicate.lower()).strip()
    if not re.fullmatch(r"state\s*=\s*['\"]claimed['\"]", normalized):
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    try:
        stored = int(row[0])
    except (TypeError, ValueError):
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    if stored != _SCHEMA_VERSION:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run supported transport DB migrations in order, then validate schema/layout."""
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    try:
        stored = int(row[0])
    except (TypeError, ValueError):
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    if stored < 2 or stored > _SCHEMA_VERSION:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    for version, fn in _MIGRATIONS:
        if stored < version:
            _run_migration_step(conn, version, fn)
            stored = version
    _validate_existing_transport_db(conn)


def _ensure_schema_version(conn: sqlite3.Connection) -> None:
    """Backward-compatible alias for connection initialization migration flow."""
    _run_migrations(conn)


@contextmanager
def _write_tx(conn: sqlite3.Connection, immediate: bool = True):
    """Single transaction wrapper for all mutating repository entry points."""
    if conn.in_transaction:
        raise RuntimeError("nested transport transaction")
    if immediate:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# ---------------------------------------------------------------------------
# Repository primitives (private)
# ---------------------------------------------------------------------------

def _load_work_item_by_id(
    conn: sqlite3.Connection, item_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if row is None:
        return None
    row = dict(row)
    _validate_work_item_row(row, item_id)
    return row


def _load_work_item_by_conversation_event(
    conn: sqlite3.Connection, conversation_key: str, event_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT w.*, u.kind, u.payload FROM work_items w "
        "JOIN updates u ON w.event_id = u.event_id "
        "WHERE w.conversation_key = ? AND w.event_id = ?",
        (conversation_key, event_id),
    ).fetchone()
    if row is None:
        return None
    row = dict(row)
    _validate_work_item_row(row)
    return row


def _assert_no_invalid_rows_for_conversation(
    conn: sqlite3.Connection, conversation_key: str
) -> None:
    rows = conn.execute(
        "SELECT id, state, worker_id, claimed_at, dispatch_mode FROM work_items WHERE conversation_key = ?",
        (conversation_key,),
    ).fetchall()
    claimed = 0
    for row in rows:
        r = dict(row)
        _validate_work_item_row(r, r["id"])
        if r["state"] == "claimed":
            claimed += 1
    if claimed > 1:
        raise TransportStateCorruption(
            f"conversation {conversation_key} has {claimed} claimed work items (at most one allowed)"
        )


def _claim_queued_item(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    worker_id: str,
    has_other_claimed_for_chat: bool,
    event_name: str,
) -> dict[str, Any] | None:
    row = _load_work_item_by_id(conn, item_id)
    if row is None or row["state"] != "queued":
        return None
    model = TransportWorkflowModel(
        state="queued",
        has_other_claimed_for_chat=has_other_claimed_for_chat,
    )
    if event_name == "claim_inline":
        result = run_transport_event(model, "claim_inline", requesting_worker_id=worker_id)
    else:
        result = run_transport_event(model, "claim_worker")
    if not result.allowed:
        if result.disposition == TransportDisposition.other_claimed_for_chat:
            return None
        raise TransportStateCorruption(
            f"_claim_queued_item: workflow rejected for item {item_id}: "
            f"{result.disposition} — {result.reason}"
        )
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE work_items SET state = ?, worker_id = ?, claimed_at = ? "
        "WHERE id = ? AND state = 'queued'",
        (result.new_state, worker_id, now, item_id),
    )
    if cursor.rowcount > 0:
        item = conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            return None
        out = dict(item)
        _validate_work_item_row(out, item_id)
        return out
    re_read = conn.execute(
        "SELECT state, worker_id, claimed_at, dispatch_mode FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if re_read is None:
        return None
    _validate_work_item_row(dict(re_read), item_id)
    if re_read["state"] != "queued":
        return None
    log.error(
        "_claim_queued_item: invariant violation item %s (still queued after UPDATE 0 rows)",
        item_id,
    )
    raise TransportStateCorruption(
        f"claim update matched 0 rows but item {item_id} still queued"
    )


def _apply_transport_event(
    conn: sqlite3.Connection,
    item_id: str,
    event_name: str,
    expected_source_state: str,
    build_model: Callable[[dict], TransportWorkflowModel],
    update_extras: str,
    update_extra_args: tuple,
    **event_kwargs: Any,
) -> ApplyResult:
    row = _load_work_item_by_id(conn, item_id)
    if row is None:
        return ApplyResult.already_handled
    if row["state"] != expected_source_state:
        return ApplyResult.already_handled
    model = build_model(row)
    result = run_transport_event(model, event_name, **event_kwargs)
    if not result.allowed:
        raise TransportStateCorruption(
            f"_apply_transport_event: workflow rejected for item {item_id} event {event_name!r}: "
            f"{result.disposition} — {result.reason}"
        )
    now = datetime.now(timezone.utc).isoformat()
    if update_extras:
        placeholders = (result.new_state,) + update_extra_args + (item_id, expected_source_state)
        cursor = conn.execute(
            "UPDATE work_items SET state = ?, " + update_extras + " WHERE id = ? AND state = ?",
            placeholders,
        )
    else:
        cursor = conn.execute(
            "UPDATE work_items SET state = ? WHERE id = ? AND state = ?",
            (result.new_state, item_id, expected_source_state),
        )
    if cursor.rowcount > 0:
        return ApplyResult.success
    re_read = conn.execute(
        "SELECT state, worker_id, claimed_at, dispatch_mode FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if re_read is None:
        return ApplyResult.already_handled
    _validate_work_item_row(dict(re_read), item_id)
    if re_read["state"] != expected_source_state:
        return ApplyResult.already_handled
    log.error(
        "_apply_transport_event: invariant violation item %s (still %s)",
        item_id, expected_source_state,
    )
    return ApplyResult.corruption


def _apply_claim_event(
    conn: sqlite3.Connection,
    item_id: str,
    event_name: str,
    expected_source_state: str,
    worker_id: str,
    build_model: Callable[[dict], TransportWorkflowModel],
    **event_kwargs: Any,
) -> dict[str, Any] | None:
    row = _load_work_item_by_id(conn, item_id)
    if row is None or row["state"] != expected_source_state:
        return None
    model = build_model(row)
    result = run_transport_event(model, event_name, **event_kwargs)
    if not result.allowed:
        if result.disposition == TransportDisposition.other_claimed_for_chat:
            return None
        if result.disposition == TransportDisposition.blocked_replay:
            raise ReclaimBlocked(item_id)
        raise TransportStateCorruption(
            f"_apply_claim_event: workflow rejected for item {item_id} event {event_name!r}: "
            f"{result.disposition} — {result.reason}"
        )
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE work_items SET state = ?, worker_id = ?, claimed_at = ?, completed_at = NULL "
        "WHERE id = ? AND state = ?",
        (result.new_state, worker_id, now, item_id, expected_source_state),
    )
    if cursor.rowcount > 0:
        out = conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
        if out is None:
            return None
        r = dict(out)
        _validate_work_item_row(r, item_id)
        return r
    re_read = conn.execute(
        "SELECT state, worker_id, claimed_at, dispatch_mode FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if re_read is None:
        return None
    _validate_work_item_row(dict(re_read), item_id)
    if re_read["state"] != expected_source_state:
        return None
    log.error(
        "_apply_claim_event: invariant violation item %s (still %s)",
        item_id, expected_source_state,
    )
    raise TransportStateCorruption(
        f"claim update matched 0 rows but item {item_id} still in {re_read['state']!r}"
    )


def _insert_initial_work_item(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    conversation_key: str,
    event_id: str,
    worker_id: str | None,
    created_at: str,
) -> str:
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    has_other_claimed = conn.execute(
        "SELECT 1 FROM work_items WHERE conversation_key = ? AND state = 'claimed' LIMIT 1",
        (conversation_key,),
    ).fetchone()
    if bool(worker_id) and not has_other_claimed:
        model = TransportWorkflowModel(
            state="queued", has_other_claimed_for_chat=False
        )
        result = run_transport_event(
            model, "claim_inline", requesting_worker_id=worker_id
        )
        if result.allowed:
            conn.execute(
                "INSERT INTO work_items "
                "(id, conversation_key, event_id, state, worker_id, claimed_at, created_at, dispatch_mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'fresh')",
                (item_id, conversation_key, event_id, result.new_state, worker_id, created_at, created_at),
            )
            return item_id
        raise TransportStateCorruption(
            f"_insert_initial_work_item: claim_inline rejected for item {item_id}: "
            f"{result.disposition} — {result.reason}"
        )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, created_at, dispatch_mode) "
        "VALUES (?, ?, ?, 'queued', ?, 'fresh')",
        (item_id, conversation_key, event_id, created_at),
    )
    return item_id


# ---------------------------------------------------------------------------
# Public API (conn as first arg)
# ---------------------------------------------------------------------------

def record_and_enqueue(
    conn: sqlite3.Connection,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
    *,
    worker_id: str | None = None,
) -> tuple[bool, str | None]:
    now = datetime.now(timezone.utc).isoformat()
    item_id = uuid.uuid4().hex
    try:
        with _write_tx(conn):
            conn.execute(
                "INSERT INTO updates (event_id, conversation_key, actor_key, kind, payload, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, conversation_key, actor_key, kind, payload, now),
            )
            _insert_initial_work_item(
                conn,
                item_id=item_id,
                conversation_key=conversation_key,
                event_id=event_id,
                worker_id=worker_id,
                created_at=now,
            )
        return True, item_id
    except sqlite3.IntegrityError as exc:
        if "updates.event_id" in str(exc):
            return False, None
        raise


def record_and_admit_message(
    conn: sqlite3.Connection,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
) -> tuple[str, str | None]:
    """Record update and durably admit fresh work. Returns (status, item_id).

    status: 'duplicate' | 'admitted' | 'queued'. item_id set when admitted or queued.
    """
    now = datetime.now(timezone.utc).isoformat()
    item_id = uuid.uuid4().hex
    try:
        with _write_tx(conn):
            conn.execute(
                "INSERT INTO updates (event_id, conversation_key, actor_key, kind, payload, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, conversation_key, actor_key, kind, payload, now),
            )
            had_prior_fresh = has_fresh_queued_or_claimed(conn, conversation_key)
            conn.execute(
                "INSERT INTO work_items (id, conversation_key, event_id, state, created_at, dispatch_mode) "
                "VALUES (?, ?, ?, 'queued', ?, 'fresh')",
                (item_id, conversation_key, event_id, now),
            )
            return ("queued" if had_prior_fresh else "admitted", item_id)
    except sqlite3.IntegrityError as exc:
        if "updates.event_id" in str(exc) or "UNIQUE" in str(exc):
            raise _DuplicateUpdate from exc
        raise


def record_update(
    conn: sqlite3.Connection,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _write_tx(conn):
            conn.execute(
                "INSERT INTO updates (event_id, conversation_key, actor_key, kind, payload, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, conversation_key, actor_key, kind, payload, now),
            )
        return True
    except sqlite3.IntegrityError as exc:
        if "updates.event_id" in str(exc):
            return False
        raise


def enqueue_work_item(
    conn: sqlite3.Connection,
    conversation_key: str,
    event_id: str,
    *,
    worker_id: str | None = None,
) -> str:
    item_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        _insert_initial_work_item(
            conn,
            item_id=item_id,
            conversation_key=conversation_key,
            event_id=event_id,
            worker_id=worker_id,
            created_at=now,
        )
    return item_id


def update_payload(conn: sqlite3.Connection, event_id: str, payload: str) -> None:
    with _write_tx(conn):
        conn.execute(
            "UPDATE updates SET payload = ? WHERE event_id = ?",
            (payload, event_id),
        )


def claim_for_update(
    conn: sqlite3.Connection, conversation_key: str, event_id: str, worker_id: str
) -> WorkItemRecord | None:
    with _write_tx(conn):
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        row = _load_work_item_by_conversation_event(conn, conversation_key, event_id)
        if row is None:
            return None
        if row["state"] == "claimed" and row.get("worker_id") == worker_id:
            return WorkItemRecord.from_mapping(row)
        if row["state"] != "queued":
            return None
        has_other_claimed = conn.execute(
            "SELECT 1 FROM work_items WHERE conversation_key = ? AND state = 'claimed' LIMIT 1",
            (conversation_key,),
        ).fetchone()
        out = _claim_queued_item(
            conn,
            item_id=row["id"],
            worker_id=worker_id,
            has_other_claimed_for_chat=bool(has_other_claimed),
            event_name="claim_inline",
        )
        if out is None:
            return None
        u = conn.execute(
            "SELECT kind, payload FROM updates WHERE event_id = ?",
            (out["event_id"],),
        ).fetchone()
        if u:
            u = dict(u)
            out["kind"] = u["kind"]
            out["payload"] = u["payload"]
        return None if out is None else WorkItemRecord.from_mapping(out)


def claim_next(
    conn: sqlite3.Connection, conversation_key: str, worker_id: str
) -> WorkItemRecord | None:
    with _write_tx(conn):
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        row = conn.execute(
            "SELECT id FROM work_items "
            "WHERE conversation_key = ? AND state = 'queued' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM work_items WHERE conversation_key = ? AND state = 'claimed'"
            ") "
            "ORDER BY created_at LIMIT 1",
            (conversation_key, conversation_key),
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        out = _claim_queued_item(
            conn,
            item_id=row["id"],
            worker_id=worker_id,
            has_other_claimed_for_chat=False,
            event_name="claim_worker",
        )
        return None if out is None else WorkItemRecord.from_mapping(out)


def claim_next_any(conn: sqlite3.Connection, worker_id: str) -> WorkItemRecord | None:
    with _write_tx(conn):
        row = conn.execute(
            "SELECT id, conversation_key FROM work_items "
            "WHERE state = 'queued' "
            "AND conversation_key NOT IN ("
            "  SELECT DISTINCT conversation_key FROM work_items WHERE state = 'claimed'"
            ") "
            "ORDER BY created_at LIMIT 1",
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        _assert_no_invalid_rows_for_conversation(conn, row["conversation_key"])
        out = _claim_queued_item(
            conn,
            item_id=row["id"],
            worker_id=worker_id,
            has_other_claimed_for_chat=False,
            event_name="claim_worker",
        )
        if out is None:
            return None
        item = conn.execute(
            "SELECT w.*, u.kind, u.payload FROM work_items w "
            "JOIN updates u ON w.event_id = u.event_id WHERE w.id = ?",
            (out["id"],),
        ).fetchone()
        if item is None:
            return None
        out = dict(item)
        _validate_work_item_row(out, out["id"])
        return out


def complete_work_item(conn: sqlite3.Connection, item_id: str) -> None:
    with _write_tx(conn):
        row = _load_work_item_by_id(conn, item_id)
        if row is None:
            return
        loaded_state = row["state"]
        if loaded_state not in ("queued", "claimed"):
            return
        model = TransportWorkflowModel(state=loaded_state)
        result = run_transport_event(model, "complete")
        if not result.allowed:
            raise TransportStateCorruption(
                f"complete_work_item: workflow rejected for item {item_id}: "
                f"{result.disposition} — {result.reason}"
            )
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "UPDATE work_items SET state = ?, completed_at = ?, error = ? "
            "WHERE id = ? AND state = ?",
            (result.new_state, now, None, item_id, loaded_state),
        )
        if cursor.rowcount > 0:
            return
        re_read = conn.execute(
            "SELECT state, worker_id, claimed_at, dispatch_mode FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        if re_read is None:
            return
        _validate_work_item_row(dict(re_read), item_id)
        if re_read["state"] == loaded_state:
            log.error(
                "complete_work_item: invariant violation item %s (still %s)",
                item_id, re_read["state"],
            )
            raise TransportStateCorruption(
                f"update matched 0 rows but item {item_id} still in {re_read['state']!r}"
            )


def fail_work_item(conn: sqlite3.Connection, item_id: str, error: str) -> None:
    with _write_tx(conn):
        row = _load_work_item_by_id(conn, item_id)
        if row is None:
            return
        loaded_state = row["state"]
        if loaded_state not in ("queued", "claimed"):
            return
        model = TransportWorkflowModel(state=loaded_state)
        result = run_transport_event(model, "fail")
        if not result.allowed:
            raise TransportStateCorruption(
                f"fail_work_item: workflow rejected for item {item_id}: "
                f"{result.disposition} — {result.reason}"
            )
        now = datetime.now(timezone.utc).isoformat()
        err = (error or "")[:500]
        cursor = conn.execute(
            "UPDATE work_items SET state = ?, completed_at = ?, error = ? "
            "WHERE id = ? AND state = ?",
            (result.new_state, now, err, item_id, loaded_state),
        )
        if cursor.rowcount > 0:
            return
        re_read = conn.execute(
            "SELECT state, worker_id, claimed_at, dispatch_mode FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        if re_read is None:
            return
        _validate_work_item_row(dict(re_read), item_id)
        if re_read["state"] == loaded_state:
            log.error(
                "fail_work_item: invariant violation item %s (still %s)",
                item_id, re_read["state"],
            )
            raise TransportStateCorruption(
                f"update matched 0 rows but item {item_id} still in {re_read['state']!r}"
            )


def has_claimed_for_chat(conn: sqlite3.Connection, conversation_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE conversation_key = ? AND state = 'claimed' LIMIT 1",
        (conversation_key,),
    ).fetchone()
    return row is not None


def has_queued_or_claimed(conn: sqlite3.Connection, conversation_key: str) -> bool:
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE conversation_key = ? AND state IN ('queued', 'claimed') LIMIT 1",
        (conversation_key,),
    ).fetchone()
    return row is not None


def has_fresh_queued_or_claimed(conn: sqlite3.Connection, conversation_key: str) -> bool:
    """True if this conversation has any work item in queued or claimed state with dispatch_mode='fresh'."""
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE conversation_key = ? AND state IN ('queued', 'claimed') "
        "AND dispatch_mode = 'fresh' LIMIT 1",
        (conversation_key,),
    ).fetchone()
    return row is not None


def cancel_queued_fresh_for_chat(conn: sqlite3.Connection, conversation_key: str) -> bool:
    """If this conversation has a queued fresh item, mark it failed with error='cancelled'. Returns True if one was cancelled."""
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        row = conn.execute(
            "SELECT id FROM work_items WHERE conversation_key = ? AND state = 'queued' AND dispatch_mode = 'fresh' "
            "ORDER BY created_at ASC LIMIT 1",
            (conversation_key,),
        ).fetchone()
        if row is None:
            return False
        item_id = row["id"]
        cur = conn.execute(
            "UPDATE work_items SET state = 'failed', completed_at = ?, error = 'cancelled' WHERE id = ? AND state = 'queued'",
            (now, item_id),
        )
        return cur.rowcount > 0


def request_cancel(
    conn: sqlite3.Connection,
    conversation_key: str,
    actor_key: str,
    *,
    cancel_request_event_id: str = "",
) -> CancelRequestResult:
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        claimed_sql = (
            "SELECT id, cancel_requested_at FROM work_items "
            "WHERE conversation_key = ? AND state = 'claimed' AND dispatch_mode = 'fresh' "
        )
        claimed_params: tuple[object, ...]
        if cancel_request_event_id:
            claimed_sql += "AND event_id != ? "
            claimed_params = (conversation_key, cancel_request_event_id)
        else:
            claimed_params = (conversation_key,)
        claimed_sql += "ORDER BY created_at ASC LIMIT 1"
        claimed = conn.execute(
            claimed_sql,
            claimed_params,
        ).fetchone()
        if claimed is not None:
            item_id = claimed["id"]
            conn.execute(
                "UPDATE work_items SET cancel_requested_at = COALESCE(cancel_requested_at, ?), "
                "cancel_requested_by = ?, cancel_request_event_id = ? "
                "WHERE id = ? AND state = 'claimed'",
                (now, actor_key, cancel_request_event_id, item_id),
            )
            return CancelRequestResult.claimed_cancel_requested

        queued_sql = (
            "SELECT id FROM work_items WHERE conversation_key = ? AND state = 'queued' "
            "AND dispatch_mode = 'fresh' "
        )
        queued_params: tuple[object, ...]
        if cancel_request_event_id:
            queued_sql += "AND event_id != ? "
            queued_params = (conversation_key, cancel_request_event_id)
        else:
            queued_params = (conversation_key,)
        queued_sql += "ORDER BY created_at ASC LIMIT 1"
        queued = conn.execute(queued_sql, queued_params).fetchone()
        if queued is not None:
            cur = conn.execute(
                "UPDATE work_items SET state = 'failed', completed_at = ?, error = 'cancelled' "
                "WHERE id = ? AND state = 'queued'",
                (now, queued["id"]),
            )
            if cur.rowcount > 0:
                return CancelRequestResult.queued_cancelled

        return CancelRequestResult.nothing_to_cancel


def is_cancel_requested(conn: sqlite3.Connection, item_id: str) -> bool:
    row = conn.execute(
        "SELECT cancel_requested_at FROM work_items WHERE id = ?",
        (item_id,),
    ).fetchone()
    return bool(row and row["cancel_requested_at"])


def get_work_items_for_chat(conn: sqlite3.Connection, conversation_key: str) -> list[WorkItemRecord]:
    """Return work items for a conversation with id, event_id, state, error, dispatch_mode, kind. Read-only."""
    rows = conn.execute(
        "SELECT w.id, w.event_id, w.state, w.error, w.dispatch_mode, u.kind "
        "FROM work_items w JOIN updates u ON w.event_id = u.event_id "
        "WHERE w.conversation_key = ? ORDER BY w.created_at ASC",
        (conversation_key,),
    ).fetchall()
    return [WorkItemRecord.from_mapping(dict(r)) for r in rows]


def list_incomplete_work_items(conn: sqlite3.Connection) -> list[WorkItemRecord]:
    """Return queued/claimed/recovery items that survive process restarts."""
    rows = conn.execute(
        "SELECT w.*, u.kind, u.payload "
        "FROM work_items w JOIN updates u ON w.event_id = u.event_id "
        "WHERE w.state IN ('queued', 'claimed', 'pending_recovery') "
        "ORDER BY w.created_at ASC",
    ).fetchall()
    return [WorkItemRecord.from_mapping(dict(r)) for r in rows]


def get_queue_snapshot(conn: sqlite3.Connection) -> QueueSnapshot:
    """Return backend-neutral queue counts and oldest timestamps."""
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN state = 'queued' AND dispatch_mode = 'fresh' THEN 1 ELSE 0 END), 0) AS fresh_queued_count,
            COALESCE(SUM(CASE WHEN state = 'queued' AND dispatch_mode = 'recovery' THEN 1 ELSE 0 END), 0) AS recovery_queued_count,
            COALESCE(SUM(CASE WHEN state = 'claimed' THEN 1 ELSE 0 END), 0) AS claimed_count,
            COALESCE(SUM(CASE WHEN state = 'pending_recovery' THEN 1 ELSE 0 END), 0) AS pending_recovery_count,
            COALESCE(SUM(CASE WHEN state = 'claimed' AND cancel_requested_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS cancel_requested_claimed_count,
            MIN(CASE WHEN state = 'queued' AND dispatch_mode = 'fresh' THEN created_at END) AS oldest_fresh_queued_at,
            MIN(CASE WHEN state = 'queued' AND dispatch_mode = 'recovery' THEN created_at END) AS oldest_recovery_queued_at,
            MIN(CASE WHEN state = 'claimed' THEN claimed_at END) AS oldest_claimed_at,
            MIN(CASE WHEN state = 'pending_recovery' THEN created_at END) AS oldest_pending_recovery_at
        FROM work_items
        """
    ).fetchone()
    if row is None:
        return QueueSnapshot()
    return QueueSnapshot(
        fresh_queued_count=int(row["fresh_queued_count"] or 0),
        recovery_queued_count=int(row["recovery_queued_count"] or 0),
        claimed_count=int(row["claimed_count"] or 0),
        pending_recovery_count=int(row["pending_recovery_count"] or 0),
        cancel_requested_claimed_count=int(row["cancel_requested_claimed_count"] or 0),
        oldest_fresh_queued_at=row["oldest_fresh_queued_at"],
        oldest_recovery_queued_at=row["oldest_recovery_queued_at"],
        oldest_claimed_at=row["oldest_claimed_at"],
        oldest_pending_recovery_at=row["oldest_pending_recovery_at"],
    )


def upsert_worker_heartbeat(conn: sqlite3.Connection, heartbeat: WorkerHeartbeat) -> None:
    with _write_tx(conn):
        conn.execute(
            """
            INSERT INTO worker_heartbeats (
                worker_id,
                process_role,
                started_at,
                last_seen_at,
                current_item_id,
                current_conversation_key,
                current_kind,
                items_processed,
                stale_recoveries_seen,
                last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                process_role = excluded.process_role,
                started_at = excluded.started_at,
                last_seen_at = excluded.last_seen_at,
                current_item_id = excluded.current_item_id,
                current_conversation_key = excluded.current_conversation_key,
                current_kind = excluded.current_kind,
                items_processed = excluded.items_processed,
                stale_recoveries_seen = excluded.stale_recoveries_seen,
                last_error = excluded.last_error
            """,
            (
                heartbeat.worker_id,
                heartbeat.process_role,
                heartbeat.started_at,
                heartbeat.last_seen_at,
                heartbeat.current_item_id,
                heartbeat.current_conversation_key,
                heartbeat.current_kind,
                heartbeat.items_processed,
                heartbeat.stale_recoveries_seen,
                heartbeat.last_error,
            ),
        )


def clear_worker_heartbeat(conn: sqlite3.Connection, worker_id: str) -> None:
    with _write_tx(conn):
        conn.execute(
            "DELETE FROM worker_heartbeats WHERE worker_id = ?",
            (worker_id,),
        )


def list_worker_heartbeats(conn: sqlite3.Connection) -> list[WorkerHeartbeat]:
    rows = conn.execute(
        "SELECT * FROM worker_heartbeats ORDER BY worker_id ASC"
    ).fetchall()
    return [
        WorkerHeartbeat(
            worker_id=row["worker_id"],
            process_role=row["process_role"],
            started_at=row["started_at"],
            last_seen_at=row["last_seen_at"],
            current_item_id=row["current_item_id"],
            current_conversation_key=row["current_conversation_key"],
            current_kind=row["current_kind"],
            items_processed=int(row["items_processed"] or 0),
            stale_recoveries_seen=int(row["stale_recoveries_seen"] or 0),
            last_error=row["last_error"],
        )
        for row in rows
    ]


def get_update_payload(conn: sqlite3.Connection, event_id: str) -> str | None:
    row = conn.execute(
        "SELECT payload FROM updates WHERE event_id = ?", (event_id,)
    ).fetchone()
    return row["payload"] if row else None


def mark_pending_recovery(conn: sqlite3.Connection, item_id: str) -> None:
    with _write_tx(conn):
        res = _apply_transport_event(
            conn,
            item_id,
            "move_to_pending_recovery",
            "claimed",
            lambda r: TransportWorkflowModel(state=r["state"]),
            "",
            (),
        )
        if res == ApplyResult.success:
            pass
        elif res == ApplyResult.corruption:
            raise TransportStateCorruption(
                f"mark_pending_recovery: invariant violation item {item_id}"
            )


def get_pending_recovery_for_update(
    conn: sqlite3.Connection, conversation_key: str, event_id: str
) -> WorkItemRecord | None:
    row = _load_work_item_by_conversation_event(conn, conversation_key, event_id)
    if row is None or row["state"] != "pending_recovery":
        return None
    return WorkItemRecord.from_mapping(row)


def get_latest_pending_recovery(
    conn: sqlite3.Connection, conversation_key: str
) -> WorkItemRecord | None:
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    rows = conn.execute(
        "SELECT w.*, u.kind, u.payload FROM work_items w "
        "JOIN updates u ON w.event_id = u.event_id "
        "WHERE w.conversation_key = ? ORDER BY w.created_at DESC",
        (conversation_key,),
    ).fetchall()
    for row in rows:
        r = dict(row)
        _validate_work_item_row(r, r["id"])
        if r["state"] == "pending_recovery":
            return WorkItemRecord.from_mapping(r)
    return None


def supersede_pending_recovery(conn: sqlite3.Connection, conversation_key: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        rows = conn.execute(
            "SELECT id FROM work_items WHERE conversation_key = ? AND state = 'pending_recovery'",
            (conversation_key,),
        ).fetchall()
        if not rows:
            return 0
        count = 0
        for row in rows:
            row = dict(row)
            full = _load_work_item_by_id(conn, row["id"])
            if full is None or full["state"] != "pending_recovery":
                continue
            res = _apply_transport_event(
                conn,
                full["id"],
                "supersede_recovery",
                "pending_recovery",
                lambda r: TransportWorkflowModel(state=r["state"]),
                "completed_at = ?, error = ?",
                (now, "superseded"),
            )
            if res == ApplyResult.success:
                count += 1
        if count:
            log.info(
                "Superseded %d pending_recovery items for conversation %s",
                count,
                conversation_key,
            )
        return count


def discard_recovery(conn: sqlite3.Connection, item_id: str) -> DiscardResult:
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        res = _apply_transport_event(
            conn,
            item_id,
            "discard_recovery",
            "pending_recovery",
            lambda r: TransportWorkflowModel(state=r["state"]),
            "completed_at = ?, error = ?",
            (now, "discarded"),
        )
        if res == ApplyResult.success:
            return DiscardResult.success
        if res == ApplyResult.already_handled:
            return DiscardResult.already_handled
        return DiscardResult.corruption


def reclaim_for_replay(
    conn: sqlite3.Connection,
    item_id: str,
    worker_id: str,
    *,
    ignore_claimed_item_id: str = "",
) -> WorkItemRecord | None:
    with _write_tx(conn):
        row = _load_work_item_by_id(conn, item_id)
        if row is None or row["state"] != "pending_recovery":
            return None
        conversation_key = row["conversation_key"]
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        if ignore_claimed_item_id:
            has_claimed = conn.execute(
                "SELECT 1 FROM work_items WHERE conversation_key = ? AND state = 'claimed' "
                "AND id <> ? LIMIT 1",
                (conversation_key, ignore_claimed_item_id),
            ).fetchone()
        else:
            has_claimed = conn.execute(
                "SELECT 1 FROM work_items WHERE conversation_key = ? AND state = 'claimed' LIMIT 1",
                (conversation_key,),
            ).fetchone()
        out = _apply_claim_event(
            conn,
            item_id,
            "reclaim_for_replay",
            "pending_recovery",
            worker_id,
            lambda r: TransportWorkflowModel(
                state=r["state"], has_other_claimed_for_chat=bool(has_claimed)
            ),
        )
        if out is None:
            return None
        full = conn.execute(
            "SELECT w.*, u.kind, u.payload FROM work_items w "
            "JOIN updates u ON w.event_id = u.event_id WHERE w.id = ?",
            (item_id,),
        ).fetchone()
        if full is None:
            return None
        r = dict(full)
        _validate_work_item_row(r, item_id)
        return WorkItemRecord.from_mapping(r)


def recover_stale_claims(
    conn: sqlite3.Connection, lease_ttl_seconds: int = 300
) -> int:
    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(seconds=lease_ttl_seconds)).isoformat()
    with _write_tx(conn):
        rows = conn.execute(
            "SELECT id, state, worker_id, claimed_at, dispatch_mode, cancel_requested_at "
            "FROM work_items WHERE state = 'claimed' AND claimed_at IS NOT NULL AND claimed_at < ?",
            (stale_before,),
        ).fetchall()
        requeued = 0
        for row in rows:
            r = dict(row)
            _validate_work_item_row(r, r["id"])
            model = TransportWorkflowModel(
                state="claimed", worker_id=r["worker_id"], is_stale=True
            )
            result = run_transport_event(model, "recover_stale_claim")
            if not result.allowed:
                if result.disposition == TransportDisposition.guard_failed:
                    continue
                raise TransportStateCorruption(
                    f"recover_stale_claims: workflow rejected for item {r['id']}: "
                    f"{result.disposition} — {result.reason}"
                )
            if r.get("cancel_requested_at"):
                cursor = conn.execute(
                    "UPDATE work_items SET state = 'failed', completed_at = ?, error = 'cancelled' "
                    "WHERE id = ? AND state = 'claimed' AND worker_id = ? AND claimed_at = ?",
                    (now.isoformat(), r["id"], r["worker_id"], r["claimed_at"]),
                )
            else:
                new_state = result.new_state
                cursor = conn.execute(
                    "UPDATE work_items SET state = ?, worker_id = NULL, claimed_at = NULL, dispatch_mode = 'recovery' "
                    "WHERE id = ? AND state = 'claimed' AND worker_id = ? AND claimed_at = ?",
                    (new_state, r["id"], r["worker_id"], r["claimed_at"]),
                )
            if cursor.rowcount > 0:
                requeued += 1
                continue
            re_read = conn.execute(
                "SELECT state, worker_id, claimed_at, dispatch_mode, cancel_requested_at FROM work_items WHERE id = ?",
                (r["id"],),
            ).fetchone()
            if re_read is None:
                continue
            re_read = dict(re_read)
            _validate_work_item_row(re_read, r["id"])
            if re_read["state"] == "claimed" and re_read["worker_id"] == r["worker_id"] and re_read["claimed_at"] == r["claimed_at"]:
                raise TransportStateCorruption(
                    f"recover_stale_claims: update matched 0 rows but item {r['id']} still claimed"
                )
        if requeued:
            log.info("Recovered %d stale work items", requeued)
        return requeued


def recover_after_crash(
    conn: sqlite3.Connection,
    lease_ttl_seconds: int = 300,
) -> int:
    """Recover durable queue state after a worker or process restart."""
    return recover_stale_claims(conn, lease_ttl_seconds)


def purge_old(conn: sqlite3.Connection, older_than_seconds: int = 7 * 24 * 3600) -> int:
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
    with _write_tx(conn):
        cursor = conn.execute(
            "DELETE FROM work_items WHERE state IN ('done', 'failed', 'pending_recovery') AND created_at < ?",
            (cutoff_iso,),
        )
        deleted_items = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM updates WHERE event_id NOT IN (SELECT event_id FROM work_items) "
            "AND received_at < ?",
            (cutoff_iso,),
        )
        deleted_updates = cursor.rowcount
        if deleted_items or deleted_updates:
            log.info("Purged %d work items and %d updates", deleted_items, deleted_updates)
        return deleted_items


def purge_old_usage(conn: sqlite3.Connection, older_than_seconds: int = 30 * 24 * 3600) -> int:
    cutoff_epoch = time.time() - older_than_seconds
    with _write_tx(conn):
        cursor = conn.execute(
            "DELETE FROM usage_log WHERE recorded_at < ?",
            (cutoff_epoch,),
        )
        return cursor.rowcount


def get_user_access_override(conn: sqlite3.Connection, actor_key: str) -> str | None:
    """Return 'allowed', 'blocked', or None when no override exists for actor_key."""
    row = conn.execute(
        "SELECT access FROM user_access WHERE actor_key = ?",
        (actor_key,),
    ).fetchone()
    return row["access"] if row else None


def set_user_access(
    conn: sqlite3.Connection,
    actor_key: str,
    access: str,
    reason: str,
    granted_by: str,
) -> None:
    """Upsert a user access override row."""
    now = datetime.now(timezone.utc).timestamp()
    conn.execute(
        """INSERT INTO user_access (actor_key, access, reason, granted_by, granted_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(actor_key) DO UPDATE SET
               access=excluded.access,
               reason=excluded.reason,
               granted_by=excluded.granted_by,
               granted_at=excluded.granted_at""",
        (actor_key, access, reason, granted_by, now),
    )
    conn.commit()


def list_user_access(conn: sqlite3.Connection) -> list[UserAccessRecord]:
    """Return all user access overrides ordered by most recent grant first."""
    rows = conn.execute(
        "SELECT actor_key, access, reason, granted_by, granted_at "
        "FROM user_access ORDER BY granted_at DESC"
    ).fetchall()
    return [UserAccessRecord.from_mapping(dict(row)) for row in rows]


def record_usage(
    conn: sqlite3.Connection,
    *,
    conversation_key: str,
    work_item_id: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    conn.execute(
        """INSERT INTO usage_log (
               conversation_key, work_item_id, provider, prompt_tokens,
               completion_tokens, cost_usd, recorded_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            conversation_key,
            work_item_id,
            provider,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            time.time(),
        ),
    )
    conn.commit()


def get_usage_since(
    conn: sqlite3.Connection, *, since_epoch: float,
) -> list[UsageRecord]:
    rows = conn.execute(
        """SELECT
               conversation_key, work_item_id, provider, prompt_tokens,
               completion_tokens, cost_usd, recorded_at
           FROM usage_log
           WHERE recorded_at >= ?
           ORDER BY recorded_at""",
        (since_epoch,),
    ).fetchall()
    return [UsageRecord.from_mapping(dict(row)) for row in rows]


class SQLiteTransportStore:
    """SQLite-backed transport store. Each data_dir gets one cached connection to transport.db."""

    def __init__(self) -> None:
        self._connections: dict[Path, sqlite3.Connection] = {}

    def _transport_db(self, data_dir: Path) -> sqlite3.Connection:
        if data_dir in self._connections:
            return self._connections[data_dir]
        db_path = data_dir / "transport.db"
        conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            has_tables = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone() is not None
            if has_tables:
                _ensure_schema_version(conn)
            else:
                _create_new_transport_db(conn)
        except RuntimeError:
            conn.close()
            raise
        except Exception:
            conn.close()
            raise
        self._connections[data_dir] = conn
        return conn

    def close_transport_db(self, data_dir: Path) -> None:
        conn = self._connections.pop(data_dir, None)
        if conn:
            conn.close()

    def close_all_transport_db(self) -> None:
        for data_dir in list(self._connections.keys()):
            self.close_transport_db(data_dir)

    def debug_connection(self, data_dir: Path) -> sqlite3.Connection:
        return self._transport_db(data_dir)

    def reset_db_for_test(self, data_dir: Path) -> None:
        self.close_transport_db(data_dir)
        db_path = data_dir / "transport.db"
        if db_path.exists():
            db_path.unlink()

    def record_and_enqueue(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
        *,
        worker_id: str | None = None,
    ) -> tuple[bool, str | None]:
        conn = self._transport_db(data_dir)
        return record_and_enqueue(conn, event_id, conversation_key, actor_key, kind, payload, worker_id=worker_id)

    def record_and_admit_message(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> tuple[str, str | None]:
        conn = self._transport_db(data_dir)
        try:
            return record_and_admit_message(conn, event_id, conversation_key, actor_key, kind, payload)
        except _DuplicateUpdate:
            return ("duplicate", None)

    def record_update(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> bool:
        conn = self._transport_db(data_dir)
        return record_update(conn, event_id, conversation_key, actor_key, kind, payload)

    def enqueue_work_item(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        *,
        worker_id: str | None = None,
    ) -> str:
        conn = self._transport_db(data_dir)
        return enqueue_work_item(conn, conversation_key, event_id, worker_id=worker_id)

    def update_payload(self, data_dir: Path, event_id: str, payload: str) -> None:
        conn = self._transport_db(data_dir)
        update_payload(conn, event_id, payload)

    def claim_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str, worker_id: str
    ) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(claim_for_update(conn, conversation_key, event_id, worker_id))

    def claim_next(self, data_dir: Path, conversation_key: str, worker_id: str) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(claim_next(conn, conversation_key, worker_id))

    def claim_next_any(self, data_dir: Path, worker_id: str) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(claim_next_any(conn, worker_id))

    def list_incomplete_work_items(self, data_dir: Path) -> list[WorkItemRecord]:
        conn = self._transport_db(data_dir)
        return coerce_work_item_records(list_incomplete_work_items(conn))

    def recover_after_crash(self, data_dir: Path, *, lease_ttl_seconds: int = 300) -> int:
        conn = self._transport_db(data_dir)
        return recover_after_crash(conn, lease_ttl_seconds)

    def complete_work_item(self, data_dir: Path, item_id: str) -> None:
        conn = self._transport_db(data_dir)
        complete_work_item(conn, item_id)

    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None:
        conn = self._transport_db(data_dir)
        fail_work_item(conn, item_id, error)

    def cancel_queued_fresh_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        conn = self._transport_db(data_dir)
        return cancel_queued_fresh_for_chat(conn, conversation_key)

    def request_cancel(
        self,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        *,
        cancel_request_event_id: str = "",
    ) -> CancelRequestResult:
        conn = self._transport_db(data_dir)
        return request_cancel(
            conn,
            conversation_key,
            actor_key,
            cancel_request_event_id=cancel_request_event_id,
        )

    def is_cancel_requested(self, data_dir: Path, item_id: str) -> bool:
        conn = self._transport_db(data_dir)
        return is_cancel_requested(conn, item_id)

    def has_claimed_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        conn = self._transport_db(data_dir)
        return has_claimed_for_chat(conn, conversation_key)

    def has_queued_or_claimed(self, data_dir: Path, conversation_key: str) -> bool:
        conn = self._transport_db(data_dir)
        return has_queued_or_claimed(conn, conversation_key)

    def get_update_payload(self, data_dir: Path, event_id: str) -> str | None:
        conn = self._transport_db(data_dir)
        return get_update_payload(conn, event_id)

    def get_work_items_for_chat(self, data_dir: Path, conversation_key: str) -> list[WorkItemRecord]:
        conn = self._transport_db(data_dir)
        return coerce_work_item_records(get_work_items_for_chat(conn, conversation_key))

    def get_queue_snapshot(self, data_dir: Path) -> QueueSnapshot:
        conn = self._transport_db(data_dir)
        return get_queue_snapshot(conn)

    def upsert_worker_heartbeat(self, data_dir: Path, heartbeat: WorkerHeartbeat) -> None:
        conn = self._transport_db(data_dir)
        upsert_worker_heartbeat(conn, heartbeat)

    def clear_worker_heartbeat(self, data_dir: Path, worker_id: str) -> None:
        conn = self._transport_db(data_dir)
        clear_worker_heartbeat(conn, worker_id)

    def list_worker_heartbeats(self, data_dir: Path) -> list[WorkerHeartbeat]:
        conn = self._transport_db(data_dir)
        return list_worker_heartbeats(conn)

    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None:
        conn = self._transport_db(data_dir)
        mark_pending_recovery(conn, item_id)

    def get_pending_recovery_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str
    ) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(get_pending_recovery_for_update(conn, conversation_key, event_id))

    def get_latest_pending_recovery(self, data_dir: Path, conversation_key: str) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(get_latest_pending_recovery(conn, conversation_key))

    def supersede_pending_recovery(self, data_dir: Path, conversation_key: str) -> int:
        conn = self._transport_db(data_dir)
        return supersede_pending_recovery(conn, conversation_key)

    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult:
        conn = self._transport_db(data_dir)
        return discard_recovery(conn, item_id)

    def reclaim_for_replay(
        self,
        data_dir: Path,
        item_id: str,
        worker_id: str,
        *,
        ignore_claimed_item_id: str = "",
    ) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(
            reclaim_for_replay(
                conn,
                item_id,
                worker_id,
                ignore_claimed_item_id=ignore_claimed_item_id,
            )
        )

    def recover_stale_claims(self, data_dir: Path, *, lease_ttl_seconds: int = 300) -> int:
        conn = self._transport_db(data_dir)
        return recover_stale_claims(conn, lease_ttl_seconds)

    def purge_old(self, data_dir: Path, *, older_than_seconds: int = 7 * 24 * 3600) -> int:
        conn = self._transport_db(data_dir)
        return purge_old(conn, older_than_seconds)

    def purge_old_usage(self, data_dir: Path, *, older_than_seconds: int = 30 * 24 * 3600) -> int:
        conn = self._transport_db(data_dir)
        return purge_old_usage(conn, older_than_seconds)

    def get_user_access(self, data_dir: Path, actor_key: str) -> str | None:
        if data_dir in self._connections:
            return get_user_access_override(self._connections[data_dir], actor_key)
        if not (data_dir / "transport.db").exists():
            return None
        conn = self._transport_db(data_dir)
        return get_user_access_override(conn, actor_key)

    def set_user_access(
        self,
        data_dir: Path,
        actor_key: str,
        access: str,
        reason: str = "",
        granted_by: str = "",
    ) -> None:
        conn = self._transport_db(data_dir)
        set_user_access(conn, actor_key, access, reason, granted_by)

    def list_user_access(self, data_dir: Path) -> list[UserAccessRecord]:
        conn = self._transport_db(data_dir)
        return coerce_user_access_records(list_user_access(conn))

    def record_usage(
        self,
        data_dir: Path,
        *,
        conversation_key: str,
        work_item_id: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
    ) -> None:
        conn = self._transport_db(data_dir)
        record_usage(
            conn,
            conversation_key=conversation_key,
            work_item_id=work_item_id,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )

    def get_usage_since(self, data_dir: Path, *, since_epoch: float) -> list[UsageRecord]:
        conn = self._transport_db(data_dir)
        return coerce_usage_records(get_usage_since(conn, since_epoch=since_epoch))
