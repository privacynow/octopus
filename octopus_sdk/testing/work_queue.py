"""In-memory work-queue implementation for SDK composition tests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from octopus_sdk.work_queue import (
    CancelRequestResult,
    DiscardResult,
    QueueSnapshot,
    UsageRecord,
    UserAccessRecord,
    WorkItemRecord,
    WorkQueuePort,
    WorkerHeartbeat,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


@dataclass
class _QueueState:
    work_items: dict[str, WorkItemRecord] = field(default_factory=dict)
    event_index: dict[str, str] = field(default_factory=dict)
    update_payloads: dict[str, str] = field(default_factory=dict)
    user_access: dict[str, UserAccessRecord] = field(default_factory=dict)
    usage_records: list[UsageRecord] = field(default_factory=list)
    heartbeats: dict[str, WorkerHeartbeat] = field(default_factory=dict)


@dataclass
class InMemoryWorkQueue(WorkQueuePort):
    """In-memory durable-admission store suitable for SDK-only tests."""

    _states: dict[str, _QueueState] = field(default_factory=dict)

    def _state(self, data_dir: Path) -> _QueueState:
        return self._states.setdefault(str(data_dir), _QueueState())

    def _new_id(self) -> str:
        return uuid4().hex

    def close_transport_db(self, data_dir: Path) -> None:
        del data_dir

    def close_all_transport_db(self) -> None:
        self._states.clear()

    def debug_connection(self, data_dir: Path) -> object:
        return self._state(data_dir)

    def reset_db_for_test(self, data_dir: Path) -> None:
        self._states.pop(str(data_dir), None)

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
        state = self._state(data_dir)
        existing_id = state.event_index.get(event_id)
        if existing_id is not None:
            return False, existing_id
        item_id = self._new_id()
        state.work_items[item_id] = WorkItemRecord(
            id=item_id,
            conversation_key=conversation_key,
            event_id=event_id,
            actor_key=actor_key,
            kind=kind,
            payload=payload,
            state="queued",
            created_at=_iso_now(),
            dispatch_mode="fresh",
            worker_id=worker_id,
        )
        state.event_index[event_id] = item_id
        state.update_payloads[event_id] = payload
        return True, item_id

    def record_and_admit_message(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> tuple[str, str | None]:
        state = self._state(data_dir)
        existing_id = state.event_index.get(event_id)
        if existing_id is not None:
            return "duplicate", existing_id
        item_id = self._new_id()
        state.work_items[item_id] = WorkItemRecord(
            id=item_id,
            conversation_key=conversation_key,
            event_id=event_id,
            actor_key=actor_key,
            kind=kind,
            payload=payload,
            state="done",
            created_at=_iso_now(),
            completed_at=_iso_now(),
            dispatch_mode="fresh",
        )
        state.event_index[event_id] = item_id
        state.update_payloads[event_id] = payload
        return "admitted", item_id

    def record_update(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> bool:
        del conversation_key, actor_key, kind
        self._state(data_dir).update_payloads[event_id] = payload
        return True

    def enqueue_work_item(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        *,
        worker_id: str | None = None,
    ) -> str:
        state = self._state(data_dir)
        existing = state.event_index.get(event_id)
        if existing is not None:
            item = state.work_items[existing]
            state.work_items[existing] = replace(
                item,
                state="queued",
                worker_id=worker_id,
                dispatch_mode=item.dispatch_mode or "fresh",
            )
            return existing
        item_id = self._new_id()
        state.work_items[item_id] = WorkItemRecord(
            id=item_id,
            conversation_key=conversation_key,
            event_id=event_id,
            actor_key="",
            kind="message",
            payload=self.get_update_payload(data_dir, event_id) or "{}",
            state="queued",
            created_at=_iso_now(),
            dispatch_mode="fresh",
            worker_id=worker_id,
        )
        state.event_index[event_id] = item_id
        return item_id

    def update_payload(self, data_dir: Path, event_id: str, payload: str) -> None:
        self._state(data_dir).update_payloads[event_id] = payload

    def claim_for_update(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        worker_id: str,
    ) -> WorkItemRecord | None:
        state = self._state(data_dir)
        item_id = state.event_index.get(event_id)
        if item_id is None:
            return None
        item = state.work_items[item_id]
        if item.conversation_key != conversation_key or item.state != "queued":
            return None
        claimed = replace(item, state="claimed", worker_id=worker_id, claimed_at=_iso_now())
        state.work_items[item_id] = claimed
        return claimed

    def claim_next(
        self,
        data_dir: Path,
        conversation_key: str,
        worker_id: str,
    ) -> WorkItemRecord | None:
        for item in self.get_work_items_for_chat(data_dir, conversation_key):
            if item.state == "queued":
                claimed = replace(item, state="claimed", worker_id=worker_id, claimed_at=_iso_now())
                self._state(data_dir).work_items[item.id] = claimed
                return claimed
        return None

    def claim_next_any(self, data_dir: Path, worker_id: str) -> WorkItemRecord | None:
        state = self._state(data_dir)
        queued = sorted(
            (item for item in state.work_items.values() if item.state == "queued"),
            key=lambda item: item.created_at,
        )
        if not queued:
            return None
        item = queued[0]
        claimed = replace(item, state="claimed", worker_id=worker_id, claimed_at=_iso_now())
        state.work_items[item.id] = claimed
        return claimed

    def list_incomplete_work_items(self, data_dir: Path) -> list[WorkItemRecord]:
        del data_dir
        raise NotImplementedError(
            "InMemoryWorkQueue is test-only and does not enumerate durable "
            "incomplete work across restarts."
        )

    def recover_after_crash(
        self,
        data_dir: Path,
        *,
        lease_ttl_seconds: int = 300,
    ) -> int:
        del data_dir, lease_ttl_seconds
        raise NotImplementedError(
            "InMemoryWorkQueue is test-only and does not provide durable "
            "crash recovery."
        )

    def complete_work_item(self, data_dir: Path, item_id: str) -> None:
        state = self._state(data_dir)
        item = state.work_items[item_id]
        state.work_items[item_id] = replace(item, state="done", completed_at=_iso_now(), worker_id=None)

    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None:
        state = self._state(data_dir)
        item = state.work_items[item_id]
        state.work_items[item_id] = replace(item, state="failed", error=error, completed_at=_iso_now(), worker_id=None)

    def cancel_queued_fresh_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        state = self._state(data_dir)
        removed = False
        for item_id, item in list(state.work_items.items()):
            if item.conversation_key == conversation_key and item.state == "queued" and item.dispatch_mode == "fresh":
                del state.work_items[item_id]
                removed = True
        return removed

    def request_cancel(
        self,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        *,
        cancel_request_event_id: str = "",
    ) -> CancelRequestResult:
        state = self._state(data_dir)
        queued = [
            item for item in state.work_items.values()
            if item.conversation_key == conversation_key and item.state == "queued" and item.dispatch_mode == "fresh"
        ]
        if queued:
            for item in queued:
                del state.work_items[item.id]
            return CancelRequestResult.queued_cancelled
        for item in state.work_items.values():
            if item.conversation_key == conversation_key and item.state == "claimed":
                state.work_items[item.id] = replace(
                    item,
                    cancel_requested_at=_iso_now(),
                    cancel_requested_by=actor_key,
                    cancel_request_event_id=cancel_request_event_id,
                )
                return CancelRequestResult.claimed_cancel_requested
        return CancelRequestResult.nothing_to_cancel

    def is_cancel_requested(self, data_dir: Path, item_id: str) -> bool:
        item = self._state(data_dir).work_items.get(item_id)
        return bool(item and item.cancel_requested_at)

    def has_claimed_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        return any(
            item.conversation_key == conversation_key and item.state == "claimed"
            for item in self._state(data_dir).work_items.values()
        )

    def has_queued_or_claimed(self, data_dir: Path, conversation_key: str) -> bool:
        return any(
            item.conversation_key == conversation_key and item.state in {"queued", "claimed"}
            for item in self._state(data_dir).work_items.values()
        )

    def get_update_payload(self, data_dir: Path, event_id: str) -> str | None:
        return self._state(data_dir).update_payloads.get(event_id)

    def get_user_access(self, data_dir: Path, actor_key: str) -> str | None:
        record = self._state(data_dir).user_access.get(actor_key)
        return None if record is None else record.access

    def set_user_access(
        self,
        data_dir: Path,
        actor_key: str,
        access: str,
        reason: str = "",
        granted_by: str = "",
    ) -> None:
        self._state(data_dir).user_access[actor_key] = UserAccessRecord(
            actor_key=actor_key,
            access=access,
            reason=reason,
            granted_by=granted_by,
            granted_at=_utc_now().timestamp(),
        )

    def list_user_access(self, data_dir: Path) -> list[UserAccessRecord]:
        return list(self._state(data_dir).user_access.values())

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
        self._state(data_dir).usage_records.append(
            UsageRecord(
                conversation_key=conversation_key,
                work_item_id=work_item_id,
                provider=provider,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                recorded_at=_utc_now().timestamp(),
            )
        )

    def get_usage_since(self, data_dir: Path, *, since_epoch: float) -> list[UsageRecord]:
        return [record for record in self._state(data_dir).usage_records if record.recorded_at >= since_epoch]

    def get_work_items_for_chat(self, data_dir: Path, conversation_key: str) -> list[WorkItemRecord]:
        return [
            item
            for item in self._state(data_dir).work_items.values()
            if item.conversation_key == conversation_key
        ]

    def get_queue_snapshot(self, data_dir: Path) -> QueueSnapshot:
        items = list(self._state(data_dir).work_items.values())
        return QueueSnapshot(
            fresh_queued_count=sum(item.state == "queued" and item.dispatch_mode == "fresh" for item in items),
            recovery_queued_count=sum(item.state == "queued" and item.dispatch_mode == "recovery" for item in items),
            claimed_count=sum(item.state == "claimed" for item in items),
            pending_recovery_count=sum(item.state == "pending_recovery" for item in items),
            cancel_requested_claimed_count=sum(item.state == "claimed" and bool(item.cancel_requested_at) for item in items),
            oldest_fresh_queued_at=min((item.created_at for item in items if item.state == "queued" and item.dispatch_mode == "fresh"), default=None),
            oldest_recovery_queued_at=min((item.created_at for item in items if item.state == "queued" and item.dispatch_mode == "recovery"), default=None),
            oldest_claimed_at=min((item.claimed_at for item in items if item.state == "claimed" and item.claimed_at), default=None),
            oldest_pending_recovery_at=min((item.claimed_at for item in items if item.state == "pending_recovery" and item.claimed_at), default=None),
        )

    def upsert_worker_heartbeat(self, data_dir: Path, heartbeat: WorkerHeartbeat) -> None:
        self._state(data_dir).heartbeats[heartbeat.worker_id] = heartbeat

    def clear_worker_heartbeat(self, data_dir: Path, worker_id: str) -> None:
        self._state(data_dir).heartbeats.pop(worker_id, None)

    def list_worker_heartbeats(self, data_dir: Path) -> list[WorkerHeartbeat]:
        return list(self._state(data_dir).heartbeats.values())

    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None:
        state = self._state(data_dir)
        item = state.work_items[item_id]
        state.work_items[item_id] = replace(item, state="pending_recovery", worker_id=None, claimed_at=None)

    def get_pending_recovery_for_update(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
    ) -> WorkItemRecord | None:
        item_id = self._state(data_dir).event_index.get(event_id)
        if item_id is None:
            return None
        item = self._state(data_dir).work_items[item_id]
        if item.conversation_key != conversation_key or item.state != "pending_recovery":
            return None
        return item

    def get_latest_pending_recovery(
        self,
        data_dir: Path,
        conversation_key: str,
    ) -> WorkItemRecord | None:
        candidates = [
            item for item in self._state(data_dir).work_items.values()
            if item.conversation_key == conversation_key and item.state == "pending_recovery"
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.created_at)[-1]

    def supersede_pending_recovery(self, data_dir: Path, conversation_key: str) -> int:
        state = self._state(data_dir)
        removed = 0
        for item_id, item in list(state.work_items.items()):
            if item.conversation_key == conversation_key and item.state == "pending_recovery":
                del state.work_items[item_id]
                removed += 1
        return removed

    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult:
        state = self._state(data_dir)
        item = state.work_items.get(item_id)
        if item is None or item.state in {"done", "failed"}:
            return DiscardResult.already_handled
        del state.work_items[item_id]
        return DiscardResult.success

    def reclaim_for_replay(
        self,
        data_dir: Path,
        item_id: str,
        worker_id: str,
        *,
        ignore_claimed_item_id: str = "",
    ) -> WorkItemRecord | None:
        del ignore_claimed_item_id
        state = self._state(data_dir)
        item = state.work_items.get(item_id)
        if item is None or item.state != "pending_recovery":
            return None
        claimed = replace(item, state="claimed", worker_id=worker_id, claimed_at=_iso_now(), dispatch_mode="recovery")
        state.work_items[item_id] = claimed
        return claimed

    def recover_stale_claims(
        self,
        data_dir: Path,
        *,
        lease_ttl_seconds: int = 300,
    ) -> int:
        cutoff = _utc_now() - timedelta(seconds=lease_ttl_seconds)
        state = self._state(data_dir)
        recovered = 0
        for item_id, item in list(state.work_items.items()):
            if item.state != "claimed" or not item.claimed_at:
                continue
            try:
                claimed_at = datetime.fromisoformat(item.claimed_at)
            except ValueError:
                claimed_at = _utc_now()
            if claimed_at <= cutoff:
                state.work_items[item_id] = replace(
                    item,
                    state="queued",
                    worker_id=None,
                    claimed_at=None,
                    dispatch_mode=item.dispatch_mode or "fresh",
                )
                recovered += 1
        return recovered

    def purge_old(
        self,
        data_dir: Path,
        *,
        older_than_seconds: int = 7 * 24 * 3600,
    ) -> int:
        cutoff = _utc_now() - timedelta(seconds=older_than_seconds)
        state = self._state(data_dir)
        removed = 0
        for item_id, item in list(state.work_items.items()):
            timestamp = item.completed_at or item.created_at
            try:
                moment = datetime.fromisoformat(timestamp) if timestamp else _utc_now()
            except ValueError:
                moment = _utc_now()
            if item.state in {"done", "failed"} and moment <= cutoff:
                del state.work_items[item_id]
                removed += 1
        return removed

    def purge_old_usage(
        self,
        data_dir: Path,
        *,
        older_than_seconds: int = 30 * 24 * 3600,
    ) -> int:
        cutoff = _utc_now().timestamp() - older_than_seconds
        state = self._state(data_dir)
        before = len(state.usage_records)
        state.usage_records = [record for record in state.usage_records if record.recorded_at > cutoff]
        return before - len(state.usage_records)
