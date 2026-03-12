"""Durable transport layer: update journal, work items, claiming, and recovery.

Moves update deduplication and per-chat request serialization from
in-memory state into SQLite so that:

- duplicate ``update_id`` delivery is safe across restarts
- in-flight and queued request state survives crashes
- per-chat ordering is enforced durably, not only by asyncio.Lock
- the same contracts work for future multi-worker webhook deployment

Uses a separate ``transport.db`` (not sessions.db) because transport
data has a different lifecycle and retention policy than session state.
"""

import logging
import re
import sqlite3
import uuid
from contextlib import contextmanager
from enum import Enum
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.workflows.results import TransportDisposition, TransportStateCorruption
from app.workflows.transport_recovery import (
    TRANSPORT_STATES,
    TransportWorkflowModel,
    run_transport_event,
)

log = logging.getLogger(__name__)

_SCHEMA_VERSION = 2


class LeaveClaimed(Exception):
    """Control-flow signal: leave the current claimed work item unreconciled.

    Used when a request is interrupted by process shutdown. The item stays in
    ``claimed`` so the next boot can recover it via ``recover_stale_claims()``.
    """


class PendingRecovery(Exception):
    """Control-flow signal: item transitioned to ``pending_recovery``.

    Raised by ``worker_dispatch`` after sending a recovery notice to the user.
    The worker loop must skip completion — the item is now owned by the user's
    explicit replay/discard choice.
    """


class ReclaimBlocked(Exception):
    """The item exists in ``pending_recovery`` but cannot be reclaimed.

    Raised by ``reclaim_for_replay`` when another item for the same chat
    is already claimed.  Distinct from returning None (item gone/handled)
    so callers can show an appropriate message to the user.
    """


class DiscardResult(str, Enum):
    """Result of discard_recovery for repository-level outcome handling."""

    success = "success"  # Row updated to done
    already_handled = "already_handled"  # Row missing or no longer pending_recovery (race)
    corruption = "corruption"  # Update matched 0 rows but re-read still pending_recovery


class ApplyResult(str, Enum):
    """Result of apply_transport_event (standard mutation adapter)."""

    success = "success"
    already_handled = "already_handled"  # Row missing or state changed by another actor
    workflow_rejected = "workflow_rejected"
    corruption = "corruption"  # Rowcount 0 but re-read still in expected_source_state


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


# ---------------------------------------------------------------------------
# Connection lifecycle (mirrors storage._db pattern)
# ---------------------------------------------------------------------------

_db_connections: dict[Path, sqlite3.Connection] = {}

# Phase 12: when set, transport delegates to work_queue_pg
_pg_url: str = ""
_pg_pool_min: int = 1
_pg_pool_max: int = 10
_pg_connect_timeout: int = 10


def set_postgres_backend(
    database_url: str,
    *,
    pool_min: int = 1,
    pool_max: int = 10,
    connect_timeout: int = 10,
) -> None:
    """Use Postgres for transport store. Call at startup when BOT_DATABASE_URL is set."""
    global _pg_url, _pg_pool_min, _pg_pool_max, _pg_connect_timeout
    _pg_url = database_url
    _pg_pool_min = pool_min
    _pg_pool_max = pool_max
    _pg_connect_timeout = connect_timeout


def _pg_conn():
    """Context manager yielding a Postgres connection when backend is Postgres."""
    if not _pg_url:
        return None
    from app.db.postgres import get_connection
    return get_connection(
        _pg_url,
        min_size=_pg_pool_min,
        max_size=_pg_pool_max,
        connect_timeout=_pg_connect_timeout,
    )

_UNSUPPORTED_SCHEMA_MSG = "Unsupported transport.db schema/layout for this build"

# Expected schema for validation (do not mutate existing DBs before validating).
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
        # PRAGMA table_info returns (cid, name, type, ...); Row or tuple may use index 1 or key "name"
        cols = set()
        for r in infos:
            if hasattr(r, "keys") and "name" in r.keys():
                cols.add(r["name"])
            else:
                cols.add(r[1])
        if _EXPECTED_COLUMNS[table] - cols:
            raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    # Require idx_one_claimed_per_chat to be UNIQUE, on chat_id, partial WHERE state = 'claimed'
    index_list = conn.execute(
        "PRAGMA index_list(work_items)"
    ).fetchall()
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
    info_rows = conn.execute(
        "PRAGMA index_info(" + _REQUIRED_INDEX + ")"
    ).fetchall()
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
    # Require partial predicate to be exactly: WHERE state = 'claimed' (whitespace/case/quote style flexible)
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


def _transport_db(data_dir: Path) -> sqlite3.Connection:
    """Return (or create) a WAL-mode SQLite connection for transport.db.

    For a brand-new DB (no tables), creates schema and inserts schema_version.
    For an existing DB, validates schema/layout only; does not mutate.
    Raises RuntimeError with a neutral message if schema/layout is unsupported.
    """
    if data_dir in _db_connections:
        return _db_connections[data_dir]
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
            _validate_existing_transport_db(conn)
        else:
            _create_new_transport_db(conn)
    except RuntimeError:
        conn.close()
        raise
    except Exception:
        conn.close()
        raise
    _db_connections[data_dir] = conn
    return conn


def close_transport_db(data_dir: Path) -> None:
    """Close the transport database connection for clean shutdown."""
    conn = _db_connections.pop(data_dir, None)
    if conn:
        conn.close()


def close_all_transport_db() -> None:
    """Close all cached transport DB connections (for test isolation)."""
    for data_dir in list(_db_connections.keys()):
        close_transport_db(data_dir)


@contextmanager
def _write_tx(conn: sqlite3.Connection, immediate: bool = True):
    """Single transaction wrapper for all mutating repository entry points.

    On entry: BEGIN IMMEDIATE (or BEGIN). On exit: COMMIT on success;
    ROLLBACK on any exception, then re-raise. Callers must not call
    conn.commit() or conn.rollback() themselves. Nested use raises RuntimeError.
    """
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


def _reset_transport_db(data_dir: Path) -> None:
    """Close and delete the transport database (tests only)."""
    close_transport_db(data_dir)
    db_path = data_dir / "transport.db"
    if db_path.exists():
        db_path.unlink()


# ---------------------------------------------------------------------------
# Row validation (full invariants: state + claimed implies worker_id and claimed_at)
# ---------------------------------------------------------------------------

def _validate_work_item_row(row: dict[str, Any], item_id: str = "") -> None:
    """Raise TransportStateCorruption if row violates transport invariants.

    Enforces: state in TRANSPORT_STATES; if state == 'claimed' then worker_id and claimed_at must be set.
    """
    state = row.get("state")
    if state not in TRANSPORT_STATES:
        raise TransportStateCorruption(f"unknown state {state!r}" + (f" for item {item_id}" if item_id else ""))
    if state == "claimed":
        if row.get("worker_id") is None:
            raise TransportStateCorruption(
                "claimed row must have worker_id" + (f" (item {item_id})" if item_id else "")
            )
        if row.get("claimed_at") is None:
            raise TransportStateCorruption(
                "claimed row must have claimed_at" + (f" (item {item_id})" if item_id else "")
            )


# ---------------------------------------------------------------------------
# Repository primitives (private): load regardless of state, validate, else raise
# ---------------------------------------------------------------------------

def _load_work_item_by_id(
    conn: sqlite3.Connection, item_id: str
) -> dict[str, Any] | None:
    """Load a work item by id. Validates full row invariants; raises TransportStateCorruption if invalid."""
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
    """Load work item by chat_id and update_id (with joined kind/payload). Raise if state invalid."""
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
    """Raise TransportStateCorruption if any work item for this chat has invalid state, row invariants, or more than one claimed row."""
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
    """Single repository path for claiming a queued item. Caller holds transaction.

    Loads and validates row (must be queued), runs machine (claim_inline or claim_worker),
    does exact CAS UPDATE; on rowcount 0 rereads and classifies already_handled vs
    corruption. Returns validated claimed row dict on success, None if already_handled.
    Raises TransportStateCorruption when reread still shows queued.
    """
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
    """Standard mutation: load, validate state, run machine, UPDATE WHERE id AND state, re-read on 0.

    build_model(row) returns TransportWorkflowModel. update_extras is e.g. 'completed_at = ?, error = ?';
    update_extra_args is (now, 'discarded'). Use '' and () for state-only update. Re-read validates; invalid raises.
    """
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
    """Claim-style transition: load, validate, run machine, UPDATE with worker_id/claimed_at, reread on 0.

    Returns updated work_items row dict on success. Returns None if row missing, state changed,
    or disposition is other_claimed_for_chat. Raises ReclaimBlocked(item_id) when disposition
    is blocked_replay. Raises TransportStateCorruption on any other rejection or on reread corruption.
    Caller holds transaction.
    """
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


# ---------------------------------------------------------------------------
# Initial work item insert (single path for create + optional immediate claim)
# ---------------------------------------------------------------------------


def _insert_initial_work_item(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    chat_id: int,
    update_id: int,
    worker_id: str | None,
    created_at: str,
) -> str:
    """Single repository path for creating a work item. Caller holds transaction (or commits after).

    Inserts queued by default. If worker_id is set and chat has no other claimed item,
    runs claim_inline on a synthetic queued model and inserts machine-derived state
    (claimed with worker_id, claimed_at). Otherwise inserts queued. Asserts chat
    has no invalid rows. Returns item_id.
    """
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
# Update journal
# ---------------------------------------------------------------------------

def record_and_enqueue(
    data_dir: Path,
    update_id: int,
    chat_id: int,
    user_id: int,
    kind: str,
    payload: str = "{}",
    *,
    worker_id: str | None = None,
) -> tuple[bool, str | None]:
    """Atomically record an update AND enqueue its work item in one transaction.

    Returns ``(is_new, item_id)``.  If the update is a duplicate,
    returns ``(False, None)`` — neither row is inserted.  A crash
    between the two INSERTs is impossible because they share a single
    ``BEGIN IMMEDIATE`` transaction.

    When *worker_id* is provided the item is created as ``claimed``
    (owned by the inline handler).  This prevents the background worker
    from stealing fresh items before the handler finishes — see
    ``dont_make_false_claims.md`` for the full race analysis.
    Uses shared _insert_initial_work_item for the narrow create-plus-claim path.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.record_and_enqueue(
                conn, update_id, chat_id, user_id, kind, payload, worker_id=worker_id,
            )
    conn = _transport_db(data_dir)
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
    except sqlite3.IntegrityError:
        return False, None


def record_update(
    data_dir: Path,
    update_id: int,
    chat_id: int,
    user_id: int,
    kind: str,
    payload: str = "{}",
) -> bool:
    """Record an inbound update WITHOUT creating a work item.

    Only used by tests that exercise low-level primitives separately.
    Production code should use ``record_and_enqueue``.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.record_update(conn, update_id, chat_id, user_id, kind, payload)
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _write_tx(conn):
            conn.execute(
                "INSERT INTO updates (update_id, chat_id, user_id, kind, payload, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (update_id, chat_id, user_id, kind, payload, now),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def enqueue_work_item(
    data_dir: Path, chat_id: int, update_id: int, *, worker_id: str | None = None,
) -> str:
    """Create a work item for an already-recorded update.

    Only used by tests that exercise low-level primitives separately.
    Production code should use ``record_and_enqueue``.

    Uses shared _insert_initial_work_item (same initial-state semantics as
    record_and_enqueue). Raises TransportStateCorruption if the chat has any invalid row.
    Uses _write_tx so the connection is never left in an open transaction on error.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.enqueue_work_item(conn, chat_id, update_id, worker_id=worker_id)
    conn = _transport_db(data_dir)
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


def update_payload(data_dir: Path, update_id: int, payload: str) -> None:
    """Update the stored payload for an already-recorded update."""
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            work_queue_pg.update_payload(conn, update_id, payload)
        return
    conn = _transport_db(data_dir)
    with _write_tx(conn):
        conn.execute(
            "UPDATE updates SET payload = ? WHERE update_id = ?",
            (payload, update_id),
        )


def claim_for_update(data_dir: Path, chat_id: int, update_id: int, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the work item for a specific update_id.

    Loads by (chat_id, update_id) regardless of state; invalid state raises.
    Returns None if no row or not claimable. Pre-claimed by same worker returns item.
    Uses shared _claim_queued_item for exact CAS + reread classification.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.claim_for_update(conn, chat_id, update_id, worker_id)
    conn = _transport_db(data_dir)
    with _write_tx(conn):
        _assert_no_invalid_rows_for_chat(conn, chat_id)
        row = _load_work_item_by_chat_update(conn, chat_id, update_id)
        if row is None:
            return None
        if row["state"] == "claimed" and row.get("worker_id") == worker_id:
            return dict(row)
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
            out["kind"] = u["kind"]
            out["payload"] = u["payload"]
        return out


def claim_next(data_dir: Path, chat_id: int, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the next queued work item for a chat.

    Selects candidate id then uses shared _claim_queued_item (exact CAS + reread).
    Returns None if no claimable item or another actor won. Raises
    TransportStateCorruption if chat has invalid state or reread finds still queued.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.claim_next(conn, chat_id, worker_id)
    conn = _transport_db(data_dir)
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
        out = _claim_queued_item(
            conn,
            item_id=row["id"],
            worker_id=worker_id,
            has_other_claimed_for_chat=False,
            event_name="claim_worker",
        )
        if out is None:
            return None
        return out


def claim_next_any(data_dir: Path, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the next queued work item across all chats.

    Selects candidate id then uses shared _claim_queued_item (exact CAS + reread).
    Only claims in chats with no other claimed item. Returns row with kind/payload.
    Raises TransportStateCorruption if chosen chat has invalid state or reread finds still queued.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.claim_next_any(conn, worker_id)
    conn = _transport_db(data_dir)
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


def complete_work_item(data_dir: Path, item_id: str) -> None:
    """Mark a work item as done.

    Uses load primitive and re-read on rowcount zero; invalid re-read raises TransportStateCorruption.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            work_queue_pg.complete_work_item(conn, item_id)
        return
    conn = _transport_db(data_dir)
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


def fail_work_item(data_dir: Path, item_id: str, error: str) -> None:
    """Mark a work item as failed.

    Uses load primitive and re-read on rowcount zero; invalid re-read raises TransportStateCorruption.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            work_queue_pg.fail_work_item(conn, item_id, error)
        return
    conn = _transport_db(data_dir)
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


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def has_claimed_for_chat(data_dir: Path, chat_id: int) -> bool:
    """True if the chat has any work item in claimed state."""
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.has_claimed_for_chat(conn, chat_id)
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed' LIMIT 1",
        (chat_id,),
    ).fetchone()
    return row is not None


def has_queued_or_claimed(data_dir: Path, chat_id: int) -> bool:
    """Check if a chat has any in-flight or queued work items.

    Asserts chat integrity (at most one claimed, valid row state) before answering.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.has_queued_or_claimed(conn, chat_id)
    conn = _transport_db(data_dir)
    _assert_no_invalid_rows_for_chat(conn, chat_id)
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE chat_id = ? AND state IN ('queued', 'claimed') LIMIT 1",
        (chat_id,),
    ).fetchone()
    return row is not None


def get_update_payload(data_dir: Path, update_id: int) -> str | None:
    """Retrieve the stored payload for an update."""
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.get_update_payload(conn, update_id)
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT payload FROM updates WHERE update_id = ?", (update_id,)
    ).fetchone()
    return row["payload"] if row else None


# ---------------------------------------------------------------------------
# Pending recovery (user-intent-owned replay)
# ---------------------------------------------------------------------------

def mark_pending_recovery(data_dir: Path, item_id: str) -> None:
    """Transition a claimed item to pending_recovery.

    Uses load and _apply_transport_event; re-read on rowcount zero validates state.
    completed_at is terminal-only; not set here.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            work_queue_pg.mark_pending_recovery(conn, item_id)
        return
    conn = _transport_db(data_dir)
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
            pass  # commit at exit
        elif res == ApplyResult.corruption:
            raise TransportStateCorruption(
                f"mark_pending_recovery: invariant violation item {item_id}"
            )
        # already_handled: no-op (row missing or state changed by another actor)


def get_pending_recovery_for_update(
    data_dir: Path, chat_id: int, update_id: int
) -> dict[str, Any] | None:
    """Get the pending_recovery item for a specific (chat_id, update_id).

    Loads by chat and update regardless of state; invalid state raises.
    Returns None only if no row or state is not pending_recovery.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.get_pending_recovery_for_update(conn, chat_id, update_id)
    conn = _transport_db(data_dir)
    row = _load_work_item_by_chat_update(conn, chat_id, update_id)
    if row is None or row["state"] != "pending_recovery":
        return None
    return row


def get_latest_pending_recovery(data_dir: Path, chat_id: int) -> dict[str, Any] | None:
    """Get the newest pending_recovery item for a chat by created_at.

    Asserts chat integrity before scanning; validates every work item through shared row validator.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.get_latest_pending_recovery(conn, chat_id)
    conn = _transport_db(data_dir)
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


def supersede_pending_recovery(data_dir: Path, chat_id: int) -> int:
    """Finalize any pending_recovery items for a chat as superseded.

    Called when a fresh message arrives — the user chose to move on
    rather than replay the interrupted request.  Returns the number
    of items superseded.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.supersede_pending_recovery(conn, chat_id)
    conn = _transport_db(data_dir)
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


def discard_recovery(data_dir: Path, item_id: str) -> DiscardResult:
    """Finalize a pending_recovery item as discarded (user chose not to replay).

    Uses _load_work_item_by_id and _apply_transport_event; re-read validates state.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.discard_recovery(conn, item_id)
    conn = _transport_db(data_dir)
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


def reclaim_for_replay(data_dir: Path, item_id: str, worker_id: str) -> dict[str, Any] | None:
    """Transition a pending_recovery item back to claimed for replay.

    Enforces the per-chat single-claimed invariant: if another item for
    the same chat is already claimed, the reclaim is rejected (raises
    ``ReclaimBlocked``).  Uses _apply_claim_event for exact CAS and reread classification.

    Returns the item dict (with kind/payload) if successful, None if the item is no longer
    in pending_recovery or already handled.  Raises ``ReclaimBlocked``
    if the item exists but another item for the same chat is claimed.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.reclaim_for_replay(conn, item_id, worker_id)
    conn = _transport_db(data_dir)
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


# ---------------------------------------------------------------------------
# Recovery and retention
# ---------------------------------------------------------------------------

def recover_stale_claims(
    data_dir: Path, current_worker_id: str, max_age_seconds: int = 300,
) -> int:
    """Requeue work items claimed by dead workers or held too long.

    Called at startup to recover from crashes.  Returns the number of
    items requeued.
    """
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.recover_stale_claims(conn, current_worker_id, max_age_seconds)
    conn = _transport_db(data_dir)
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
            if row["worker_id"] != current_worker_id:
                stale = True
            elif row["claimed_at"]:
                claimed = datetime.fromisoformat(row["claimed_at"])
                if (now - claimed).total_seconds() > max_age_seconds:
                    stale = True
            if stale:
                model = TransportWorkflowModel(
                    state="claimed", worker_id=row["worker_id"], is_stale=True
                )
                result = run_transport_event(model, "recover_stale_claim")
                if not result.allowed:
                    if result.disposition == TransportDisposition.guard_failed:
                        continue  # not stale (same worker, not expired), skip
                    raise TransportStateCorruption(
                        f"recover_stale_claims: workflow rejected for item {row['id']}: "
                        f"{result.disposition} — {result.reason}"
                    )
                new_state = result.new_state
                cursor = conn.execute(
                    "UPDATE work_items SET state = ?, worker_id = NULL, claimed_at = NULL "
                    "WHERE id = ? AND state = 'claimed' AND worker_id = ? AND claimed_at = ?",
                    (new_state, row["id"], row["worker_id"], row["claimed_at"]),
                )
                if cursor.rowcount > 0:
                    requeued += 1
                    continue
                re_read = conn.execute(
                    "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                if re_read is None:
                    continue
                _validate_work_item_row(dict(re_read), row["id"])
                if re_read["state"] == "claimed" and re_read["worker_id"] == row["worker_id"] and re_read["claimed_at"] == row["claimed_at"]:
                    raise TransportStateCorruption(
                        f"recover_stale_claims: update matched 0 rows but item {row['id']} still claimed"
                    )
        if requeued:
            log.info("Recovered %d stale work items", requeued)
        return requeued


def purge_old(data_dir: Path, older_than_hours: int = 24) -> int:
    """Delete completed/failed work items and their updates older than the threshold."""
    if _pg_url:
        from app import work_queue_pg
        with _pg_conn() as conn:
            return work_queue_pg.purge_old(conn, older_than_hours)
    conn = _transport_db(data_dir)
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
