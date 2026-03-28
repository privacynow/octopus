"""SQLite transport store: connection-per-data_dir and conn-based impl delegation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from octopus_sdk.work_queue import QueueSnapshot, WorkerHeartbeat
from app import work_queue_sqlite_impl
from octopus_sdk.work_queue import (
    CancelRequestResult,
    DiscardResult,
    UsageRecord,
    UserAccessRecord,
    WorkItemRecord,
    coerce_usage_records,
    coerce_user_access_records,
    coerce_work_item_record,
    coerce_work_item_records,
)


class SQLiteTransportStore:
    """SQLite-backed transport store. Each data_dir gets one cached connection to transport.db."""

    def __init__(self) -> None:
        self._connections: dict[Path, sqlite3.Connection] = {}

    def _transport_db(self, data_dir: Path) -> sqlite3.Connection:
        """Return (or create) a WAL-mode SQLite connection for data_dir/transport.db.

        For a brand-new DB (no tables), creates schema and inserts schema_version.
        For an existing DB, runs supported in-place migrations, then validates
        the supported schema/layout.
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
                work_queue_sqlite_impl._ensure_schema_version(conn)
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

    def debug_connection(self, data_dir: Path) -> sqlite3.Connection:
        """Return the SQLite transport connection for tests/diagnostics."""
        return self._transport_db(data_dir)

    def reset_db_for_test(self, data_dir: Path) -> None:
        """Close and delete the transport database (tests only)."""
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
        return work_queue_sqlite_impl.record_and_enqueue(
            conn, event_id, conversation_key, actor_key, kind, payload, worker_id=worker_id
        )

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
            return work_queue_sqlite_impl.record_and_admit_message(
                conn, event_id, conversation_key, actor_key, kind, payload,
            )
        except work_queue_sqlite_impl._DuplicateUpdate:
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
        return work_queue_sqlite_impl.record_update(
            conn, event_id, conversation_key, actor_key, kind, payload
        )

    def enqueue_work_item(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        *,
        worker_id: str | None = None,
    ) -> str:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.enqueue_work_item(
            conn, conversation_key, event_id, worker_id=worker_id
        )

    def update_payload(self, data_dir: Path, event_id: str, payload: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.update_payload(conn, event_id, payload)

    def claim_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str, worker_id: str
    ) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(
            work_queue_sqlite_impl.claim_for_update(conn, conversation_key, event_id, worker_id)
        )

    def claim_next(
        self, data_dir: Path, conversation_key: str, worker_id: str
    ) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(work_queue_sqlite_impl.claim_next(conn, conversation_key, worker_id))

    def claim_next_any(self, data_dir: Path, worker_id: str) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(work_queue_sqlite_impl.claim_next_any(conn, worker_id))

    def list_incomplete_work_items(self, data_dir: Path) -> list[WorkItemRecord]:
        conn = self._transport_db(data_dir)
        return coerce_work_item_records(work_queue_sqlite_impl.list_incomplete_work_items(conn))

    def recover_after_crash(
        self,
        data_dir: Path,
        *,
        lease_ttl_seconds: int = 300,
    ) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.recover_after_crash(conn, lease_ttl_seconds)

    def complete_work_item(self, data_dir: Path, item_id: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.complete_work_item(conn, item_id)

    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.fail_work_item(conn, item_id, error)

    def cancel_queued_fresh_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.cancel_queued_fresh_for_chat(conn, conversation_key)

    def request_cancel(
        self,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        *,
        cancel_request_event_id: str = "",
    ) -> CancelRequestResult:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.request_cancel(
            conn,
            conversation_key,
            actor_key,
            cancel_request_event_id=cancel_request_event_id,
        )

    def is_cancel_requested(self, data_dir: Path, item_id: str) -> bool:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.is_cancel_requested(conn, item_id)

    def has_claimed_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.has_claimed_for_chat(conn, conversation_key)

    def has_queued_or_claimed(self, data_dir: Path, conversation_key: str) -> bool:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.has_queued_or_claimed(conn, conversation_key)

    def get_update_payload(self, data_dir: Path, event_id: str) -> str | None:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.get_update_payload(conn, event_id)

    def get_work_items_for_chat(self, data_dir: Path, conversation_key: str) -> list[WorkItemRecord]:
        conn = self._transport_db(data_dir)
        return coerce_work_item_records(work_queue_sqlite_impl.get_work_items_for_chat(conn, conversation_key))

    def get_queue_snapshot(self, data_dir: Path) -> QueueSnapshot:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.get_queue_snapshot(conn)

    def upsert_worker_heartbeat(self, data_dir: Path, heartbeat: WorkerHeartbeat) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.upsert_worker_heartbeat(conn, heartbeat)

    def clear_worker_heartbeat(self, data_dir: Path, worker_id: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.clear_worker_heartbeat(conn, worker_id)

    def list_worker_heartbeats(self, data_dir: Path) -> list[WorkerHeartbeat]:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.list_worker_heartbeats(conn)

    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.mark_pending_recovery(conn, item_id)

    def get_pending_recovery_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str
    ) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(
            work_queue_sqlite_impl.get_pending_recovery_for_update(conn, conversation_key, event_id)
        )

    def get_latest_pending_recovery(
        self, data_dir: Path, conversation_key: str
    ) -> WorkItemRecord | None:
        conn = self._transport_db(data_dir)
        return coerce_work_item_record(work_queue_sqlite_impl.get_latest_pending_recovery(conn, conversation_key))

    def supersede_pending_recovery(self, data_dir: Path, conversation_key: str) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.supersede_pending_recovery(conn, conversation_key)

    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.discard_recovery(conn, item_id)

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
            work_queue_sqlite_impl.reclaim_for_replay(
                conn,
                item_id,
                worker_id,
                ignore_claimed_item_id=ignore_claimed_item_id,
            )
        )

    def recover_stale_claims(
        self,
        data_dir: Path,
        *,
        lease_ttl_seconds: int = 300,
    ) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.recover_stale_claims(conn, lease_ttl_seconds)

    def purge_old(self, data_dir: Path, *, older_than_seconds: int = 7 * 24 * 3600) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.purge_old(conn, older_than_seconds)

    def purge_old_usage(self, data_dir: Path, *, older_than_seconds: int = 30 * 24 * 3600) -> int:
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.purge_old_usage(conn, older_than_seconds)

    def get_user_access(self, data_dir: Path, actor_key: str) -> str | None:
        if data_dir in self._connections:
            return work_queue_sqlite_impl.get_user_access_override(
                self._connections[data_dir], actor_key
            )
        if not (data_dir / "transport.db").exists():
            return None
        conn = self._transport_db(data_dir)
        return work_queue_sqlite_impl.get_user_access_override(conn, actor_key)

    def set_user_access(
        self,
        data_dir: Path,
        actor_key: str,
        access: str,
        reason: str = "",
        granted_by: str = "",
    ) -> None:
        conn = self._transport_db(data_dir)
        work_queue_sqlite_impl.set_user_access(conn, actor_key, access, reason, granted_by)

    def list_user_access(self, data_dir: Path) -> list[UserAccessRecord]:
        conn = self._transport_db(data_dir)
        return coerce_user_access_records(work_queue_sqlite_impl.list_user_access(conn))

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
        work_queue_sqlite_impl.record_usage(
            conn,
            conversation_key=conversation_key,
            work_item_id=work_item_id,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )

    def get_usage_since(
        self,
        data_dir: Path,
        *,
        since_epoch: float,
    ) -> list[UsageRecord]:
        conn = self._transport_db(data_dir)
        return coerce_usage_records(work_queue_sqlite_impl.get_usage_since(conn, since_epoch=since_epoch))
