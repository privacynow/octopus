"""Durable transport layer: facade over runtime_backend.transport_store(). Product/runtime API only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import runtime_backend
from app.transport_contract import (
    ApplyResult,
    DiscardResult,
    LeaveClaimed,
    PendingRecovery,
    ReclaimBlocked,
)

__all__ = [
    "ApplyResult",
    "DiscardResult",
    "LeaveClaimed",
    "PendingRecovery",
    "ReclaimBlocked",
    "close_all_transport_db",
    "close_transport_db",
    "claim_for_update",
    "claim_next",
    "claim_next_any",
    "complete_work_item",
    "discard_recovery",
    "enqueue_work_item",
    "fail_work_item",
    "get_latest_pending_recovery",
    "get_pending_recovery_for_update",
    "get_update_payload",
    "has_claimed_for_chat",
    "has_queued_or_claimed",
    "mark_pending_recovery",
    "purge_old",
    "reclaim_for_replay",
    "record_and_enqueue",
    "record_update",
    "recover_stale_claims",
    "supersede_pending_recovery",
    "update_payload",
]


def _store():
    return runtime_backend.transport_store()


def close_transport_db(data_dir: Path) -> None:
    _store().close_transport_db(data_dir)


def close_all_transport_db() -> None:
    _store().close_all_transport_db()


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
    return _store().record_and_enqueue(
        data_dir, update_id, chat_id, user_id, kind, payload, worker_id=worker_id,
    )


def record_update(
    data_dir: Path,
    update_id: int,
    chat_id: int,
    user_id: int,
    kind: str,
    payload: str = "{}",
) -> bool:
    return _store().record_update(data_dir, update_id, chat_id, user_id, kind, payload)


def enqueue_work_item(
    data_dir: Path, chat_id: int, update_id: int, *, worker_id: str | None = None,
) -> str:
    return _store().enqueue_work_item(data_dir, chat_id, update_id, worker_id=worker_id)


def update_payload(data_dir: Path, update_id: int, payload: str) -> None:
    _store().update_payload(data_dir, update_id, payload)


def claim_for_update(
    data_dir: Path, chat_id: int, update_id: int, worker_id: str,
) -> dict[str, Any] | None:
    return _store().claim_for_update(data_dir, chat_id, update_id, worker_id)


def claim_next(data_dir: Path, chat_id: int, worker_id: str) -> dict[str, Any] | None:
    return _store().claim_next(data_dir, chat_id, worker_id)


def claim_next_any(data_dir: Path, worker_id: str) -> dict[str, Any] | None:
    return _store().claim_next_any(data_dir, worker_id)


def complete_work_item(data_dir: Path, item_id: str) -> None:
    _store().complete_work_item(data_dir, item_id)


def fail_work_item(data_dir: Path, item_id: str, error: str) -> None:
    _store().fail_work_item(data_dir, item_id, error)


def has_claimed_for_chat(data_dir: Path, chat_id: int) -> bool:
    return _store().has_claimed_for_chat(data_dir, chat_id)


def has_queued_or_claimed(data_dir: Path, chat_id: int) -> bool:
    return _store().has_queued_or_claimed(data_dir, chat_id)


def get_update_payload(data_dir: Path, update_id: int) -> str | None:
    return _store().get_update_payload(data_dir, update_id)


def mark_pending_recovery(data_dir: Path, item_id: str) -> None:
    _store().mark_pending_recovery(data_dir, item_id)


def get_pending_recovery_for_update(
    data_dir: Path, chat_id: int, update_id: int,
) -> dict[str, Any] | None:
    return _store().get_pending_recovery_for_update(data_dir, chat_id, update_id)


def get_latest_pending_recovery(data_dir: Path, chat_id: int) -> dict[str, Any] | None:
    return _store().get_latest_pending_recovery(data_dir, chat_id)


def supersede_pending_recovery(data_dir: Path, chat_id: int) -> int:
    return _store().supersede_pending_recovery(data_dir, chat_id)


def discard_recovery(data_dir: Path, item_id: str) -> DiscardResult:
    return _store().discard_recovery(data_dir, item_id)


def reclaim_for_replay(
    data_dir: Path, item_id: str, worker_id: str,
) -> dict[str, Any] | None:
    return _store().reclaim_for_replay(data_dir, item_id, worker_id)


def recover_stale_claims(
    data_dir: Path, current_worker_id: str, max_age_seconds: int = 300,
) -> int:
    return _store().recover_stale_claims(data_dir, current_worker_id, max_age_seconds)


def purge_old(data_dir: Path, older_than_hours: int = 24) -> int:
    return _store().purge_old(data_dir, older_than_hours)
