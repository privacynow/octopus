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
import sqlite3
import uuid
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

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Connection lifecycle (mirrors storage._db pattern)
# ---------------------------------------------------------------------------

_db_connections: dict[Path, sqlite3.Connection] = {}


def _transport_db(data_dir: Path) -> sqlite3.Connection:
    """Return (or create) a WAL-mode SQLite connection for transport.db."""
    if data_dir in _db_connections:
        return _db_connections[data_dir]
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_CREATE_SQL)
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            # Distinguish fresh DB (empty meta) from old DB missing schema_version.
            if conn.execute("SELECT 1 FROM meta LIMIT 1").fetchone() is not None:
                conn.close()
                raise RuntimeError(
                    f"Unsupported transport.db schema (no schema_version key). "
                    f"Delete {db_path} and restart the bot."
                )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            conn.commit()
        else:
            stored = int(row["value"])
            if stored != _SCHEMA_VERSION:
                conn.close()
                raise RuntimeError(
                    f"Unsupported transport.db schema (version {stored}). "
                    f"Delete {db_path} and restart the bot."
                )
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
    """Raise TransportStateCorruption if any work item for this chat has invalid state or row invariants."""
    rows = conn.execute(
        "SELECT id, state, worker_id, claimed_at FROM work_items WHERE chat_id = ?", (chat_id,)
    ).fetchall()
    for row in rows:
        r = dict(row)
        _validate_work_item_row(r, r["id"])


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
        return ApplyResult.workflow_rejected
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
    """
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    item_id = uuid.uuid4().hex
    conn.execute("BEGIN IMMEDIATE")
    try:
        _assert_no_invalid_rows_for_chat(conn, chat_id)
        conn.execute(
            "INSERT INTO updates (update_id, chat_id, user_id, kind, payload, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (update_id, chat_id, user_id, kind, payload, now),
        )
        # Create as queued by default. Only create as claimed via machine contract (narrow path).
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
                    (item_id, chat_id, update_id, result.new_state, worker_id, now, now),
                )
            else:
                conn.execute(
                    "INSERT INTO work_items (id, chat_id, update_id, state, created_at) "
                    "VALUES (?, ?, ?, 'queued', ?)",
                    (item_id, chat_id, update_id, now),
                )
        else:
            conn.execute(
                "INSERT INTO work_items (id, chat_id, update_id, state, created_at) "
                "VALUES (?, ?, ?, 'queued', ?)",
                (item_id, chat_id, update_id, now),
            )
        conn.execute("COMMIT")
        return True, item_id
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
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
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO updates (update_id, chat_id, user_id, kind, payload, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (update_id, chat_id, user_id, kind, payload, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def enqueue_work_item(
    data_dir: Path, chat_id: int, update_id: int, *, worker_id: str | None = None,
) -> str:
    """Create a work item for an already-recorded update.

    Only used by tests that exercise low-level primitives separately.
    Production code should use ``record_and_enqueue``.

    When *worker_id* is provided, the item starts as ``claimed`` only if
    the chat has no existing claimed item; otherwise ``queued``.
    Raises TransportStateCorruption if the chat has any invalid row.
    """
    conn = _transport_db(data_dir)
    _assert_no_invalid_rows_for_chat(conn, chat_id)
    item_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
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
                (item_id, chat_id, update_id, result.new_state, worker_id, now, now),
            )
        else:
            conn.execute(
                "INSERT INTO work_items (id, chat_id, update_id, state, created_at) "
                "VALUES (?, ?, ?, 'queued', ?)",
                (item_id, chat_id, update_id, now),
            )
    else:
        conn.execute(
            "INSERT INTO work_items (id, chat_id, update_id, state, created_at) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (item_id, chat_id, update_id, now),
        )
    conn.commit()
    return item_id


def update_payload(data_dir: Path, update_id: int, payload: str) -> None:
    """Update the stored payload for an already-recorded update."""
    conn = _transport_db(data_dir)
    conn.execute(
        "UPDATE updates SET payload = ? WHERE update_id = ?",
        (payload, update_id),
    )
    conn.commit()


def claim_for_update(data_dir: Path, chat_id: int, update_id: int, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the work item for a specific update_id.

    Loads by (chat_id, update_id) regardless of state; invalid state raises.
    Returns None if no row or not claimable. Pre-claimed by same worker returns item.
    """
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _assert_no_invalid_rows_for_chat(conn, chat_id)
        row = _load_work_item_by_chat_update(conn, chat_id, update_id)
        if row is None:
            conn.execute("COMMIT")
            return None
        if row["state"] == "claimed" and row.get("worker_id") == worker_id:
            conn.execute("COMMIT")
            return dict(row)
        if row["state"] != "queued":
            conn.execute("COMMIT")
            return None
        has_other_claimed = conn.execute(
            "SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed' LIMIT 1",
            (chat_id,),
        ).fetchone()
        model = TransportWorkflowModel(
            state="queued", has_other_claimed_for_chat=bool(has_other_claimed)
        )
        result = run_transport_event(
            model, "claim_inline", requesting_worker_id=worker_id
        )
        if not result.allowed:
            conn.execute("COMMIT")
            return None
        item_id = row["id"]
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = ?, claimed_at = ? "
            "WHERE id = ? AND state = 'queued'",
            (worker_id, now, item_id),
        )
        conn.execute("COMMIT")
    except TransportStateCorruption:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    item = conn.execute(
        "SELECT * FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if item is None:
        return None
    row = dict(item)
    _validate_work_item_row(row, item_id)
    return row


def claim_next(data_dir: Path, chat_id: int, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the next queued work item for a chat.

    Uses exact compare-and-update (WHERE id = ? AND state = 'queued'); on rowcount
    zero rereads and classifies already_handled vs corruption. Returns None if no
    claimable item or another actor won. Raises TransportStateCorruption if the
    chat has invalid state or reread finds still queued.
    """
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
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
            conn.execute("COMMIT")
            return None
        item_id = row["id"]
        full = _load_work_item_by_id(conn, item_id)
        if full is None or full["state"] != "queued":
            conn.execute("COMMIT")
            return None
        model = TransportWorkflowModel(state="queued", has_other_claimed_for_chat=False)
        result = run_transport_event(model, "claim_worker")
        if not result.allowed:
            conn.execute("COMMIT")
            return None
        cursor = conn.execute(
            "UPDATE work_items SET state = ?, worker_id = ?, claimed_at = ? "
            "WHERE id = ? AND state = ?",
            (result.new_state, worker_id, now, item_id, "queued"),
        )
        if cursor.rowcount > 0:
            conn.execute("COMMIT")
            item = conn.execute(
                "SELECT * FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            if item is None:
                return None
            out = dict(item)
            _validate_work_item_row(out, item_id)
            return out
        re_read = conn.execute(
            "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        if re_read is None:
            conn.execute("COMMIT")
            return None
        _validate_work_item_row(dict(re_read), item_id)
        if re_read["state"] != "queued":
            conn.execute("COMMIT")
            return None
        log.error(
            "claim_next: invariant violation item %s (still queued after UPDATE 0 rows)",
            item_id,
        )
        conn.execute("ROLLBACK")
        raise TransportStateCorruption(
            f"claim_next: update matched 0 rows but item {item_id} still queued"
        )
    except TransportStateCorruption:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise


def claim_next_any(data_dir: Path, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the next queued work item across all chats.

    Uses exact compare-and-update (WHERE id = ? AND state = 'queued'); on rowcount
    zero rereads and classifies already_handled vs corruption. Only claims in chats
    with no other claimed item. Raises TransportStateCorruption if the chosen chat
    has invalid state or reread finds still queued.
    """
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT id, chat_id FROM work_items "
            "WHERE state = 'queued' "
            "AND chat_id NOT IN ("
            "  SELECT DISTINCT chat_id FROM work_items WHERE state = 'claimed'"
            ") "
            "ORDER BY created_at LIMIT 1",
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        _assert_no_invalid_rows_for_chat(conn, row["chat_id"])
        item_id = row["id"]
        full = _load_work_item_by_id(conn, item_id)
        if full is None or full["state"] != "queued":
            conn.execute("COMMIT")
            return None
        model = TransportWorkflowModel(state="queued", has_other_claimed_for_chat=False)
        result = run_transport_event(model, "claim_worker")
        if not result.allowed:
            conn.execute("COMMIT")
            return None
        cursor = conn.execute(
            "UPDATE work_items SET state = ?, worker_id = ?, claimed_at = ? "
            "WHERE id = ? AND state = ?",
            (result.new_state, worker_id, now, item_id, "queued"),
        )
        if cursor.rowcount > 0:
            conn.execute("COMMIT")
            item = conn.execute(
                "SELECT w.*, u.kind, u.payload FROM work_items w "
                "JOIN updates u ON w.update_id = u.update_id WHERE w.id = ?",
                (item_id,),
            ).fetchone()
            if item is None:
                return None
            out = dict(item)
            _validate_work_item_row(out, item_id)
            return out
        re_read = conn.execute(
            "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        if re_read is None:
            conn.execute("COMMIT")
            return None
        _validate_work_item_row(dict(re_read), item_id)
        if re_read["state"] != "queued":
            conn.execute("COMMIT")
            return None
        log.error(
            "claim_next_any: invariant violation item %s (still queued after UPDATE 0 rows)",
            item_id,
        )
        conn.execute("ROLLBACK")
        raise TransportStateCorruption(
            f"claim_next_any: update matched 0 rows but item {item_id} still queued"
        )
    except TransportStateCorruption:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise


def complete_work_item(data_dir: Path, item_id: str) -> None:
    """Mark a work item as done.

    Uses load primitive and re-read on rowcount zero; invalid re-read raises TransportStateCorruption.
    """
    conn = _transport_db(data_dir)
    row = _load_work_item_by_id(conn, item_id)
    if row is None:
        return
    loaded_state = row["state"]
    if loaded_state not in ("queued", "claimed"):
        return
    model = TransportWorkflowModel(state=loaded_state)
    result = run_transport_event(model, "complete")
    if not result.allowed:
        if result.disposition == TransportDisposition.invalid_transition:
            log.error(
                "complete_work_item: workflow rejected for item %s: %s",
                item_id, result.reason,
            )
        return
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE work_items SET state = ?, completed_at = ?, error = ? "
        "WHERE id = ? AND state = ?",
        (result.new_state, now, None, item_id, loaded_state),
    )
    if cursor.rowcount > 0:
        conn.commit()
        return
    re_read = conn.execute(
        "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if re_read is None:
        conn.commit()
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
    conn.commit()


def fail_work_item(data_dir: Path, item_id: str, error: str) -> None:
    """Mark a work item as failed.

    Uses load primitive and re-read on rowcount zero; invalid re-read raises TransportStateCorruption.
    """
    conn = _transport_db(data_dir)
    row = _load_work_item_by_id(conn, item_id)
    if row is None:
        return
    loaded_state = row["state"]
    if loaded_state not in ("queued", "claimed"):
        return
    model = TransportWorkflowModel(state=loaded_state)
    result = run_transport_event(model, "fail")
    if not result.allowed:
        if result.disposition == TransportDisposition.invalid_transition:
            log.error(
                "fail_work_item: workflow rejected for item %s: %s",
                item_id, result.reason,
            )
        return
    now = datetime.now(timezone.utc).isoformat()
    err = (error or "")[:500]
    cursor = conn.execute(
        "UPDATE work_items SET state = ?, completed_at = ?, error = ? "
        "WHERE id = ? AND state = ?",
        (result.new_state, now, err, item_id, loaded_state),
    )
    if cursor.rowcount > 0:
        conn.commit()
        return
    re_read = conn.execute(
        "SELECT state, worker_id, claimed_at FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if re_read is None:
        conn.commit()
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
    conn.commit()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def has_queued_or_claimed(data_dir: Path, chat_id: int) -> bool:
    """Check if a chat has any in-flight or queued work items."""
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT 1 FROM work_items WHERE chat_id = ? AND state IN ('queued', 'claimed') LIMIT 1",
        (chat_id,),
    ).fetchone()
    return row is not None


def get_update_payload(data_dir: Path, update_id: int) -> str | None:
    """Retrieve the stored payload for an update."""
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
    conn = _transport_db(data_dir)
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
        conn.commit()
    elif res == ApplyResult.corruption:
        raise TransportStateCorruption(
            f"mark_pending_recovery: invariant violation item {item_id}"
        )
    # already_handled or workflow_rejected: no-op


def get_pending_recovery_for_update(
    data_dir: Path, chat_id: int, update_id: int
) -> dict[str, Any] | None:
    """Get the pending_recovery item for a specific (chat_id, update_id).

    Loads by chat and update regardless of state; invalid state raises.
    Returns None only if no row or state is not pending_recovery.
    """
    conn = _transport_db(data_dir)
    row = _load_work_item_by_chat_update(conn, chat_id, update_id)
    if row is None or row["state"] != "pending_recovery":
        return None
    return row


def get_latest_pending_recovery(data_dir: Path, chat_id: int) -> dict[str, Any] | None:
    """Get the newest pending_recovery item for a chat by created_at.

    Validates every work item through shared row validator; invalid state raises.
    """
    conn = _transport_db(data_dir)
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
    conn = _transport_db(data_dir)
    rows = conn.execute(
        "SELECT id FROM work_items WHERE chat_id = ? AND state = 'pending_recovery'",
        (chat_id,),
    ).fetchall()
    if not rows:
        return 0
    for row in rows:
        full = _load_work_item_by_id(conn, row["id"])
        if full is None or full["state"] != "pending_recovery":
            continue
        model = TransportWorkflowModel(state=full["state"])
        result = run_transport_event(model, "supersede_recovery")
        if not result.allowed:
            if result.disposition == TransportDisposition.invalid_transition:
                log.error(
                    "supersede_pending_recovery: workflow rejected for chat %s item %s: %s",
                    chat_id, full["id"], result.reason,
                )
            return 0
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE work_items SET state = 'done', completed_at = ?, error = 'superseded' "
        "WHERE chat_id = ? AND state = 'pending_recovery'",
        (now, chat_id),
    )
    count = cursor.rowcount
    conn.commit()
    if count:
        log.info("Superseded %d pending_recovery items for chat %d", count, chat_id)
    return count


def discard_recovery(data_dir: Path, item_id: str) -> DiscardResult:
    """Finalize a pending_recovery item as discarded (user chose not to replay).

    Uses _load_work_item_by_id and _apply_transport_event; re-read validates state.
    """
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
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
        conn.commit()
        return DiscardResult.success
    if res == ApplyResult.already_handled:
        conn.commit()
        return DiscardResult.already_handled
    if res == ApplyResult.workflow_rejected:
        conn.commit()
        return DiscardResult.already_handled
    conn.commit()
    return DiscardResult.corruption


def reclaim_for_replay(data_dir: Path, item_id: str, worker_id: str) -> dict[str, Any] | None:
    """Transition a pending_recovery item back to claimed for replay.

    Enforces the per-chat single-claimed invariant: if another item for
    the same chat is already claimed, the reclaim is rejected (raises
    ``ReclaimBlocked``).  This mirrors the guard in ``claim_for_update``
    and ``claim_next_any``.

    Returns the item dict if successful, None if the item is no longer
    in pending_recovery or already handled.  Raises ``ReclaimBlocked``
    if the item exists but another item for the same chat is claimed.
    """
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _load_work_item_by_id(conn, item_id)
        if row is None or row["state"] != "pending_recovery":
            conn.execute("COMMIT")
            return None
        chat_id = row["chat_id"]
        # Per-chat single-claimed invariant: reject if another item is claimed.
        has_claimed = conn.execute(
            "SELECT 1 FROM work_items WHERE chat_id = ? AND state = 'claimed' LIMIT 1",
            (chat_id,),
        ).fetchone()
        model = TransportWorkflowModel(
            state="pending_recovery", has_other_claimed_for_chat=bool(has_claimed)
        )
        result = run_transport_event(model, "reclaim_for_replay")
        if not result.allowed:
            conn.execute("COMMIT")
            if result.disposition == TransportDisposition.blocked_replay:
                raise ReclaimBlocked(item_id)
            return None
        new_state = result.new_state  # machine is source of truth
        conn.execute(
            "UPDATE work_items SET state = ?, worker_id = ?, "
            "claimed_at = ?, completed_at = NULL "
            "WHERE id = ?",
            (new_state, worker_id, now, item_id),
        )
        conn.execute("COMMIT")
    except ReclaimBlocked:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    row = conn.execute(
        "SELECT w.*, u.kind, u.payload FROM work_items w "
        "JOIN updates u ON w.update_id = u.update_id WHERE w.id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    r = dict(row)
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
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc)
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
                if result.disposition == TransportDisposition.invalid_transition:
                    log.error(
                        "recover_stale_claims: workflow rejected for item %s: %s",
                        row["id"], result.reason,
                    )
                continue
            new_state = result.new_state  # machine is source of truth
            conn.execute(
                "UPDATE work_items SET state = ?, worker_id = NULL, claimed_at = NULL "
                "WHERE id = ?",
                (new_state, row["id"]),
            )
            requeued += 1
    if requeued:
        conn.commit()
        log.info("Recovered %d stale work items", requeued)
    return requeued


def purge_old(data_dir: Path, older_than_hours: int = 24) -> int:
    """Delete completed/failed work items and their updates older than the threshold."""
    conn = _transport_db(data_dir)
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()

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
    conn.commit()
    if deleted_items or deleted_updates:
        log.info("Purged %d work items and %d updates", deleted_items, deleted_updates)
    return deleted_items
