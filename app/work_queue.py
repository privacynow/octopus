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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

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
    created_at  TEXT    NOT NULL
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
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            conn.commit()
        else:
            stored = int(row["value"])
            if stored > _SCHEMA_VERSION:
                raise RuntimeError(
                    f"Transport DB schema version {stored} is newer than supported "
                    f"version {_SCHEMA_VERSION}. Upgrade the bot."
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


def _reset_transport_db(data_dir: Path) -> None:
    """Close and delete the transport database (tests only)."""
    close_transport_db(data_dir)
    db_path = data_dir / "transport.db"
    if db_path.exists():
        db_path.unlink()


# ---------------------------------------------------------------------------
# Update journal
# ---------------------------------------------------------------------------

def record_update(
    data_dir: Path,
    update_id: int,
    chat_id: int,
    user_id: int,
    kind: str,
    payload: str = "{}",
) -> bool:
    """Record an inbound Telegram update.  Returns True if new, False if duplicate."""
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


def update_payload(data_dir: Path, update_id: int, payload: str) -> None:
    """Update the stored payload for an already-recorded update."""
    conn = _transport_db(data_dir)
    conn.execute(
        "UPDATE updates SET payload = ? WHERE update_id = ?",
        (payload, update_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Work items
# ---------------------------------------------------------------------------

def enqueue_work_item(data_dir: Path, chat_id: int, update_id: int) -> str:
    """Create a queued work item for the given update.  Returns the item id."""
    conn = _transport_db(data_dir)
    item_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, created_at) "
        "VALUES (?, ?, ?, 'queued', ?)",
        (item_id, chat_id, update_id, now),
    )
    conn.commit()
    return item_id


def claim_next(data_dir: Path, chat_id: int, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the next queued work item for a chat.

    Returns None if no claimable item exists (either nothing queued or
    another item for this chat is already claimed).
    """
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
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
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = ?, claimed_at = ? "
            "WHERE id = ?",
            (worker_id, now, item_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    item = conn.execute(
        "SELECT * FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    return dict(item) if item else None


def claim_next_any(data_dir: Path, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the next queued work item across all chats.

    Only claims items in chats that have no currently-claimed item
    (per-chat serialization).  Returns None if nothing is claimable.
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
        item_id = row["id"]
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = ?, claimed_at = ? "
            "WHERE id = ?",
            (worker_id, now, item_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    item = conn.execute(
        "SELECT w.*, u.kind, u.payload FROM work_items w "
        "JOIN updates u ON w.update_id = u.update_id WHERE w.id = ?",
        (item_id,),
    ).fetchone()
    return dict(item) if item else None


def complete_work_item(
    data_dir: Path, item_id: str, state: str = "done", error: str | None = None,
) -> None:
    """Mark a work item as done or failed."""
    conn = _transport_db(data_dir)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE work_items SET state = ?, completed_at = ?, error = ? WHERE id = ?",
        (state, now, error, item_id),
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
        "SELECT id, worker_id, claimed_at FROM work_items WHERE state = 'claimed'"
    ).fetchall()
    requeued = 0
    for row in rows:
        stale = False
        if row["worker_id"] != current_worker_id:
            stale = True
        elif row["claimed_at"]:
            claimed = datetime.fromisoformat(row["claimed_at"])
            if (now - claimed).total_seconds() > max_age_seconds:
                stale = True
        if stale:
            conn.execute(
                "UPDATE work_items SET state = 'queued', worker_id = NULL, claimed_at = NULL "
                "WHERE id = ?",
                (row["id"],),
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
        "DELETE FROM work_items WHERE state IN ('done', 'failed') AND created_at < ?",
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
