"""Postgres transport store wrapper. Conn-based API lives in work_queue_pg for tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.transport_contract import DiscardResult
from app import work_queue_pg


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
        update_id: int,
        chat_id: int,
        user_id: int,
        kind: str,
        payload: str = "{}",
        *,
        worker_id: str | None = None,
    ) -> tuple[bool, str | None]:
        with self._conn() as conn:
            return work_queue_pg.record_and_enqueue(
                conn, update_id, chat_id, user_id, kind, payload, worker_id=worker_id,
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
        with self._conn() as conn:
            return work_queue_pg.record_update(conn, update_id, chat_id, user_id, kind, payload)

    def enqueue_work_item(
        self,
        data_dir: Path,
        chat_id: int,
        update_id: int,
        *,
        worker_id: str | None = None,
    ) -> str:
        with self._conn() as conn:
            return work_queue_pg.enqueue_work_item(conn, chat_id, update_id, worker_id=worker_id)

    def update_payload(self, data_dir: Path, update_id: int, payload: str) -> None:
        with self._conn() as conn:
            work_queue_pg.update_payload(conn, update_id, payload)

    def claim_for_update(
        self, data_dir: Path, chat_id: int, update_id: int, worker_id: str,
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_pg.claim_for_update(conn, chat_id, update_id, worker_id)

    def claim_next(self, data_dir: Path, chat_id: int, worker_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_pg.claim_next(conn, chat_id, worker_id)

    def claim_next_any(self, data_dir: Path, worker_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_pg.claim_next_any(conn, worker_id)

    def complete_work_item(self, data_dir: Path, item_id: str) -> None:
        with self._conn() as conn:
            work_queue_pg.complete_work_item(conn, item_id)

    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None:
        with self._conn() as conn:
            work_queue_pg.fail_work_item(conn, item_id, error)

    def has_claimed_for_chat(self, data_dir: Path, chat_id: int) -> bool:
        with self._conn() as conn:
            return work_queue_pg.has_claimed_for_chat(conn, chat_id)

    def has_queued_or_claimed(self, data_dir: Path, chat_id: int) -> bool:
        with self._conn() as conn:
            return work_queue_pg.has_queued_or_claimed(conn, chat_id)

    def get_update_payload(self, data_dir: Path, update_id: int) -> str | None:
        with self._conn() as conn:
            return work_queue_pg.get_update_payload(conn, update_id)

    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None:
        with self._conn() as conn:
            work_queue_pg.mark_pending_recovery(conn, item_id)

    def get_pending_recovery_for_update(
        self, data_dir: Path, chat_id: int, update_id: int,
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_pg.get_pending_recovery_for_update(conn, chat_id, update_id)

    def get_latest_pending_recovery(self, data_dir: Path, chat_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_pg.get_latest_pending_recovery(conn, chat_id)

    def supersede_pending_recovery(self, data_dir: Path, chat_id: int) -> int:
        with self._conn() as conn:
            return work_queue_pg.supersede_pending_recovery(conn, chat_id)

    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult:
        with self._conn() as conn:
            return work_queue_pg.discard_recovery(conn, item_id)

    def reclaim_for_replay(
        self, data_dir: Path, item_id: str, worker_id: str,
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            return work_queue_pg.reclaim_for_replay(conn, item_id, worker_id)

    def recover_stale_claims(
        self, data_dir: Path, current_worker_id: str, max_age_seconds: int = 300,
    ) -> int:
        with self._conn() as conn:
            return work_queue_pg.recover_stale_claims(conn, current_worker_id, max_age_seconds)

    def purge_old(self, data_dir: Path, older_than_hours: int = 24) -> int:
        with self._conn() as conn:
            return work_queue_pg.purge_old(conn, older_than_hours)

    def close_transport_db(self, data_dir: Path) -> None:
        pass

    def close_all_transport_db(self) -> None:
        pass

    def _reset_transport_db(self, data_dir: Path) -> None:
        pass

    def _transport_db(self, data_dir: Path):
        """Not available for Postgres; use pool. Raises for tests that assume SQLite."""
        raise NotImplementedError("Postgres transport store does not expose _transport_db; use connection pool")
