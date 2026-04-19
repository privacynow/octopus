"""Shared protocol runtime helpers for the registry control plane."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from octopus_sdk.protocols import (
    ProtocolAccessContextRecord,
    ProtocolArtifactRecord,
    ProtocolDefinitionDocumentRecord,
    ProtocolEngineDecisionRecord,
    ProtocolParticipantResolutionRecord,
    ProtocolRunDetailRecord,
    ProtocolRunRecord,
    ProtocolStageExecutionRecord,
    TargetSelector,
)
from octopus_sdk.protocols.engine import ProtocolRunEngine

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


def resolve_protocol_participant(
    *,
    selector: TargetSelector,
    resolve_selector: Callable[[TargetSelector], Mapping[str, object]],
) -> ProtocolParticipantResolutionRecord:
    try:
        resolved = resolve_selector(selector)
    except Exception as exc:
        return ProtocolParticipantResolutionRecord(
            selector=selector,
            outcome="error",
            reason=str(exc),
        )
    return ProtocolParticipantResolutionRecord(
        selector=selector,
        resolved_agent_id=str(resolved.get("agent_id", "") or ""),
        resolved_authority_ref=str(resolved.get("authority_ref", "") or ""),
        outcome="ok",
        reason="",
    )


def evaluate_protocol_dispatch(
    *,
    protocol_engine: ProtocolRunEngine,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution: ProtocolStageExecutionRecord,
    stage_executions: list[ProtocolStageExecutionRecord],
    artifacts: list[ProtocolArtifactRecord],
    previous_feedback: str,
    now: str,
    resolve_selector: Callable[[TargetSelector], Mapping[str, object]],
    lease_ttl_seconds: int = 900,
) -> ProtocolEngineDecisionRecord:
    stage = document.stage(stage_execution.stage_key)
    dispatch = protocol_engine.dispatch_preflight(
        document=document,
        run=run,
        stage=stage,
        stage_executions=stage_executions,
        now=now,
        lease_owner=stage_execution.protocol_stage_execution_id,
        lease_ttl_seconds=lease_ttl_seconds,
    )
    if not dispatch.ok:
        return protocol_engine.dispatch_blocked(
            run=run,
            stage_execution=stage_execution,
            error_code=dispatch.error_code,
            error_detail=dispatch.error_detail,
        )
    try:
        selector = protocol_engine.dispatch_target_selector(
            run=run,
            participant=document.participant(stage.participant_key),
        )
    except ValueError as exc:
        return protocol_engine.dispatch_blocked(
            run=run,
            stage_execution=stage_execution,
            error_code="PARTICIPANT_SELECTOR_REQUIRED",
            error_detail=str(exc),
        )
    resolution = resolve_protocol_participant(selector=selector, resolve_selector=resolve_selector)
    return protocol_engine.evaluate_dispatch_resolution(
        document=document,
        run=run,
        stage_execution=stage_execution,
        artifacts=artifacts,
        previous_feedback=previous_feedback,
        now=now,
        resolution=resolution,
        timeout_at=dispatch.timeout_at,
        lease_owner=dispatch.lease_owner,
        lease_expires_at=dispatch.lease_expires_at,
    )
