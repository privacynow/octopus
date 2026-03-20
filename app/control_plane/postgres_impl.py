"""Postgres-backed control-plane store and conn-based implementation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

from app.control_plane.machine import (
    ControlCommandSnapshot,
    retry_backoff_seconds,
    run_control_command_event,
)
from app.control_plane.models import ControlCommand, ControlReply

_SCHEMA = "bot_runtime"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_or_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@contextmanager
def _cur(conn):
    cur = conn.cursor(row_factory=dict_row)
    try:
        yield cur
    finally:
        cur.close()


@contextmanager
def _write_tx(conn):
    if getattr(conn, "_in_control_plane_tx", False):
        raise RuntimeError("nested control-plane transaction")
    conn._in_control_plane_tx = True
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn._in_control_plane_tx = False


def _row_to_command(row: dict[str, Any]) -> ControlCommand:
    return ControlCommand(
        command_id=row["command_id"],
        capability=row["capability"],
        operation=row["operation"],
        payload_json=row["payload_json"],
        claimed_at=_iso_or_str(row.get("claimed_at")),
        priority=row["priority"],
        correlation_id=row.get("correlation_id") or "",
        authority_ref=row["authority_ref"],
        idempotency_key=row.get("idempotency_key") or "",
        max_retries=row["max_retries"],
    )


def _row_to_reply(row: dict[str, Any]) -> ControlReply | None:
    state = row["state"]
    if state == "completed":
        return ControlReply(
            command_id=row["command_id"],
            status="completed",
            result_json=row.get("result_json"),
        )
    if state in {"failed", "dead_letter"}:
        return ControlReply(
            command_id=row["command_id"],
            status="failed",
            error=row.get("error") or "control-plane command failed",
        )
    return None


def submit(conn, command: ControlCommand) -> str:
    now = _utcnow()
    try:
        with _write_tx(conn), _cur(conn) as cur:
            if command.idempotency_key:
                cur.execute(
                    f"""
                    SELECT command_id
                    FROM {_SCHEMA}.control_plane_commands
                    WHERE capability = %s
                      AND operation = %s
                      AND authority_ref = %s
                      AND idempotency_key = %s
                    """,
                    (
                        command.capability,
                        command.operation,
                        command.authority_ref,
                        command.idempotency_key,
                    ),
                )
                row = cur.fetchone()
                if row is not None:
                    return row["command_id"]
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.control_plane_commands (
                    command_id, capability, operation, payload_json, state,
                    priority, correlation_id, authority_ref, idempotency_key,
                    result_json, error, retry_count, max_retries, created_at
                ) VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, NULL, NULL, 0, %s, %s)
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
    except Exception:
        if not command.idempotency_key:
            raise
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT command_id
                FROM {_SCHEMA}.control_plane_commands
                WHERE capability = %s
                  AND operation = %s
                  AND authority_ref = %s
                  AND idempotency_key = %s
                """,
                (
                    command.capability,
                    command.operation,
                    command.authority_ref,
                    command.idempotency_key,
                ),
            )
            row = cur.fetchone()
        if row is not None:
            return row["command_id"]
        raise
    return command.command_id


def get_reply(conn, command_id: str) -> ControlReply | None:
    with _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT command_id, state, result_json, error
            FROM {_SCHEMA}.control_plane_commands
            WHERE command_id = %s
            """,
            (command_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _row_to_reply(dict(row))


def poll_commands(
    conn,
    *,
    allowed_pairs: set[tuple[str, str]],
    limit: int = 20,
    lease_seconds: float = 30.0,
) -> list[ControlCommand]:
    if not allowed_pairs:
        return []
    now = _utcnow()
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    pair_terms = " OR ".join("(authority_ref = %s AND capability = %s)" for _ in allowed_pairs)
    pair_args: list[str] = []
    for authority_ref, capability in sorted(allowed_pairs):
        pair_args.extend([authority_ref, capability])
    with _write_tx(conn), _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {_SCHEMA}.control_plane_commands
            WHERE state = 'pending'
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
              AND ({pair_terms})
            ORDER BY priority DESC, seq ASC
            FOR UPDATE SKIP LOCKED
            LIMIT %s
            """,
            (now, *pair_args, limit),
        )
        rows = cur.fetchall()
        claimed: list[ControlCommand] = []
        for row in rows:
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.control_plane_commands
                SET state = 'claimed',
                    claimed_at = %s,
                    lease_expires_at = %s,
                    next_attempt_at = NULL
                WHERE command_id = %s
                  AND state = 'pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                RETURNING *
                """,
                (
                    now,
                    lease_expires_at,
                    row["command_id"],
                    now,
                ),
            )
            updated = cur.fetchone()
            if updated is not None:
                claimed.append(_row_to_command(dict(updated)))
    return claimed


def complete(
    conn,
    command_id: str,
    *,
    claimed_at: str,
    result_json: str | None = None,
) -> None:
    now = _utcnow()
    with _write_tx(conn), _cur(conn) as cur:
        cur.execute(
            f"""
            UPDATE {_SCHEMA}.control_plane_commands
            SET state = 'completed',
                result_json = %s,
                error = NULL,
                completed_at = %s,
                claimed_at = NULL,
                lease_expires_at = NULL,
                next_attempt_at = NULL
            WHERE command_id = %s
              AND state = 'claimed'
              AND claimed_at = %s
            """,
            (result_json, now, command_id, claimed_at),
        )


def fail(conn, command_id: str, *, claimed_at: str, error: str) -> None:
    now = _utcnow()
    with _write_tx(conn), _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT state, retry_count, max_retries
            FROM {_SCHEMA}.control_plane_commands
            WHERE command_id = %s
              AND state = 'claimed'
              AND claimed_at = %s
            """,
            (command_id, claimed_at),
        )
        row = cur.fetchone()
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
            backoff_at = now + timedelta(seconds=retry_backoff_seconds(row["retry_count"]))
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.control_plane_commands
                SET state = 'pending',
                    error = %s,
                    retry_count = %s,
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = %s,
                    completed_at = NULL
                WHERE command_id = %s
                  AND state = 'claimed'
                  AND claimed_at = %s
                """,
                (error, retry.retry_count, backoff_at, command_id, claimed_at),
            )
            return
        cur.execute(
            f"""
            UPDATE {_SCHEMA}.control_plane_commands
            SET state = 'dead_letter',
                error = %s,
                claimed_at = NULL,
                lease_expires_at = NULL,
                next_attempt_at = NULL,
                completed_at = %s
            WHERE command_id = %s
              AND state = 'claimed'
              AND claimed_at = %s
            """,
            (error, now, command_id, claimed_at),
        )


def dead_letter(conn, command_id: str, *, claimed_at: str, reason: str) -> None:
    now = _utcnow()
    with _write_tx(conn), _cur(conn) as cur:
        cur.execute(
            f"""
            UPDATE {_SCHEMA}.control_plane_commands
            SET state = 'dead_letter',
                error = %s,
                completed_at = %s,
                claimed_at = NULL,
                lease_expires_at = NULL,
                next_attempt_at = NULL
            WHERE command_id = %s
              AND state = 'claimed'
              AND claimed_at = %s
            """,
            (reason, now, command_id, claimed_at),
        )


def renew_lease(conn, command_id: str, *, claimed_at: str, extension_seconds: float = 30.0) -> bool:
    with _write_tx(conn), _cur(conn) as cur:
        cur.execute(
            f"""
            UPDATE {_SCHEMA}.control_plane_commands
            SET lease_expires_at = %s
            WHERE command_id = %s
              AND state = 'claimed'
              AND claimed_at = %s
            """,
            (_utcnow() + timedelta(seconds=extension_seconds), command_id, claimed_at),
        )
        return cur.rowcount == 1


def reclaim_expired(conn) -> int:
    now = _utcnow()
    reclaimed = 0
    with _write_tx(conn), _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT command_id, retry_count, max_retries
            FROM {_SCHEMA}.control_plane_commands
            WHERE state = 'claimed'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < %s
            FOR UPDATE SKIP LOCKED
            """,
            (now,),
        )
        rows = cur.fetchall()
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
            backoff_at = now + timedelta(seconds=retry_backoff_seconds(row["retry_count"]))
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.control_plane_commands
                SET state = 'pending',
                    retry_count = %s,
                    error = 'lease expired',
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = %s
                WHERE command_id = %s
                  AND state = 'claimed'
                  AND lease_expires_at < %s
                """,
                (decision.retry_count, backoff_at, row["command_id"], now),
            )
            if cur.rowcount == 1:
                reclaimed += 1
    return reclaimed


def reconcile_orphans(conn, *, allowed_pairs: set[tuple[str, str]]) -> int:
    now = _utcnow()
    dead_lettered = 0
    with _write_tx(conn), _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT command_id, authority_ref, capability
            FROM {_SCHEMA}.control_plane_commands
            WHERE state IN ('pending', 'claimed')
            FOR UPDATE SKIP LOCKED
            """
        )
        rows = cur.fetchall()
        for row in rows:
            pair = (row["authority_ref"], row["capability"])
            if pair in allowed_pairs:
                continue
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.control_plane_commands
                SET state = 'dead_letter',
                    error = 'invalid authority/capability pair',
                    completed_at = %s,
                    claimed_at = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = NULL
                WHERE command_id = %s
                  AND state IN ('pending', 'claimed')
                """,
                (now, row["command_id"]),
            )
            if cur.rowcount == 1:
                dead_lettered += 1
    return dead_lettered


class PostgresControlPlaneStore:
    """Postgres-backed control-plane store. Uses connection pool; data_dir ignored."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_min: int = 1,
        pool_max: int = 10,
        connect_timeout: int = 10,
    ) -> None:
        self._database_url = database_url
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._connect_timeout = connect_timeout

    @contextmanager
    def _conn(self):
        from app.db.postgres import get_connection

        with get_connection(
            self._database_url,
            min_size=self._pool_min,
            max_size=self._pool_max,
            connect_timeout=self._connect_timeout,
        ) as conn:
            yield conn

    def close_control_plane_db(self, data_dir: Path) -> None:
        del data_dir

    def close_all_control_plane_db(self) -> None:
        pass

    def debug_connection(self, data_dir: Path):
        del data_dir
        raise NotImplementedError(
            "Postgres control-plane store does not expose a runtime debug connection; "
            "use the conn-based control-plane helpers in tests"
        )

    def reset_db_for_test(self, data_dir: Path) -> None:
        del data_dir

    def validate_backend(self, data_dir: Path) -> None:
        del data_dir
        with self._conn() as conn, _cur(conn) as cur:
            cur.execute("SELECT to_regclass('bot_runtime.control_plane_commands') AS rel")
            row = cur.fetchone()
            if row is None or row["rel"] != "bot_runtime.control_plane_commands":
                raise RuntimeError("Control-plane table bot_runtime.control_plane_commands missing")

    def submit(self, data_dir: Path, command: ControlCommand) -> str:
        del data_dir
        with self._conn() as conn:
            return submit(conn, command)

    def get_reply(self, data_dir: Path, command_id: str) -> ControlReply | None:
        del data_dir
        with self._conn() as conn:
            return get_reply(conn, command_id)

    def poll_commands(
        self,
        data_dir: Path,
        *,
        allowed_pairs: set[tuple[str, str]],
        limit: int = 20,
        lease_seconds: float = 30.0,
    ) -> list[ControlCommand]:
        del data_dir
        with self._conn() as conn:
            return poll_commands(
                conn,
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
        del data_dir
        with self._conn() as conn:
            complete(conn, command_id, claimed_at=claimed_at, result_json=result_json)

    def fail(self, data_dir: Path, command_id: str, *, claimed_at: str, error: str) -> None:
        del data_dir
        with self._conn() as conn:
            fail(conn, command_id, claimed_at=claimed_at, error=error)

    def dead_letter(self, data_dir: Path, command_id: str, *, claimed_at: str, reason: str) -> None:
        del data_dir
        with self._conn() as conn:
            dead_letter(conn, command_id, claimed_at=claimed_at, reason=reason)

    def renew_lease(
        self,
        data_dir: Path,
        command_id: str,
        *,
        claimed_at: str,
        extension_seconds: float = 30.0,
    ) -> bool:
        del data_dir
        with self._conn() as conn:
            return renew_lease(
                conn,
                command_id,
                claimed_at=claimed_at,
                extension_seconds=extension_seconds,
            )

    def reclaim_expired(self, data_dir: Path) -> int:
        del data_dir
        with self._conn() as conn:
            return reclaim_expired(conn)

    def reconcile_orphans(
        self,
        data_dir: Path,
        *,
        allowed_pairs: set[tuple[str, str]],
    ) -> int:
        del data_dir
        with self._conn() as conn:
            return reconcile_orphans(conn, allowed_pairs=allowed_pairs)
