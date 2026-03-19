"""Postgres transport store wrapper. Conn-based API lives in work_queue_postgres_impl."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app import work_queue_postgres_impl
from app.runtime_health import QueueSnapshot, WorkerHeartbeat
from app.workflows.recovery.transport_contract import CancelRequestResult, DiscardResult


class PostgresTransportStore:
    """Transport store backed by Postgres. Uses connection pool; data_dir ignored."""

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
        with self._conn() as conn:
            return work_queue_postgres_impl.record_and_enqueue(
                conn, event_id, conversation_key, actor_key, kind, payload, worker_id=worker_id,
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
        with self._conn() as conn:
            return work_queue_postgres_impl.record_and_admit_message(
                conn, event_id, conversation_key, actor_key, kind, payload,
            )

    def record_update(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> bool:
        with self._conn() as conn:
            return work_queue_postgres_impl.record_update(
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
        with self._conn() as conn:
            return work_queue_postgres_impl.enqueue_work_item(
                conn, conversation_key, event_id, worker_id=worker_id
            )

    def update_payload(self, data_dir: Path, event_id: str, payload: str) -> None:
        with self._conn() as conn:
            work_queue_postgres_impl.update_payload(conn, event_id, payload)

    def claim_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str, worker_id: str,
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.claim_for_update(conn, conversation_key, event_id, worker_id)

    def claim_next(self, data_dir: Path, conversation_key: str, worker_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.claim_next(conn, conversation_key, worker_id)

    def claim_next_any(self, data_dir: Path, worker_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.claim_next_any(conn, worker_id)

    def complete_work_item(self, data_dir: Path, item_id: str) -> None:
        with self._conn() as conn:
            work_queue_postgres_impl.complete_work_item(conn, item_id)

    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None:
        with self._conn() as conn:
            work_queue_postgres_impl.fail_work_item(conn, item_id, error)

    def cancel_queued_fresh_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        with self._conn() as conn:
            return work_queue_postgres_impl.cancel_queued_fresh_for_chat(conn, conversation_key)

    def request_cancel(
        self,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        *,
        cancel_request_event_id: str = "",
    ) -> CancelRequestResult:
        with self._conn() as conn:
            return work_queue_postgres_impl.request_cancel(
                conn,
                conversation_key,
                actor_key,
                cancel_request_event_id=cancel_request_event_id,
            )

    def is_cancel_requested(self, data_dir: Path, item_id: str) -> bool:
        with self._conn() as conn:
            return work_queue_postgres_impl.is_cancel_requested(conn, item_id)

    def has_claimed_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        with self._conn() as conn:
            return work_queue_postgres_impl.has_claimed_for_chat(conn, conversation_key)

    def has_queued_or_claimed(self, data_dir: Path, conversation_key: str) -> bool:
        with self._conn() as conn:
            return work_queue_postgres_impl.has_queued_or_claimed(conn, conversation_key)

    def get_update_payload(self, data_dir: Path, event_id: str) -> str | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.get_update_payload(conn, event_id)

    def get_work_items_for_chat(self, data_dir: Path, conversation_key: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return work_queue_postgres_impl.get_work_items_for_chat(conn, conversation_key)

    def get_queue_snapshot(self, data_dir: Path) -> QueueSnapshot:
        with self._conn() as conn:
            return work_queue_postgres_impl.get_queue_snapshot(conn)

    def upsert_worker_heartbeat(self, data_dir: Path, heartbeat: WorkerHeartbeat) -> None:
        with self._conn() as conn:
            work_queue_postgres_impl.upsert_worker_heartbeat(conn, heartbeat)

    def clear_worker_heartbeat(self, data_dir: Path, worker_id: str) -> None:
        with self._conn() as conn:
            work_queue_postgres_impl.clear_worker_heartbeat(conn, worker_id)

    def list_worker_heartbeats(self, data_dir: Path) -> list[WorkerHeartbeat]:
        with self._conn() as conn:
            return work_queue_postgres_impl.list_worker_heartbeats(conn)

    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None:
        with self._conn() as conn:
            work_queue_postgres_impl.mark_pending_recovery(conn, item_id)

    def get_pending_recovery_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str,
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.get_pending_recovery_for_update(
                conn, conversation_key, event_id
            )

    def get_latest_pending_recovery(self, data_dir: Path, conversation_key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.get_latest_pending_recovery(conn, conversation_key)

    def supersede_pending_recovery(self, data_dir: Path, conversation_key: str) -> int:
        with self._conn() as conn:
            return work_queue_postgres_impl.supersede_pending_recovery(conn, conversation_key)

    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult:
        with self._conn() as conn:
            return work_queue_postgres_impl.discard_recovery(conn, item_id)

    def reclaim_for_replay(
        self,
        data_dir: Path,
        item_id: str,
        worker_id: str,
        *,
        ignore_claimed_item_id: str = "",
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.reclaim_for_replay(
                conn,
                item_id,
                worker_id,
                ignore_claimed_item_id=ignore_claimed_item_id,
            )

    def recover_stale_claims(
        self, data_dir: Path, current_worker_id: str, max_age_seconds: int = 300,
    ) -> int:
        with self._conn() as conn:
            return work_queue_postgres_impl.recover_stale_claims(
                conn, current_worker_id, max_age_seconds
            )

    def purge_old(self, data_dir: Path, older_than_hours: int = 24) -> int:
        with self._conn() as conn:
            return work_queue_postgres_impl.purge_old(conn, older_than_hours)

    def get_user_access(self, data_dir: Path, actor_key: str) -> str | None:
        with self._conn() as conn:
            return work_queue_postgres_impl.get_user_access_override(conn, actor_key)

    def set_user_access(
        self,
        data_dir: Path,
        actor_key: str,
        access: str,
        reason: str = "",
        granted_by: str = "",
    ) -> None:
        with self._conn() as conn:
            work_queue_postgres_impl.set_user_access(conn, actor_key, access, reason, granted_by)

    def list_user_access(self, data_dir: Path) -> list[dict]:
        with self._conn() as conn:
            return work_queue_postgres_impl.list_user_access(conn)

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
        with self._conn() as conn:
            work_queue_postgres_impl.record_usage(
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
    ) -> list[dict]:
        with self._conn() as conn:
            return work_queue_postgres_impl.get_usage_since(conn, since_epoch=since_epoch)

    def close_transport_db(self, data_dir: Path) -> None:
        pass

    def close_all_transport_db(self) -> None:
        pass

    def reset_db_for_test(self, data_dir: Path) -> None:
        pass

    def debug_connection(self, data_dir: Path):
        """Not available via runtime backend; use conn-based helpers in tests."""
        raise NotImplementedError(
            "Postgres transport store does not expose a runtime debug connection; "
            "use the conn-based transport implementation helpers in tests"
        )
