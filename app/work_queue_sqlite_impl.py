"""SQLite transport implementation with conn-based API (same shape as work_queue_pg)."""

from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.transport_contract import (
    ApplyResult,
    DiscardResult,
    ReclaimBlocked,
    _validate_work_item_row,
)
from app.workflows.results import TransportDisposition, TransportStateCorruption
from app.workflows.transport_recovery import (
    TRANSPORT_STATES,
    TransportWorkflowModel,
    run_transport_event,
)

log = logging.getLogger(__name__)

_SCHEMA_VERSION = 2

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS updates (
    update_id   INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    kind        TEXT    NOT NULL,
    payload     TEXT    NOT NULL DEFAULT '{}',
    received_at TEXT    NOT NULL,
    state       TEXT    NOT NULL DEFAULT 'received'
);
CREATE INDEX IF NOT EXISTS idx_updates_chat ON updates (chat_id, received_at);

CREATE TABLE IF NOT EXISTS work_items (
    id          TEXT    PRIMARY KEY,
    chat_id     INTEGER NOT NULL,
    update_id   INTEGER NOT NULL UNIQUE REFERENCES updates(update_id),
    state       TEXT    NOT NULL DEFAULT 'queued',
    worker_id   TEXT,
    claimed_at  TEXT,
    completed_at TEXT,
    error       TEXT,
    created_at  TEXT    NOT NULL,
    CHECK (state IN ('queued','claimed','pending_recovery','done','failed')),
    CHECK (state != 'claimed' OR worker_id IS NOT NULL),
    CHECK (state != 'claimed' OR claimed_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_work_items_state ON work_items (state, chat_id);
CREATE INDEX IF NOT EXISTS idx_work_items_chat  ON work_items (chat_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_claimed_per_chat ON work_items(chat_id) WHERE state = 'claimed';

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_UNSUPPORTED_SCHEMA_MSG = "Unsupported transport.db schema/layout for this build"
_EXPECTED_TABLES = ("updates", "work_items", "meta")
_EXPECTED_COLUMNS: dict[str, set[str]] = {
    "updates": {"update_id", "chat_id", "user_id", "kind", "payload", "received_at", "state"},
    "work_items": {"id", "chat_id", "update_id", "state", "worker_id", "claimed_at", "completed_at", "error", "created_at"},
    "meta": {"key", "value"},
}
_REQUIRED_INDEX = "idx_one_claimed_per_chat"


def _create_new_transport_db(conn: sqlite3.Connection) -> None:
    """Initialize a brand-new transport DB. Call only when the file has no tables."""
    conn.executescript(_CREATE_SQL)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.commit()


def _validate_existing_transport_db(conn: sqlite3.Connection) -> None:
    """Verify an existing transport DB has the supported schema/layout. Does not mutate."""
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    if _EXPECTED_TABLES[0] not in tables or _EXPECTED_TABLES[1] not in tables or _EXPECTED_TABLES[2] not in tables:
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
    if index_cols != ["chat_id"]:
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


def _load_work_item_by_chat_update(
    conn: sqlite3.Connection, chat_id: int, update_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT w.*, u.kind, u.payload FROM work_items w "
        "JOIN updates u ON w.update_id = u.update_id "
        "WHERE w.chat_id = ? AND w.update_id = ?",
        (chat_id, update_id),
    ).fetchone()
    if row is None:
        return None
    row = dict(row)
    _validate_work_item_row(row)
    return row


def _assert_no_invalid_rows_for_chat(conn: sqlite3.Connection, chat_id: int) -> None:
    rows = conn.execute(
        "SELECT id, state, worker_id, claimed_at FROM work_items WHERE chat_id = ?", (chat_id,)
    ).fetchall()
    claimed = 0
    for row in rows:
        r = dict(row)
        _validate_work_item_row(r, r["id"])
        if r["state"] == "claimed":
            claimed += 1
    if claimed > 1:
        raise TransportStateCorruption(
            f"chat {chat_id} has {claimed} claimed work items (at most one allowed)"
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
        "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
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
        "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
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
        "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
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
    chat_id: int,
    update_id: int,
    worker_id: str | None,
    created_at: str,
) -> str:
    _assert_no_invalid_rows_for_chat(conn, chat_id)
    has_other_claimed = conn.execute(
        "SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed' LIMIT 1",
        (chat_id,),
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
                "(id, chat_id, update_id, state, worker_id, claimed_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item_id, chat_id, update_id, result.new_state, worker_id, created_at, created_at),
            )
            return item_id
        raise TransportStateCorruption(
            f"_insert_initial_work_item: claim_inline rejected for item {item_id}: "
            f"{result.disposition} — {result.reason}"
        )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, created_at) "
        "VALUES (?, ?, ?, 'queued', ?)",
        (item_id, chat_id, update_id, created_at),
    )
    return item_id


# ---------------------------------------------------------------------------
# Public API (conn as first arg)
# ---------------------------------------------------------------------------

def record_and_enqueue(
    conn: sqlite3.Connection,
    update_id: int,
    chat_id: int,
    user_id: int,
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
                "INSERT INTO updates (update_id, chat_id, user_id, kind, payload, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (update_id, chat_id, user_id, kind, payload, now),
            )
            _insert_initial_work_item(
                conn,
                item_id=item_id,
                chat_id=chat_id,
                update_id=update_id,
                worker_id=worker_id,
                created_at=now,
            )
        return True, item_id
    except sqlite3.IntegrityError as exc:
        if "updates.update_id" in str(exc):
            return False, None
        raise


def record_update(
    conn: sqlite3.Connection,
    update_id: int,
    chat_id: int,
    user_id: int,
    kind: str,
    payload: str = "{}",
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _write_tx(conn):
            conn.execute(
                "INSERT INTO updates (update_id, chat_id, user_id, kind, payload, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (update_id, chat_id, user_id, kind, payload, now),
            )
        return True
    except sqlite3.IntegrityError as exc:
        if "updates.update_id" in str(exc):
            return False
        raise


def enqueue_work_item(
    conn: sqlite3.Connection,
    chat_id: int,
    update_id: int,
    *,
    worker_id: str | None = None,
) -> str:
    item_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        _insert_initial_work_item(
            conn,
            item_id=item_id,
            chat_id=chat_id,
            update_id=update_id,
            worker_id=worker_id,
            created_at=now,
        )
    return item_id


def update_payload(conn: sqlite3.Connection, update_id: int, payload: str) -> None:
    with _write_tx(conn):
        conn.execute(
            "UPDATE updates SET payload = ? WHERE update_id = ?",
            (payload, update_id),
        )


def claim_for_update(
    conn: sqlite3.Connection, chat_id: int, update_id: int, worker_id: str
) -> dict[str, Any] | None:
    with _write_tx(conn):
        _assert_no_invalid_rows_for_chat(conn, chat_id)
        row = _load_work_item_by_chat_update(conn, chat_id, update_id)
        if row is None:
            return None
        if row["state"] == "claimed" and row.get("worker_id") == worker_id:
            return row
        if row["state"] != "queued":
            return None
        has_other_claimed = conn.execute(
            "SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed' LIMIT 1",
            (chat_id,),
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
            "SELECT kind, payload FROM updates WHERE update_id = ?",
            (out["update_id"],),
        ).fetchone()
        if u:
            u = dict(u)
            out["kind"] = u["kind"]
            out["payload"] = u["payload"]
        return out


def claim_next(
    conn: sqlite3.Connection, chat_id: int, worker_id: str
) -> dict[str, Any] | None:
    with _write_tx(conn):
        _assert_no_invalid_rows_for_chat(conn, chat_id)
        row = conn.execute(
            "SELECT id FROM work_items "
            "WHERE chat_id = ? AND state = 'queued' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed'"
            ") "
            "ORDER BY created_at LIMIT 1",
            (chat_id, chat_id),
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
        return out


def claim_next_any(conn: sqlite3.Connection, worker_id: str) -> dict[str, Any] | None:
    with _write_tx(conn):
        row = conn.execute(
            "SELECT id, chat_id FROM work_items "
            "WHERE state = 'queued' "
            "AND chat_id NOT IN ("
            "  SELECT DISTINCT chat_id FROM work_items WHERE state = 'claimed'"
            ") "
            "ORDER BY created_at LIMIT 1",
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        _assert_no_invalid_rows_for_chat(conn, row["chat_id"])
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
            "JOIN updates u ON w.update_id = u.update_id WHERE w.id = ?",
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
            "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
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
            "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
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


def has_claimed_for_chat(conn: sqlite3.Connection, chat_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed' LIMIT 1",
        (chat_id,),
    ).fetchone()
    return row is not None


def has_queued_or_claimed(conn: sqlite3.Connection, chat_id: int) -> bool:
    _assert_no_invalid_rows_for_chat(conn, chat_id)
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE chat_id = ? AND state IN ('queued', 'claimed') LIMIT 1",
        (chat_id,),
    ).fetchone()
    return row is not None


def get_update_payload(conn: sqlite3.Connection, update_id: int) -> str | None:
    row = conn.execute(
        "SELECT payload FROM updates WHERE update_id = ?", (update_id,)
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
    conn: sqlite3.Connection, chat_id: int, update_id: int
) -> dict[str, Any] | None:
    row = _load_work_item_by_chat_update(conn, chat_id, update_id)
    if row is None or row["state"] != "pending_recovery":
        return None
    return row


def get_latest_pending_recovery(
    conn: sqlite3.Connection, chat_id: int
) -> dict[str, Any] | None:
    _assert_no_invalid_rows_for_chat(conn, chat_id)
    rows = conn.execute(
        "SELECT w.*, u.kind, u.payload FROM work_items w "
        "JOIN updates u ON w.update_id = u.update_id "
        "WHERE w.chat_id = ? ORDER BY w.created_at DESC",
        (chat_id,),
    ).fetchall()
    for row in rows:
        r = dict(row)
        _validate_work_item_row(r, r["id"])
        if r["state"] == "pending_recovery":
            return r
    return None


def supersede_pending_recovery(conn: sqlite3.Connection, chat_id: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        _assert_no_invalid_rows_for_chat(conn, chat_id)
        rows = conn.execute(
            "SELECT id FROM work_items WHERE chat_id = ? AND state = 'pending_recovery'",
            (chat_id,),
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
            log.info("Superseded %d pending_recovery items for chat %d", count, chat_id)
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
    conn: sqlite3.Connection, item_id: str, worker_id: str
) -> dict[str, Any] | None:
    with _write_tx(conn):
        row = _load_work_item_by_id(conn, item_id)
        if row is None or row["state"] != "pending_recovery":
            return None
        chat_id = row["chat_id"]
        _assert_no_invalid_rows_for_chat(conn, chat_id)
        has_claimed = conn.execute(
            "SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed' LIMIT 1",
            (chat_id,),
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
            "JOIN updates u ON w.update_id = u.update_id WHERE w.id = ?",
            (item_id,),
        ).fetchone()
        if full is None:
            return None
        r = dict(full)
        _validate_work_item_row(r, item_id)
        return r


def recover_stale_claims(
    conn: sqlite3.Connection, current_worker_id: str, max_age_seconds: int = 300
) -> int:
    now = datetime.now(timezone.utc)
    with _write_tx(conn):
        rows = conn.execute(
            "SELECT id, state, worker_id, claimed_at FROM work_items WHERE state = 'claimed'"
        ).fetchall()
        requeued = 0
        for row in rows:
            r = dict(row)
            _validate_work_item_row(r, r["id"])
            stale = False
            if r["worker_id"] != current_worker_id:
                stale = True
            elif r["claimed_at"]:
                claimed = datetime.fromisoformat(r["claimed_at"])
                if (now - claimed).total_seconds() > max_age_seconds:
                    stale = True
            if stale:
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
                new_state = result.new_state
                cursor = conn.execute(
                    "UPDATE work_items SET state = ?, worker_id = NULL, claimed_at = NULL "
                    "WHERE id = ? AND state = 'claimed' AND worker_id = ? AND claimed_at = ?",
                    (new_state, r["id"], r["worker_id"], r["claimed_at"]),
                )
                if cursor.rowcount > 0:
                    requeued += 1
                    continue
                re_read = conn.execute(
                    "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?",
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


def purge_old(conn: sqlite3.Connection, older_than_hours: int = 24) -> int:
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    with _write_tx(conn):
        cursor = conn.execute(
            "DELETE FROM work_items WHERE state IN ('done', 'failed', 'pending_recovery') AND created_at < ?",
            (cutoff_iso,),
        )
        deleted_items = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM updates WHERE update_id NOT IN (SELECT update_id FROM work_items) "
            "AND received_at < ?",
            (cutoff_iso,),
        )
        deleted_updates = cursor.rowcount
        if deleted_items or deleted_updates:
            log.info("Purged %d work items and %d updates", deleted_items, deleted_updates)
        return deleted_items
