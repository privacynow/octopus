"""Shared protocol runtime helpers for the registry control plane."""

from __future__ import annotations

import logging
from typing import Any

from octopus_sdk.protocols import ProtocolAccessContextRecord, ProtocolRunDetailRecord

from .store_base import AbstractRegistryStore
from .ws import WebSocketManager

log = logging.getLogger(__name__)


def internal_protocol_access() -> ProtocolAccessContextRecord:
    return ProtocolAccessContextRecord(
        actor_ref="registry-service",
        roles=["admin", "operator", "auditor", "publisher", "author"],
    )


def protocol_run_event_payload(
    detail: ProtocolRunDetailRecord,
    *,
    event_kind: str,
    reason: str,
    routed_task_id: str = "",
) -> dict[str, Any]:
    run = detail.run
    latest_stage = detail.stage_executions[0] if detail.stage_executions else None
    return {
        "topic": f"protocol-run:{run.protocol_run_id}",
        "event_kind": event_kind,
        "reason": reason,
        "protocol_run_id": run.protocol_run_id,
        "protocol_id": run.protocol_id,
        "status": run.status,
        "current_stage_key": run.current_stage_key,
        "version": run.version,
        "blocked_code": run.blocked_code,
        "blocked_detail": run.blocked_detail,
        "termination_summary": run.termination_summary,
        "last_transition_at": run.last_transition_at,
        "latest_stage_key": latest_stage.stage_key if latest_stage is not None else "",
        "latest_stage_status": latest_stage.status if latest_stage is not None else "",
        "routed_task_id": routed_task_id,
    }


async def broadcast_protocol_run_event(
    store: AbstractRegistryStore,
    ws_manager: WebSocketManager,
    *,
    run_id: str,
    event_kind: str,
    reason: str,
    routed_task_id: str = "",
) -> None:
    token = str(run_id or "").strip()
    if not token:
        return
    try:
        detail = store.get_protocol_run(token, access=internal_protocol_access())
    except Exception:
        log.warning("Failed to load protocol run %s for realtime event %s", token, event_kind, exc_info=True)
        return
    await ws_manager.broadcast_topic_event(
        f"protocol-run:{token}",
        protocol_run_event_payload(detail, event_kind=event_kind, reason=reason, routed_task_id=routed_task_id),
    )
