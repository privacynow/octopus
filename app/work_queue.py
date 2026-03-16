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
    "cancel_queued_fresh_for_chat",
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
    "get_user_access",
    "get_work_items_for_chat",
    "has_claimed_for_chat",
    "has_queued_or_claimed",
    "list_user_access",
    "mark_pending_recovery",
    "purge_old",
    "reclaim_for_replay",
    "record_and_admit_message",
    "record_and_enqueue",
    "record_usage",
    "record_update",
    "recover_stale_claims",
    "set_user_access",
    "supersede_pending_recovery",
    "get_usage_since",
    "update_payload",
]


def _store():
    return runtime_backend.transport_store()


def close_transport_db(data_dir: Path) -> None:
    _store().close_transport_db(data_dir)


def close_all_transport_db() -> None:
    _store().close_all_transport_db()


def record_and_admit_message(
    data_dir: Path,
    update_id: int,
    chat_id: int,
    user_id: int,
    kind: str,
    payload: str = "{}",
) -> tuple[str, str | None]:
    """Record update and admit or reject for provider work. Returns (status, item_id).
    status: 'duplicate' | 'admitted' | 'busy'. item_id set when admitted or busy."""
    return _store().record_and_admit_message(
        data_dir, update_id, chat_id, user_id, kind, payload,
    )


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


def cancel_queued_fresh_for_chat(data_dir: Path, chat_id: int) -> bool:
    """If this chat has a queued fresh item, mark it failed with error='cancelled'. Returns True if one was cancelled."""
    return _store().cancel_queued_fresh_for_chat(data_dir, chat_id)


def has_claimed_for_chat(data_dir: Path, chat_id: int) -> bool:
    return _store().has_claimed_for_chat(data_dir, chat_id)


def has_queued_or_claimed(data_dir: Path, chat_id: int) -> bool:
    return _store().has_queued_or_claimed(data_dir, chat_id)


def get_update_payload(data_dir: Path, update_id: int) -> str | None:
    return _store().get_update_payload(data_dir, update_id)


def get_user_access(data_dir: Path, user_id: int) -> str | None:
    return _store().get_user_access(data_dir, user_id)


def set_user_access(
    data_dir: Path,
    user_id: int,
    access: str,
    reason: str = "",
    granted_by: int = 0,
) -> None:
    _store().set_user_access(data_dir, user_id, access, reason, granted_by)


def list_user_access(data_dir: Path) -> list[dict]:
    return _store().list_user_access(data_dir)


def record_usage(
    data_dir: Path,
    *,
    chat_id: int,
    work_item_id: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    _store().record_usage(
        data_dir,
        chat_id=chat_id,
        work_item_id=work_item_id,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


def get_usage_since(data_dir: Path, *, since_epoch: float) -> list[dict]:
    return _store().get_usage_since(data_dir, since_epoch=since_epoch)


def get_work_items_for_chat(data_dir: Path, chat_id: int) -> list[dict[str, Any]]:
    """Return work items for chat: id, update_id, state, error, dispatch_mode, kind. Read-only; for contract/test assertion."""
    return _store().get_work_items_for_chat(data_dir, chat_id)


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
