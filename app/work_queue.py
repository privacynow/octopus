"""Durable transport layer: facade over runtime_backend.transport_store(). Product/runtime API only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import runtime_backend
from app.runtime_health import QueueSnapshot, WorkerHeartbeat
from app.transport_contract import (
    ApplyResult,
    CancelRequestResult,
    DiscardResult,
    LeaveClaimed,
    PendingRecovery,
    ReclaimBlocked,
)

__all__ = [
    "ApplyResult",
    "CancelRequestResult",
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
    "debug_transport_connection",
    "enqueue_work_item",
    "fail_work_item",
    "get_queue_snapshot",
    "get_latest_pending_recovery",
    "get_pending_recovery_for_update",
    "get_update_payload",
    "get_user_access",
    "get_work_items_for_chat",
    "has_claimed_for_chat",
    "has_queued_or_claimed",
    "list_user_access",
    "list_worker_heartbeats",
    "mark_pending_recovery",
    "purge_old",
    "request_cancel",
    "reclaim_for_replay",
    "record_and_admit_message",
    "record_and_enqueue",
    "record_usage",
    "record_update",
    "recover_stale_claims",
    "reset_transport_store_for_test",
    "clear_worker_heartbeat",
    "set_user_access",
    "supersede_pending_recovery",
    "is_cancel_requested",
    "get_usage_since",
    "upsert_worker_heartbeat",
    "update_payload",
]


def _store():
    return runtime_backend.transport_store()


def close_transport_db(data_dir: Path) -> None:
    _store().close_transport_db(data_dir)


def close_all_transport_db() -> None:
    _store().close_all_transport_db()


def debug_transport_connection(data_dir: Path):
    """Return a backend-specific transport-store inspection handle. Tests only."""
    return _store().debug_connection(data_dir)


def reset_transport_store_for_test(data_dir: Path) -> None:
    """Tests only: close and reset the transport store for this data dir."""
    _store().reset_db_for_test(data_dir)


def record_and_admit_message(
    data_dir: Path,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
) -> tuple[str, str | None]:
    """Record update and durably admit fresh message work. Returns (status, item_id).

    status: 'duplicate' | 'admitted' | 'queued'. item_id set when admitted or queued.
    'admitted' means no older fresh runnable work existed for the conversation.
    'queued' means the item was accepted behind existing fresh work.
    """
    return _store().record_and_admit_message(
        data_dir, event_id, conversation_key, actor_key, kind, payload,
    )


def record_and_enqueue(
    data_dir: Path,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
    *,
    worker_id: str | None = None,
) -> tuple[bool, str | None]:
    return _store().record_and_enqueue(
        data_dir, event_id, conversation_key, actor_key, kind, payload, worker_id=worker_id,
    )


def record_update(
    data_dir: Path,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
) -> bool:
    return _store().record_update(data_dir, event_id, conversation_key, actor_key, kind, payload)


def enqueue_work_item(
    data_dir: Path, conversation_key: str, event_id: str, *, worker_id: str | None = None,
) -> str:
    return _store().enqueue_work_item(data_dir, conversation_key, event_id, worker_id=worker_id)


def update_payload(data_dir: Path, event_id: str, payload: str) -> None:
    _store().update_payload(data_dir, event_id, payload)


def claim_for_update(
    data_dir: Path, conversation_key: str, event_id: str, worker_id: str,
) -> dict[str, Any] | None:
    return _store().claim_for_update(data_dir, conversation_key, event_id, worker_id)


def claim_next(data_dir: Path, conversation_key: str, worker_id: str) -> dict[str, Any] | None:
    return _store().claim_next(data_dir, conversation_key, worker_id)


def claim_next_any(data_dir: Path, worker_id: str) -> dict[str, Any] | None:
    return _store().claim_next_any(data_dir, worker_id)


def complete_work_item(data_dir: Path, item_id: str) -> None:
    _store().complete_work_item(data_dir, item_id)


def fail_work_item(data_dir: Path, item_id: str, error: str) -> None:
    _store().fail_work_item(data_dir, item_id, error)


def cancel_queued_fresh_for_chat(data_dir: Path, conversation_key: str) -> bool:
    """If this conversation has a queued fresh item, mark it failed with error='cancelled'."""
    return _store().cancel_queued_fresh_for_chat(data_dir, conversation_key)


def request_cancel(
    data_dir: Path,
    conversation_key: str,
    actor_key: str,
    *,
    cancel_request_event_id: str = "",
) -> CancelRequestResult:
    return _store().request_cancel(
        data_dir,
        conversation_key,
        actor_key,
        cancel_request_event_id=cancel_request_event_id,
    )


def is_cancel_requested(data_dir: Path, item_id: str) -> bool:
    return _store().is_cancel_requested(data_dir, item_id)


def has_claimed_for_chat(data_dir: Path, conversation_key: str) -> bool:
    return _store().has_claimed_for_chat(data_dir, conversation_key)


def has_queued_or_claimed(data_dir: Path, conversation_key: str) -> bool:
    return _store().has_queued_or_claimed(data_dir, conversation_key)


def get_update_payload(data_dir: Path, event_id: str) -> str | None:
    return _store().get_update_payload(data_dir, event_id)


def get_user_access(data_dir: Path, actor_key: str) -> str | None:
    return _store().get_user_access(data_dir, actor_key)


def set_user_access(
    data_dir: Path,
    actor_key: str,
    access: str,
    reason: str = "",
    granted_by: str = "",
) -> None:
    _store().set_user_access(data_dir, actor_key, access, reason, granted_by)


def list_user_access(data_dir: Path) -> list[dict]:
    return _store().list_user_access(data_dir)


def record_usage(
    data_dir: Path,
    *,
    conversation_key: str,
    work_item_id: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    _store().record_usage(
        data_dir,
        conversation_key=conversation_key,
        work_item_id=work_item_id,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


def get_usage_since(data_dir: Path, *, since_epoch: float) -> list[dict]:
    return _store().get_usage_since(data_dir, since_epoch=since_epoch)


def get_work_items_for_chat(data_dir: Path, conversation_key: str) -> list[dict[str, Any]]:
    """Return work items for a conversation: id, event_id, state, error, dispatch_mode, kind."""
    return _store().get_work_items_for_chat(data_dir, conversation_key)


def get_queue_snapshot(data_dir: Path) -> QueueSnapshot:
    """Return a backend-neutral queue summary for Shared Runtime observability."""
    return _store().get_queue_snapshot(data_dir)


def upsert_worker_heartbeat(data_dir: Path, heartbeat: WorkerHeartbeat) -> None:
    _store().upsert_worker_heartbeat(data_dir, heartbeat)


def clear_worker_heartbeat(data_dir: Path, worker_id: str) -> None:
    _store().clear_worker_heartbeat(data_dir, worker_id)


def list_worker_heartbeats(data_dir: Path) -> list[WorkerHeartbeat]:
    return _store().list_worker_heartbeats(data_dir)


def mark_pending_recovery(data_dir: Path, item_id: str) -> None:
    _store().mark_pending_recovery(data_dir, item_id)


def get_pending_recovery_for_update(
    data_dir: Path, conversation_key: str, event_id: str,
) -> dict[str, Any] | None:
    return _store().get_pending_recovery_for_update(data_dir, conversation_key, event_id)


def get_latest_pending_recovery(data_dir: Path, conversation_key: str) -> dict[str, Any] | None:
    return _store().get_latest_pending_recovery(data_dir, conversation_key)


def supersede_pending_recovery(data_dir: Path, conversation_key: str) -> int:
    return _store().supersede_pending_recovery(data_dir, conversation_key)


def discard_recovery(data_dir: Path, item_id: str) -> DiscardResult:
    return _store().discard_recovery(data_dir, item_id)


def reclaim_for_replay(
    data_dir: Path,
    item_id: str,
    worker_id: str,
    *,
    ignore_claimed_item_id: str = "",
) -> dict[str, Any] | None:
    return _store().reclaim_for_replay(
        data_dir,
        item_id,
        worker_id,
        ignore_claimed_item_id=ignore_claimed_item_id,
    )


def recover_stale_claims(
    data_dir: Path, current_worker_id: str, max_age_seconds: int = 300,
) -> int:
    return _store().recover_stale_claims(data_dir, current_worker_id, max_age_seconds)


def purge_old(data_dir: Path, older_than_hours: int = 24) -> int:
    return _store().purge_old(data_dir, older_than_hours)
