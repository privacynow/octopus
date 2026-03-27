"""SDK durable-admission and transport-work queue contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from collections.abc import Mapping
from typing import Protocol

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _coerce_epoch_float(value: object) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if value is None:
        return 0.0
    return float(value or 0.0)


class LeaveClaimed(Exception):
    """Control-flow signal: leave the current claimed work item unreconciled."""


class PendingRecovery(Exception):
    """Control-flow signal: item transitioned to pending recovery."""


class ReclaimBlocked(Exception):
    """The item exists in pending recovery but cannot be reclaimed."""


class OtherClaimedForChat(Exception):
    """Another item for the same conversation is already claimed."""


class BlockedReplay(Exception):
    """Replay requested but another item for the same conversation is claimed."""


class NotStaleClaim(Exception):
    """recover_stale_claim was invoked but the claim is not stale."""


class TransportStateCorruption(Exception):
    """Durable queue state is not internally consistent."""


class DiscardResult(str, Enum):
    success = "success"
    already_handled = "already_handled"
    corruption = "corruption"


class ApplyResult(str, Enum):
    success = "success"
    already_handled = "already_handled"
    workflow_rejected = "workflow_rejected"
    corruption = "corruption"


class CancelRequestResult(str, Enum):
    queued_cancelled = "queued_cancelled"
    claimed_cancel_requested = "claimed_cancel_requested"
    nothing_to_cancel = "nothing_to_cancel"


class TransportDisposition(str, Enum):
    ok = "ok"
    already_claimed_by_worker = "already_claimed_by_worker"
    other_claimed_for_chat = "other_claimed_for_chat"
    blocked_replay = "blocked_replay"
    already_handled = "already_handled"
    discarded = "discarded"
    replayed = "replayed"
    superseded = "superseded"
    stale_recovered = "stale_recovered"
    done = "done"
    failed = "failed"
    invalid_transition = "invalid_transition"
    guard_failed = "guard_failed"


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    new_state: str | None
    disposition: TransportDisposition
    reason: str = ""
    user_message_key: str | None = None
    extra: dict[str, JsonValue] | None = None
    model: object | None = None


@dataclass(frozen=True)
class QueueSnapshot:
    fresh_queued_count: int = 0
    recovery_queued_count: int = 0
    claimed_count: int = 0
    pending_recovery_count: int = 0
    cancel_requested_claimed_count: int = 0
    oldest_fresh_queued_at: str | None = None
    oldest_recovery_queued_at: str | None = None
    oldest_claimed_at: str | None = None
    oldest_pending_recovery_at: str | None = None


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    process_role: str
    started_at: str
    last_seen_at: str
    current_item_id: str = ""
    current_conversation_key: str = ""
    current_kind: str = ""
    items_processed: int = 0
    stale_recoveries_seen: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class WorkItemRecord:
    id: str = ""
    conversation_key: str = ""
    event_id: str = ""
    actor_key: str = ""
    kind: str = ""
    payload: str = ""
    state: str = ""
    worker_id: str | None = None
    claimed_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    created_at: str = ""
    dispatch_mode: str = ""
    cancel_requested_at: str | None = None
    cancel_requested_by: str = ""
    cancel_request_event_id: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "WorkItemRecord":
        raw = dict(value)
        return cls(
            id=str(raw.get("id", "") or ""),
            conversation_key=str(raw.get("conversation_key", "") or ""),
            event_id=str(raw.get("event_id", "") or ""),
            actor_key=str(raw.get("actor_key", "") or ""),
            kind=str(raw.get("kind", "") or ""),
            payload=str(raw.get("payload", "") or ""),
            state=str(raw.get("state", "") or ""),
            worker_id=None if raw.get("worker_id") is None else str(raw.get("worker_id") or ""),
            claimed_at=None if raw.get("claimed_at") is None else str(raw.get("claimed_at") or ""),
            completed_at=None if raw.get("completed_at") is None else str(raw.get("completed_at") or ""),
            error=None if raw.get("error") is None else str(raw.get("error") or ""),
            created_at=str(raw.get("created_at", "") or ""),
            dispatch_mode=str(raw.get("dispatch_mode", "") or ""),
            cancel_requested_at=None if raw.get("cancel_requested_at") is None else str(raw.get("cancel_requested_at") or ""),
            cancel_requested_by=str(raw.get("cancel_requested_by", "") or ""),
            cancel_request_event_id=str(raw.get("cancel_request_event_id", "") or ""),
        )


@dataclass(frozen=True)
class UserAccessRecord:
    actor_key: str = ""
    access: str = ""
    reason: str = ""
    granted_by: str = ""
    granted_at: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "UserAccessRecord":
        raw = dict(value)
        return cls(
            actor_key=str(raw.get("actor_key", "") or ""),
            access=str(raw.get("access", "") or ""),
            reason=str(raw.get("reason", "") or ""),
            granted_by=str(raw.get("granted_by", "") or ""),
            granted_at=_coerce_epoch_float(raw.get("granted_at", 0.0)),
        )


@dataclass(frozen=True)
class UsageRecord:
    conversation_key: str = ""
    work_item_id: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    recorded_at: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "UsageRecord":
        raw = dict(value)
        return cls(
            conversation_key=str(raw.get("conversation_key", "") or ""),
            work_item_id=str(raw.get("work_item_id", "") or ""),
            provider=str(raw.get("provider", "") or ""),
            prompt_tokens=int(raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(raw.get("completion_tokens", 0) or 0),
            cost_usd=float(raw.get("cost_usd", 0.0) or 0.0),
            recorded_at=_coerce_epoch_float(raw.get("recorded_at", 0.0)),
        )


def coerce_work_item_record(value: Mapping[str, object] | WorkItemRecord | None) -> WorkItemRecord | None:
    if value is None or isinstance(value, WorkItemRecord):
        return value
    return WorkItemRecord.from_mapping(value)


def coerce_work_item_records(values: list[Mapping[str, object] | WorkItemRecord]) -> list[WorkItemRecord]:
    return [record if isinstance(record, WorkItemRecord) else WorkItemRecord.from_mapping(record) for record in values]


def coerce_user_access_records(values: list[Mapping[str, object] | UserAccessRecord]) -> list[UserAccessRecord]:
    return [record if isinstance(record, UserAccessRecord) else UserAccessRecord.from_mapping(record) for record in values]


def coerce_usage_records(values: list[Mapping[str, object] | UsageRecord]) -> list[UsageRecord]:
    return [record if isinstance(record, UsageRecord) else UsageRecord.from_mapping(record) for record in values]

TRANSPORT_STATES = frozenset(
    {"queued", "claimed", "done", "failed", "pending_recovery"},
)


def validate_work_item_row(
    row: Mapping[str, object] | WorkItemRecord,
    item_id: str = "",
) -> None:
    """Raise TransportStateCorruption if a durable queue row violates invariants."""

    row = row if isinstance(row, WorkItemRecord) else WorkItemRecord.from_mapping(row)
    state = row.state
    if state not in TRANSPORT_STATES:
        raise TransportStateCorruption(
            f"unknown state {state!r}" + (f" for item {item_id}" if item_id else ""),
        )
    dispatch_mode = row.dispatch_mode
    if dispatch_mode not in ("fresh", "recovery"):
        raise TransportStateCorruption(
            "work item row must have dispatch_mode in ('fresh', 'recovery')"
            + (f" (item {item_id})" if item_id else ""),
        )
    if state == "claimed":
        if row.worker_id is None:
            raise TransportStateCorruption(
                "claimed row must have worker_id" + (f" (item {item_id})" if item_id else ""),
            )
        if row.claimed_at is None:
            raise TransportStateCorruption(
                "claimed row must have claimed_at" + (f" (item {item_id})" if item_id else ""),
            )


_validate_work_item_row = validate_work_item_row


class WorkQueuePort(Protocol):
    def close_transport_db(self, data_dir: Path) -> None: ...
    def close_all_transport_db(self) -> None: ...
    def debug_connection(self, data_dir: Path) -> object: ...
    def reset_db_for_test(self, data_dir: Path) -> None: ...
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
    ) -> tuple[bool, str | None]: ...
    def record_and_admit_message(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> tuple[str, str | None]: ...
    def record_update(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> bool: ...
    def enqueue_work_item(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        *,
        worker_id: str | None = None,
    ) -> str: ...
    def update_payload(self, data_dir: Path, event_id: str, payload: str) -> None: ...
    def claim_for_update(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        worker_id: str,
    ) -> WorkItemRecord | None: ...
    def claim_next(
        self,
        data_dir: Path,
        conversation_key: str,
        worker_id: str,
    ) -> WorkItemRecord | None: ...
    def claim_next_any(self, data_dir: Path, worker_id: str) -> WorkItemRecord | None: ...
    def complete_work_item(self, data_dir: Path, item_id: str) -> None: ...
    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None: ...
    def cancel_queued_fresh_for_chat(self, data_dir: Path, conversation_key: str) -> bool: ...
    def request_cancel(
        self,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        *,
        cancel_request_event_id: str = "",
    ) -> CancelRequestResult: ...
    def is_cancel_requested(self, data_dir: Path, item_id: str) -> bool: ...
    def has_claimed_for_chat(self, data_dir: Path, conversation_key: str) -> bool: ...
    def has_queued_or_claimed(self, data_dir: Path, conversation_key: str) -> bool: ...
    def get_update_payload(self, data_dir: Path, event_id: str) -> str | None: ...
    def get_user_access(self, data_dir: Path, actor_key: str) -> str | None: ...
    def set_user_access(
        self,
        data_dir: Path,
        actor_key: str,
        access: str,
        reason: str = "",
        granted_by: str = "",
    ) -> None: ...
    def list_user_access(self, data_dir: Path) -> list[UserAccessRecord]: ...
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
    ) -> None: ...
    def get_usage_since(self, data_dir: Path, *, since_epoch: float) -> list[UsageRecord]: ...
    def get_work_items_for_chat(self, data_dir: Path, conversation_key: str) -> list[WorkItemRecord]: ...
    def get_queue_snapshot(self, data_dir: Path) -> QueueSnapshot: ...
    def upsert_worker_heartbeat(self, data_dir: Path, heartbeat: WorkerHeartbeat) -> None: ...
    def clear_worker_heartbeat(self, data_dir: Path, worker_id: str) -> None: ...
    def list_worker_heartbeats(self, data_dir: Path) -> list[WorkerHeartbeat]: ...
    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None: ...
    def get_pending_recovery_for_update(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
    ) -> WorkItemRecord | None: ...
    def get_latest_pending_recovery(
        self,
        data_dir: Path,
        conversation_key: str,
    ) -> WorkItemRecord | None: ...
    def supersede_pending_recovery(self, data_dir: Path, conversation_key: str) -> int: ...
    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult: ...
    def reclaim_for_replay(
        self,
        data_dir: Path,
        item_id: str,
        worker_id: str,
        *,
        ignore_claimed_item_id: str = "",
    ) -> WorkItemRecord | None: ...
    def recover_stale_claims(
        self,
        data_dir: Path,
        *,
        lease_ttl_seconds: int = 300,
    ) -> int: ...
    def purge_old(
        self,
        data_dir: Path,
        *,
        older_than_seconds: int = 7 * 24 * 3600,
    ) -> int: ...
    def purge_old_usage(
        self,
        data_dir: Path,
        *,
        older_than_seconds: int = 30 * 24 * 3600,
    ) -> int: ...
