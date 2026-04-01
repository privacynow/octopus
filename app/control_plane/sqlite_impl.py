"""SQLite-backed control-plane store and conn-based implementation."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.control_plane.machine import (
    ControlCommandSnapshot,
    retry_backoff_seconds,
    run_control_command_event,
)
from app.control_plane.models import ControlCommand, ControlReply
from octopus_sdk.time_utils import utc_now, utc_now_iso

_SCHEMA_VERSION = 1
_DB_NAME = "control_plane.db"
_UNSUPPORTED_SCHEMA_MSG = "Unsupported control-plane DB schema/layout for this build"
_EXPECTED_TABLES = ("control_plane_commands", "meta")
_EXPECTED_COLUMNS: dict[str, set[str]] = {
    "control_plane_commands": {
        "seq",
        "command_id",
        "capability",
        "operation",
        "payload_json",
        "state",
        "priority",
        "correlation_id",
        "authority_ref",
        "idempotency_key",
        "result_json",
        "error",
        "retry_count",
        "max_retries",
        "created_at",
        "claimed_at",
        "completed_at",
        "lease_expires_at",
        "next_attempt_at",
    },
    "meta": {"key", "value"},
}

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS control_plane_commands (
    seq               INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id        TEXT NOT NULL UNIQUE,
    capability        TEXT NOT NULL,
    operation         TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'pending',
    priority          INTEGER NOT NULL DEFAULT 0,
    correlation_id    TEXT NOT NULL DEFAULT '',
    authority_ref     TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL DEFAULT '',
    result_json       TEXT,
    error             TEXT,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    max_retries       INTEGER NOT NULL DEFAULT 3,
    created_at        TEXT NOT NULL,
    claimed_at        TEXT,
    completed_at      TEXT,
    lease_expires_at  TEXT,
    next_attempt_at   TEXT,
    CHECK (state IN ('pending', 'claimed', 'completed', 'failed', 'dead_letter')),
    CHECK (authority_ref != '')
);
CREATE INDEX IF NOT EXISTS idx_cp_state
    ON control_plane_commands (state, next_attempt_at, priority DESC, seq);
CREATE INDEX IF NOT EXISTS idx_cp_correlation
    ON control_plane_commands (correlation_id)
    WHERE correlation_id != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_cp_idempotency
    ON control_plane_commands (capability, operation, authority_ref, idempotency_key)
    WHERE idempotency_key != '';

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utcnow() -> datetime:
    return utc_now()


def _expiry_iso(seconds: float) -> str:
    return (_utcnow() + timedelta(seconds=seconds)).isoformat()


def _is_due(value: str | None, *, now_iso: str) -> bool:
    return value is None or value == "" or value <= now_iso


def _row_to_command(row: sqlite3.Row | dict[str, Any]) -> ControlCommand:
    return ControlCommand(
        command_id=row["command_id"],
        capability=row["capability"],
        operation=row["operation"],
        payload_json=row["payload_json"],
        claimed_at=row["claimed_at"] or "",
        priority=row["priority"],
        correlation_id=row["correlation_id"] or "",
        authority_ref=row["authority_ref"],
        idempotency_key=row["idempotency_key"] or "",
        max_retries=row["max_retries"],
    )


def _row_to_reply(row: sqlite3.Row | dict[str, Any]) -> ControlReply | None:
    state = row["state"]
    if state == "completed":
        return ControlReply(
            command_id=row["command_id"],
            status="completed",
            result_json=row["result_json"],
        )
    if state in {"failed", "dead_letter"}:
        return ControlReply(
            command_id=row["command_id"],
            status="failed",
            error=row["error"] or "control-plane command failed",
        )
    return None


def _create_new_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_CREATE_SQL)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.commit()


def _validate_existing_db(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    if any(table not in tables for table in _EXPECTED_TABLES):
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    for table in _EXPECTED_TABLES:
        infos = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {row["name"] if hasattr(row, "keys") else row[1] for row in infos}
        if _EXPECTED_COLUMNS[table] - cols:
            raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)
    if int(row[0]) != _SCHEMA_VERSION:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MSG)


@contextmanager
def _write_tx(conn: sqlite3.Connection):
    if conn.in_transaction:
        raise RuntimeError("nested control-plane transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def submit(conn: sqlite3.Connection, command: ControlCommand) -> str:
    now = utc_now_iso()
    try:
        with _write_tx(conn):
            if command.idempotency_key:
                row = conn.execute(
                    """
                    SELECT command_id
                    FROM control_plane_commands
                    WHERE capability = ?
                      AND operation = ?
                      AND authority_ref = ?
                      AND idempotency_key = ?
                    """,
                    (
                        command.capability,
                        command.operation,
                        command.authority_ref,
                        command.idempotency_key,
                    ),
                ).fetchone()
                if row is not None:
                    return row["command_id"]
            conn.execute(
                """
                INSERT INTO control_plane_commands (
                    command_id, capability, operation, payload_json, state,
                    priority, correlation_id, authority_ref, idempotency_key,
                    result_json, error, retry_count, max_retries, created_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, NULL, NULL, 0, ?, ?)
                """,
                (
                    command.command_id,
                    command.capability,
                    command.operation,
                    command.payload_json,
                    command.priority,
                    command.correlation_id,
                    command.authority_ref,
                    command.idempotency_key,
                    command.max_retries,
                    now,
                ),
            )
    except sqlite3.IntegrityError:
        if not command.idempotency_key:
            raise
        row = conn.execute(
            """
            SELECT command_id
            FROM control_plane_commands
            WHERE capability = ?
              AND operation = ?
              AND authority_ref = ?
              AND idempotency_key = ?
            """,
            (
                command.capability,
                command.operation,
                command.authority_ref,
                command.idempotency_key,
            ),
        ).fetchone()
        if row is not None:
            return row["command_id"]
        raise
    return command.command_id


def get_reply(conn: sqlite3.Connection, command_id: str) -> ControlReply | None:
    row = conn.execute(
        """
        SELECT command_id, state, result_json, error
        FROM control_plane_commands
        WHERE command_id = ?
        """,
        (command_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_reply(row)


def poll_commands(
    conn: sqlite3.Connection,
    *,
    allowed_pairs: set[tuple[str, str]],
    limit: int = 20,
    lease_seconds: float = 30.0,
) -> list[ControlCommand]:
    if not allowed_pairs:
        return []
    now_iso = utc_now_iso()
    lease_expires_at = _expiry_iso(lease_seconds)
    pair_terms = " OR ".join("(authority_ref = ? AND capability = ?)" for _ in allowed_pairs)
    pair_args: list[str] = []
    for authority_ref, capability in sorted(allowed_pairs):
        pair_args.extend([authority_ref, capability])
    claimed: list[ControlCommand] = []
    with _write_tx(conn):
        rows = conn.execute(
            f"""
            SELECT *
            FROM control_plane_commands
            WHERE state = 'pending'
              AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
              AND ({pair_terms})
            ORDER BY priority DESC, seq ASC
            LIMIT ?
            """,
            (now_iso, *pair_args, limit),
        ).fetchall()
        for row in rows:
            cur = conn.execute(
                """
                UPDATE control_plane_commands
                SET state = 'claimed',
                    claimed_at = ?,
                    lease_expires_at = ?,
                    next_attempt_at = NULL
                WHERE command_id = ?
                  AND state = 'pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                """,
                (
                    now_iso,
                    lease_expires_at,
                    row["command_id"],
                    now_iso,
                ),
            )
            if cur.rowcount != 1:
                continue
            claimed_row = conn.execute(
                "SELECT * FROM control_plane_commands WHERE command_id = ?",
                (row["command_id"],),
            ).fetchone()
            if claimed_row is not None:
                claimed.append(_row_to_command(claimed_row))
    return claimed


def complete(
    conn: sqlite3.Connection,
    command_id: str,
    *,
    claimed_at: str,
    result_json: str | None = None,
) -> None:
    now_iso = utc_now_iso()
    with _write_tx(conn):
        conn.execute(
            """
            UPDATE control_plane_commands
            SET state = 'completed',
                result_json = ?,
                error = NULL,
                completed_at = ?,
                claimed_at = NULL,
                lease_expires_at = NULL,
                next_attempt_at = NULL
            WHERE command_id = ?
              AND state = 'claimed'
              AND claimed_at = ?
            """,
            (result_json, now_iso, command_id, claimed_at),
        )


def fail(conn: sqlite3.Connection, command_id: str, *, claimed_at: str, error: str) -> None:
    now = _utcnow()
    now_iso = now.isoformat()
    with _write_tx(conn):
        row = conn.execute(
            """
            SELECT state, retry_count, max_retries
            FROM control_plane_commands
            WHERE command_id = ?
              AND state = 'claimed'
              AND claimed_at = ?
            """,
            (command_id, claimed_at),
        ).fetchone()
        if row is None:
            return
        record_failure = run_control_command_event(
            ControlCommandSnapshot(
                state="claimed",
                retry_count=row["retry_count"],
                max_retries=row["max_retries"],
            ),
            "record_failure",
        )
        if not record_failure.ok:
            raise RuntimeError(record_failure.reason)
        retry = run_control_command_event(
            ControlCommandSnapshot(
                state="failed",
                retry_count=row["retry_count"],
                max_retries=row["max_retries"],
            ),
            "retry",
        )
        if not retry.ok:
            raise RuntimeError(retry.reason)
        if retry.new_state == "pending":
            backoff_iso = (now + timedelta(seconds=retry_backoff_seconds(row["retry_count"]))).isoformat()
            conn.execute(
                """
                UPDATE control_plane_commands
                SET state = 'pending',
                    error = ?,
                    retry_count = ?,
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = ?,
                    completed_at = NULL
                WHERE command_id = ?
                  AND state = 'claimed'
                  AND claimed_at = ?
                """,
                (error, retry.retry_count, backoff_iso, command_id, claimed_at),
            )
            return
        conn.execute(
            """
            UPDATE control_plane_commands
            SET state = 'dead_letter',
                error = ?,
                claimed_at = NULL,
                lease_expires_at = NULL,
                next_attempt_at = NULL,
                completed_at = ?
            WHERE command_id = ?
              AND state = 'claimed'
              AND claimed_at = ?
            """,
            (error, now_iso, command_id, claimed_at),
        )


def dead_letter(conn: sqlite3.Connection, command_id: str, *, claimed_at: str, reason: str) -> None:
    now_iso = utc_now_iso()
    with _write_tx(conn):
        conn.execute(
            """
            UPDATE control_plane_commands
            SET state = 'dead_letter',
                error = ?,
                completed_at = ?,
                claimed_at = NULL,
                lease_expires_at = NULL,
                next_attempt_at = NULL
            WHERE command_id = ?
              AND state = 'claimed'
              AND claimed_at = ?
            """,
            (reason, now_iso, command_id, claimed_at),
        )


def renew_lease(
    conn: sqlite3.Connection,
    command_id: str,
    *,
    claimed_at: str,
    extension_seconds: float = 30.0,
) -> bool:
    with _write_tx(conn):
        cur = conn.execute(
            """
            UPDATE control_plane_commands
            SET lease_expires_at = ?
            WHERE command_id = ?
              AND state = 'claimed'
              AND claimed_at = ?
            """,
            (_expiry_iso(extension_seconds), command_id, claimed_at),
        )
        return cur.rowcount == 1


def reclaim_expired(conn: sqlite3.Connection) -> int:
    now = _utcnow()
    now_iso = now.isoformat()
    reclaimed = 0
    with _write_tx(conn):
        rows = conn.execute(
            """
            SELECT command_id, retry_count, max_retries, lease_expires_at
            FROM control_plane_commands
            WHERE state = 'claimed'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < ?
            """,
            (now_iso,),
        ).fetchall()
        for row in rows:
            decision = run_control_command_event(
                ControlCommandSnapshot(
                    state="claimed",
                    retry_count=row["retry_count"],
                    max_retries=row["max_retries"],
                    lease_expired=True,
                ),
                "reclaim_expired",
            )
            if not decision.ok:
                continue
            backoff_iso = (now + timedelta(seconds=retry_backoff_seconds(row["retry_count"]))).isoformat()
            cur = conn.execute(
                """
                UPDATE control_plane_commands
                SET state = 'pending',
                    retry_count = ?,
                    error = 'lease expired',
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = ?
                WHERE command_id = ?
                  AND state = 'claimed'
                  AND lease_expires_at < ?
                """,
                (
                    decision.retry_count,
                    backoff_iso,
                    row["command_id"],
                    now_iso,
                ),
            )
            if cur.rowcount == 1:
                reclaimed += 1
    return reclaimed


def purge_old_commands(conn: sqlite3.Connection, older_than_hours: int = 72) -> int:
    cutoff_iso = (_utcnow() - timedelta(hours=older_than_hours)).isoformat()
    with _write_tx(conn):
        cursor = conn.execute(
            """
            DELETE FROM control_plane_commands
            WHERE state IN ('completed', 'dead_letter')
              AND completed_at IS NOT NULL
              AND completed_at < ?
            """,
            (cutoff_iso,),
        )
        return cursor.rowcount


def reconcile_orphans(conn: sqlite3.Connection, *, allowed_pairs: set[tuple[str, str]]) -> int:
    now_iso = utc_now_iso()
    dead_lettered = 0
    with _write_tx(conn):
        rows = conn.execute(
            """
            SELECT command_id, authority_ref, capability
            FROM control_plane_commands
            WHERE state IN ('pending', 'claimed')
            """
        ).fetchall()
        for row in rows:
            pair = (row["authority_ref"], row["capability"])
            if pair in allowed_pairs:
                continue
            cur = conn.execute(
                """
                UPDATE control_plane_commands
                SET state = 'dead_letter',
                    error = 'invalid authority/capability pair',
                    completed_at = ?,
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = NULL
                WHERE command_id = ?
                  AND state IN ('pending', 'claimed')
                """,
                (now_iso, row["command_id"]),
            )
            if cur.rowcount == 1:
                dead_lettered += 1
    return dead_lettered


class SQLiteControlPlaneStore:
    """SQLite-backed control-plane store. Each data_dir gets one cached connection."""

    def __init__(self) -> None:
        self._connections: dict[Path, sqlite3.Connection] = {}

    def _control_plane_db(self, data_dir: Path) -> sqlite3.Connection:
        if data_dir in self._connections:
            return self._connections[data_dir]
        db_path = data_dir / _DB_NAME
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
                _validate_existing_db(conn)
            else:
                _create_new_db(conn)
        except Exception:
            conn.close()
            raise
        self._connections[data_dir] = conn
        return conn

    def close_control_plane_db(self, data_dir: Path) -> None:
        conn = self._connections.pop(data_dir, None)
        if conn:
            conn.close()

    def close_all_control_plane_db(self) -> None:
        for data_dir in list(self._connections.keys()):
            self.close_control_plane_db(data_dir)

    def debug_connection(self, data_dir: Path) -> sqlite3.Connection:
        return self._control_plane_db(data_dir)

    def reset_db_for_test(self, data_dir: Path) -> None:
        self.close_control_plane_db(data_dir)
        db_path = data_dir / _DB_NAME
        if db_path.exists():
            db_path.unlink()

    def validate_backend(self, data_dir: Path) -> None:
        self._control_plane_db(data_dir)

    def submit(self, data_dir: Path, command: ControlCommand) -> str:
        return submit(self._control_plane_db(data_dir), command)

    def get_reply(self, data_dir: Path, command_id: str) -> ControlReply | None:
        return get_reply(self._control_plane_db(data_dir), command_id)

    def poll_commands(
        self,
        data_dir: Path,
        *,
        allowed_pairs: set[tuple[str, str]],
        limit: int = 20,
        lease_seconds: float = 30.0,
    ) -> list[ControlCommand]:
        return poll_commands(
            self._control_plane_db(data_dir),
            allowed_pairs=allowed_pairs,
            limit=limit,
            lease_seconds=lease_seconds,
        )

    def complete(
        self,
        data_dir: Path,
        command_id: str,
        *,
        claimed_at: str,
        result_json: str | None = None,
    ) -> None:
        complete(
            self._control_plane_db(data_dir),
            command_id,
            claimed_at=claimed_at,
            result_json=result_json,
        )

    def fail(self, data_dir: Path, command_id: str, *, claimed_at: str, error: str) -> None:
        fail(self._control_plane_db(data_dir), command_id, claimed_at=claimed_at, error=error)

    def dead_letter(self, data_dir: Path, command_id: str, *, claimed_at: str, reason: str) -> None:
        dead_letter(
            self._control_plane_db(data_dir),
            command_id,
            claimed_at=claimed_at,
            reason=reason,
        )

    def renew_lease(
        self,
        data_dir: Path,
        command_id: str,
        *,
        claimed_at: str,
        extension_seconds: float = 30.0,
    ) -> bool:
        return renew_lease(
            self._control_plane_db(data_dir),
            command_id,
            claimed_at=claimed_at,
            extension_seconds=extension_seconds,
        )

    def reclaim_expired(self, data_dir: Path) -> int:
        return reclaim_expired(self._control_plane_db(data_dir))

    def purge_old_commands(self, data_dir: Path, older_than_hours: int = 72) -> int:
        return purge_old_commands(
            self._control_plane_db(data_dir),
            older_than_hours=older_than_hours,
        )

    def reconcile_orphans(
        self,
        data_dir: Path,
        *,
        allowed_pairs: set[tuple[str, str]],
    ) -> int:
        return reconcile_orphans(self._control_plane_db(data_dir), allowed_pairs=allowed_pairs)
