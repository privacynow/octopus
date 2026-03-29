"""Registry-local runtime-health serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from octopus_sdk.work_queue import QueueSnapshot, WorkerHeartbeat

_RUNTIME_HEALTH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SharedRuntimeSnapshot:
    queue: QueueSnapshot = QueueSnapshot()
    workers: tuple[WorkerHeartbeat, ...] = ()
    healthy_worker_count: int = 0
    stale_worker_count: int = 0


@dataclass(frozen=True)
class RuntimeDiagnostic:
    level: str
    code: str
    message: str


@dataclass(frozen=True)
class RuntimeHealthSummary:
    status: str = "healthy"
    healthy_worker_count: int = 0
    stale_worker_count: int = 0
    fresh_queued_count: int = 0
    claimed_count: int = 0
    pending_recovery_count: int = 0
    recovery_queued_count: int = 0
    oldest_claim_age_seconds: int | None = None
    warning_count: int = 0
    error_count: int = 0


@dataclass(frozen=True)
class RuntimeHealthReport:
    schema_version: int = _RUNTIME_HEALTH_SCHEMA_VERSION
    generated_at: str = ""
    summary: RuntimeHealthSummary = RuntimeHealthSummary()
    snapshot: SharedRuntimeSnapshot | None = None
    diagnostics: tuple[RuntimeDiagnostic, ...] = ()


def report_to_dict(report: RuntimeHealthReport) -> dict[str, Any]:
    return _to_wire(report)


def report_from_dict(payload: dict[str, Any] | None) -> RuntimeHealthReport | None:
    if not payload:
        return None
    summary = payload.get("summary") or {}
    snapshot = payload.get("snapshot")
    diagnostics = tuple(
        RuntimeDiagnostic(
            level=str(item.get("level", "info")),
            code=str(item.get("code", "")),
            message=str(item.get("message", "")),
        )
        for item in (payload.get("diagnostics") or [])
        if isinstance(item, dict)
    )
    hydrated_snapshot: SharedRuntimeSnapshot | None = None
    if isinstance(snapshot, dict):
        queue_payload = snapshot.get("queue") or {}
        workers_payload = snapshot.get("workers") or []
        hydrated_snapshot = SharedRuntimeSnapshot(
            queue=QueueSnapshot(
                fresh_queued_count=int(queue_payload.get("fresh_queued_count", 0) or 0),
                recovery_queued_count=int(queue_payload.get("recovery_queued_count", 0) or 0),
                claimed_count=int(queue_payload.get("claimed_count", 0) or 0),
                pending_recovery_count=int(queue_payload.get("pending_recovery_count", 0) or 0),
                cancel_requested_claimed_count=int(
                    queue_payload.get("cancel_requested_claimed_count", 0) or 0
                ),
                oldest_fresh_queued_at=queue_payload.get("oldest_fresh_queued_at"),
                oldest_recovery_queued_at=queue_payload.get("oldest_recovery_queued_at"),
                oldest_claimed_at=queue_payload.get("oldest_claimed_at"),
                oldest_pending_recovery_at=queue_payload.get("oldest_pending_recovery_at"),
            ),
            workers=tuple(
                WorkerHeartbeat(
                    worker_id=str(worker.get("worker_id", "")),
                    process_role=str(worker.get("process_role", "")),
                    started_at=str(worker.get("started_at", "")),
                    last_seen_at=str(worker.get("last_seen_at", "")),
                    current_item_id=str(worker.get("current_item_id", "")),
                    current_conversation_key=worker.get("current_conversation_key"),
                    current_kind=str(worker.get("current_kind", "")),
                    items_processed=int(worker.get("items_processed", 0) or 0),
                    stale_recoveries_seen=int(worker.get("stale_recoveries_seen", 0) or 0),
                    last_error=str(worker.get("last_error", "")),
                )
                for worker in workers_payload
                if isinstance(worker, dict)
            ),
            healthy_worker_count=int(snapshot.get("healthy_worker_count", 0) or 0),
            stale_worker_count=int(snapshot.get("stale_worker_count", 0) or 0),
        )
    return RuntimeHealthReport(
        schema_version=int(payload.get("schema_version", _RUNTIME_HEALTH_SCHEMA_VERSION) or _RUNTIME_HEALTH_SCHEMA_VERSION),
        generated_at=str(payload.get("generated_at", "") or ""),
        summary=RuntimeHealthSummary(
            status=str(summary.get("status", "healthy")),
            healthy_worker_count=int(summary.get("healthy_worker_count", 0) or 0),
            stale_worker_count=int(summary.get("stale_worker_count", 0) or 0),
            fresh_queued_count=int(summary.get("fresh_queued_count", 0) or 0),
            claimed_count=int(summary.get("claimed_count", 0) or 0),
            pending_recovery_count=int(summary.get("pending_recovery_count", 0) or 0),
            recovery_queued_count=int(summary.get("recovery_queued_count", 0) or 0),
            oldest_claim_age_seconds=(
                None
                if summary.get("oldest_claim_age_seconds") in (None, "")
                else int(summary.get("oldest_claim_age_seconds", 0))
            ),
            warning_count=int(summary.get("warning_count", 0) or 0),
            error_count=int(summary.get("error_count", 0) or 0),
        ),
        snapshot=hydrated_snapshot,
        diagnostics=diagnostics,
    )


def _to_wire(value: Any) -> Any:
    if isinstance(value, RuntimeHealthReport):
        return {
            "schema_version": value.schema_version,
            "generated_at": value.generated_at,
            "summary": _to_wire(value.summary),
            "snapshot": _to_wire(value.snapshot),
            "diagnostics": [_to_wire(item) for item in value.diagnostics],
        }
    if isinstance(value, RuntimeHealthSummary):
        return {
            "status": value.status,
            "healthy_worker_count": value.healthy_worker_count,
            "stale_worker_count": value.stale_worker_count,
            "fresh_queued_count": value.fresh_queued_count,
            "claimed_count": value.claimed_count,
            "pending_recovery_count": value.pending_recovery_count,
            "recovery_queued_count": value.recovery_queued_count,
            "oldest_claim_age_seconds": value.oldest_claim_age_seconds,
            "warning_count": value.warning_count,
            "error_count": value.error_count,
        }
    if isinstance(value, SharedRuntimeSnapshot):
        return {
            "queue": _to_wire(value.queue),
            "workers": [_to_wire(item) for item in value.workers],
            "healthy_worker_count": value.healthy_worker_count,
            "stale_worker_count": value.stale_worker_count,
        }
    if isinstance(value, QueueSnapshot):
        return {
            "fresh_queued_count": value.fresh_queued_count,
            "recovery_queued_count": value.recovery_queued_count,
            "claimed_count": value.claimed_count,
            "pending_recovery_count": value.pending_recovery_count,
            "cancel_requested_claimed_count": value.cancel_requested_claimed_count,
            "oldest_fresh_queued_at": value.oldest_fresh_queued_at,
            "oldest_recovery_queued_at": value.oldest_recovery_queued_at,
            "oldest_claimed_at": value.oldest_claimed_at,
            "oldest_pending_recovery_at": value.oldest_pending_recovery_at,
        }
    if isinstance(value, WorkerHeartbeat):
        return {
            "worker_id": value.worker_id,
            "process_role": value.process_role,
            "started_at": value.started_at,
            "last_seen_at": value.last_seen_at,
            "current_item_id": value.current_item_id,
            "current_conversation_key": value.current_conversation_key,
            "current_kind": value.current_kind,
            "items_processed": value.items_processed,
            "stale_recoveries_seen": value.stale_recoveries_seen,
            "last_error": value.last_error,
        }
    if isinstance(value, RuntimeDiagnostic):
        return {
            "level": value.level,
            "code": value.code,
            "message": value.message,
        }
    return value
