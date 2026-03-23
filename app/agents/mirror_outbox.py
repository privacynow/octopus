"""Bot-local retry outbox for failed mirrored registry operations."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS mirror_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    authority_ref TEXT NOT NULL,
    operation TEXT NOT NULL,
    conversation_id TEXT NOT NULL DEFAULT '',
    bot_key TEXT NOT NULL DEFAULT '',
    origin_channel TEXT NOT NULL DEFAULT '',
    external_conversation_ref TEXT NOT NULL DEFAULT '',
    event_id TEXT NOT NULL DEFAULT '',
    created_at_ts TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    inserted_at REAL NOT NULL
);
"""

_MAX_RETRIES = 10
_MAX_AGE_SECONDS = 86400 * 7  # 7 days
_MAX_ROWS = 10000


class MirrorOutbox:
    def __init__(self, data_dir: Path) -> None:
        self._db_path = data_dir / "agent" / "mirror_outbox.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_OUTBOX_SCHEMA)

    def enqueue(
        self,
        authority_ref: str,
        operation: str,
        *,
        conversation_id: str = "",
        bot_key: str = "",
        origin_channel: str = "",
        external_conversation_ref: str = "",
        event_id: str = "",
        created_at_ts: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mirror_outbox
                   (authority_ref, operation, conversation_id, bot_key, origin_channel,
                    external_conversation_ref, event_id, created_at_ts,
                    payload_json, retry_count, next_attempt_at, last_error, inserted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, '', ?)""",
                (
                    authority_ref,
                    operation,
                    conversation_id,
                    bot_key,
                    origin_channel,
                    external_conversation_ref,
                    event_id,
                    created_at_ts,
                    json.dumps(payload or {}),
                    now,
                    now,
                ),
            )

    def pending(self, limit: int = 50) -> list[dict[str, Any]]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mirror_outbox WHERE next_attempt_at <= ? AND retry_count < ? ORDER BY id LIMIT ?",
                (now, _MAX_RETRIES, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_success(self, row_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM mirror_outbox WHERE id = ?", (row_id,))

    def mark_failure(self, row_id: int, error: str | Exception) -> None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT retry_count FROM mirror_outbox WHERE id = ?", (row_id,)
            ).fetchone()
            if row:
                retry = row["retry_count"] + 1
                backoff = min(300, 2**retry)  # exponential, cap 5 min
                conn.execute(
                    "UPDATE mirror_outbox SET retry_count=?, next_attempt_at=?, last_error=? WHERE id=?",
                    (retry, now + backoff, str(error)[:500], row_id),
                )

    def purge_old(self) -> None:
        cutoff = time.time() - _MAX_AGE_SECONDS
        with self._connect() as conn:
            conn.execute("DELETE FROM mirror_outbox WHERE inserted_at < ?", (cutoff,))
            count = conn.execute("SELECT COUNT(*) FROM mirror_outbox").fetchone()[0]
            if count > _MAX_ROWS:
                conn.execute(
                    "DELETE FROM mirror_outbox WHERE id IN (SELECT id FROM mirror_outbox ORDER BY id LIMIT ?)",
                    (count - _MAX_ROWS,),
                )

    def backlog_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM mirror_outbox").fetchone()[0]
