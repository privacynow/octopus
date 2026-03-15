"""SQLite transport store: connection-per-data_dir and conn-based impl delegation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app import work_queue_sqlite_impl
from app.transport_contract import DiscardResult


class SQLiteTransportStore:
    """SQLite-backed transport store. Each data_dir gets one cached connection to transport.db."""

    def __init__(self) -> None:
        self._connections: dict[Path, sqlite3.Connection] = {}

    def _transport_db(self, data_dir: Path) -> sqlite3.Connection:
        """Return (or create) a WAL-mode SQLite connection for data_dir/transport.db.

        For a brand-new DB (no tables), creates schema and inserts schema_version.
        For an existing DB, validates schema/layout only; does not mutate.
        """
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
                work_queue_sqlite_impl._validate_existing_transport_db(conn)
            else:
                work_queue_sqlite_impl._create_new_transport_db(conn)
        except RuntimeError:
            conn.close()
            raise
        except Exception:
            conn.close()
            raise
        self._connections[data_dir] = conn
        return conn

    def close_transport_db(self, data_dir: Path) -> None:
        """Close the transport database connection for this data_dir."""
        conn = self._connections.pop(data_dir, None)
        if conn:
            conn.close()

    def close_all_transport_db(self) -> None:
        """Close all cached transport DB connections."""
        for data_dir in list(self._connections.keys()):
            self.close_transport_db(data_dir)

    def _reset_transport_db(self, data_dir: Path) -> None:
        """Close and delete the transport database (tests only)."""
        self.close_transport_db(data_dir)
        db_path = data_dir / "transport.db"
        if db_path.exists():
            db_path.unlink()

    def record_and_enqueue(
        self,
        data_dir: Path,
        update_id: int,
        chat_id: int,
        user_id: int,
        kind: str,
        payload: str = "{}",
        *,
        worker_id: str | None = None,
    ) -> tuple[bool, str | None]:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.record_and_enqueue(
            conn, update_id, chat_id, user_id, kind, payload, worker_id=worker_id
        )

    def record_update(
        self,
        data_dir: Path,
        update_id: int,
        chat_id: int,
        user_id: int,
        kind: str,
        payload: str = "{}",
    ) -> bool:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.record_update(
            conn, update_id, chat_id, user_id, kind, payload
        )

    def enqueue_work_item(
        self,
        data_dir: Path,
        chat_id: int,
        update_id: int,
        *,
        worker_id: str | None = None,
    ) -> str:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.enqueue_work_item(
            conn, chat_id, update_id, worker_id=worker_id
        )

    def update_payload(self, data_dir: Path, update_id: int, payload: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.update_payload(conn, update_id, payload)

    def claim_for_update(
        self, data_dir: Path, chat_id: int, update_id: int, worker_id: str
    ) -> dict[str, Any] | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.claim_for_update(
            conn, chat_id, update_id, worker_id
        )

    def claim_next(
        self, data_dir: Path, chat_id: int, worker_id: str
    ) -> dict[str, Any] | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.claim_next(conn, chat_id, worker_id)

    def claim_next_any(self, data_dir: Path, worker_id: str) -> dict[str, Any] | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.claim_next_any(conn, worker_id)

    def complete_work_item(self, data_dir: Path, item_id: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.complete_work_item(conn, item_id)

    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.fail_work_item(conn, item_id, error)

    def has_claimed_for_chat(self, data_dir: Path, chat_id: int) -> bool:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.has_claimed_for_chat(conn, chat_id)

    def has_queued_or_claimed(self, data_dir: Path, chat_id: int) -> bool:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.has_queued_or_claimed(conn, chat_id)

    def get_update_payload(self, data_dir: Path, update_id: int) -> str | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.get_update_payload(conn, update_id)

    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.mark_pending_recovery(conn, item_id)

    def get_pending_recovery_for_update(
        self, data_dir: Path, chat_id: int, update_id: int
    ) -> dict[str, Any] | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.get_pending_recovery_for_update(
            conn, chat_id, update_id
        )

    def get_latest_pending_recovery(
        self, data_dir: Path, chat_id: int
    ) -> dict[str, Any] | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.get_latest_pending_recovery(conn, chat_id)

    def supersede_pending_recovery(self, data_dir: Path, chat_id: int) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.supersede_pending_recovery(conn, chat_id)

    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.discard_recovery(conn, item_id)

    def reclaim_for_replay(
        self, data_dir: Path, item_id: str, worker_id: str
    ) -> dict[str, Any] | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.reclaim_for_replay(conn, item_id, worker_id)

    def recover_stale_claims(
        self,
        data_dir: Path,
        current_worker_id: str,
        max_age_seconds: int = 300,
    ) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.recover_stale_claims(
            conn, current_worker_id, max_age_seconds
        )

    def purge_old(self, data_dir: Path, older_than_hours: int = 24) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.purge_old(conn, older_than_hours)
