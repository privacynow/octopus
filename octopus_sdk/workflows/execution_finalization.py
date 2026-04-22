"""SDK-owned post-execution finalization workflow."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from octopus_sdk.config import BotConfigBase
from octopus_sdk.deferred_notifications import DeferredNotification, DeferredNotificationPort
from octopus_sdk.execution import RequestExecutionOutcome
from octopus_sdk.formatting import summarize_text
from octopus_sdk.protocols import ProtocolArtifactObservationRecord, ProtocolStageRuntimeContractRecord
from octopus_sdk.registry_inspection import RegistryInspectionPort
from octopus_sdk.registry.models import RoutedTaskResult, RoutedTaskUpdate
from octopus_sdk.sessions import SessionState
from octopus_sdk.task_routing import TaskRoutingPort
from octopus_sdk.time_utils import utc_now_iso
from octopus_sdk.webhooks import CompletionWebhookPort
from octopus_sdk.workflows.delegation import finalize_resumed_delegation

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizationContext:
    config: BotConfigBase
    item_id: str
    conversation_key: str
    runtime_chat: int | str
    conversation_ref: str
    chat_id: int = 0
    routed_task_id: str = ""
    authority_ref: str = ""
    skip_approval: bool = False
    last_status_text: str = ""
    load_session: Callable[[int | str], SessionState] | None = None
    save_session: Callable[[int | str, SessionState], None] | None = None
    task_routing: TaskRoutingPort | None = None
    record_usage: Callable[..., None] | None = None
    completion_webhook_sender: CompletionWebhookPort | None = None
    deferred_notifications: DeferredNotificationPort | None = None
    deferred_target_agent_id: str = ""
    deferred_actor_key: str = ""
    deferred_title: str = ""
    registry_inspection: RegistryInspectionPort | None = None
    working_dir_resolver: Callable[[int | str], str] | None = None


@dataclass(frozen=True)
class FinalizationOutcome:
    delegation_status: str = ""
    routed_result_status: str = ""
    usage_status: str = "skipped"
    timeline_status: str = "skipped"
    webhook_status: str = "skipped"
    deferred_notification_status: str = "skipped"


def _result_full_text(outcome: RequestExecutionOutcome, *, last_status_text: str) -> str:
    return outcome.reply_text or html.unescape(last_status_text or "")


def _routed_result_authority_ref(context: FinalizationContext) -> str:
    return context.authority_ref


def _routed_result_delivery_failure_summary(result_status: str) -> str:
    if result_status == "completed":
        return "Execution completed, but the result could not be delivered to the requesting conversation."
    return summarize_text(
        f"Execution finished with status {result_status}, but the result could not be delivered to the requesting conversation."
    )


async def _publish_routed_result_delivery_failure(
    *,
    context: FinalizationContext,
    authority_ref: str,
    result_status: str,
) -> None:
    if context.task_routing is None or not context.routed_task_id:
        return
    try:
        await context.task_routing.update_routed_task_status(
            update=RoutedTaskUpdate(
                routed_task_id=context.routed_task_id,
                status="failed",
                transition_id=uuid4().hex,
                summary=_routed_result_delivery_failure_summary(result_status),
            ),
            authority_ref=authority_ref,
        )
    except Exception:
        log.warning(
            "Fallback routed-task status update failed for %s",
            context.routed_task_id,
            exc_info=True,
    )


def _safe_workspace_artifact_path(base_dir: str, relative_path: str) -> Path | None:
    base = Path(base_dir).expanduser().resolve()
    candidate = Path(relative_path)
    if candidate.is_absolute():
        return None
    resolved = (base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        return None
    return resolved


def _artifact_observation_for_path(
    *,
    base_dir: str,
    artifact_key: str,
    artifact_kind: str,
    relative_path: str,
) -> ProtocolArtifactObservationRecord:
    safe_path = _safe_workspace_artifact_path(base_dir, relative_path)
    if safe_path is None:
        return ProtocolArtifactObservationRecord(
            artifact_key=artifact_key,
            artifact_kind=artifact_kind,
            path=relative_path,
            exists=False,
            verification_state="missing",
        )
    try:
        stat = safe_path.stat()
    except FileNotFoundError:
        return ProtocolArtifactObservationRecord(
            artifact_key=artifact_key,
            artifact_kind=artifact_kind,
            path=relative_path,
            exists=False,
            verification_state="missing",
        )
    except Exception:
        log.warning("Failed to stat protocol artifact %s", safe_path, exc_info=True)
        return ProtocolArtifactObservationRecord(
            artifact_key=artifact_key,
            artifact_kind=artifact_kind,
            path=relative_path,
            exists=False,
            verification_state="missing",
        )
    if not safe_path.is_file():
        return ProtocolArtifactObservationRecord(
            artifact_key=artifact_key,
            artifact_kind=artifact_kind,
            path=relative_path,
            exists=False,
            verification_state="missing",
        )
    digest = hashlib.sha256()
    with safe_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return ProtocolArtifactObservationRecord(
        artifact_key=artifact_key,
        artifact_kind=artifact_kind,
        path=relative_path,
        exists=True,
        size_bytes=int(stat.st_size or 0),
        content_hash=digest.hexdigest(),
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        verification_state="verified",
    )


async def _protocol_artifact_payloads(
    context: FinalizationContext,
    *,
    working_dir: str = "",
) -> list[dict[str, object]]:
    if (
        not context.routed_task_id
        or not context.authority_ref
        or context.registry_inspection is None
    ):
        return []
    try:
        task = await context.registry_inspection.get_task(context.authority_ref, context.routed_task_id)
    except Exception:
        log.warning(
            "Failed to inspect routed task %s for protocol artifact observations",
            context.routed_task_id,
            exc_info=True,
        )
        return []
    request_payload = task.request.as_dict() if task.request is not None else {}
    internal_context = request_payload.get("internal_context", {})
    if not isinstance(internal_context, dict):
        return []
    contract_raw = internal_context.get("protocol_stage_contract")
    if not isinstance(contract_raw, dict):
        return []
    try:
        contract = ProtocolStageRuntimeContractRecord.model_validate(contract_raw)
    except Exception:
        log.warning(
            "Invalid protocol stage contract on routed task %s",
            context.routed_task_id,
            exc_info=True,
        )
        return []
    working_dir = str(working_dir or "").strip()
    if not working_dir and context.working_dir_resolver is not None:
        working_dir = str(context.working_dir_resolver(context.runtime_chat) or "").strip()
    if not working_dir:
        return []
    observations = [
        _artifact_observation_for_path(
            base_dir=working_dir,
            artifact_key=artifact.artifact_key,
            artifact_kind=artifact.artifact_kind,
            relative_path=artifact.path,
        )
        for artifact in contract.output_artifacts
    ]
    return [item.model_dump(mode="json") for item in observations]


async def finalize_execution(
    outcome: RequestExecutionOutcome | None,
    *,
    context: FinalizationContext,
) -> FinalizationOutcome:
    if outcome is None:
        return FinalizationOutcome()

    delegation_status = ""
    if (
        context.skip_approval
        and context.conversation_ref
        and context.load_session is not None
        and context.save_session is not None
    ):
        session = context.load_session(context.runtime_chat)
        finalized = finalize_resumed_delegation(
            session.pending_delegation,
            conversation_ref=context.conversation_ref,
        )
        delegation_status = finalized.status
        if finalized.status == "cleared_after_resume":
            session.pending_delegation = None
            context.save_session(context.runtime_chat, session)

    routed_result_status = ""
    authority_ref = _routed_result_authority_ref(context)
    if context.routed_task_id and context.task_routing is not None and authority_ref:
        full_text = _result_full_text(outcome, last_status_text=context.last_status_text)
        result_status = "completed" if outcome.status in {"completed", "completed_with_denials"} else outcome.status
        working_dir = str(outcome.working_dir or "").strip()
        if not working_dir and context.working_dir_resolver is not None:
            working_dir = str(context.working_dir_resolver(context.runtime_chat) or "").strip()
        artifact_payloads = await _protocol_artifact_payloads(context, working_dir=working_dir)
        try:
            report = await context.task_routing.report_routed_task_result(
                routed_task_id=context.routed_task_id,
                authority_ref=authority_ref,
                result=RoutedTaskResult(
                    routed_task_id=context.routed_task_id,
                    status=result_status,
                    transition_id=uuid4().hex,
                    summary=summarize_text(full_text or outcome.error_text or result_status),
                    full_text=full_text or outcome.error_text,
                    artifacts=artifact_payloads,
                    follow_up_questions=(),
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    cached_prompt_tokens=outcome.cached_prompt_tokens,
                    cached_completion_tokens=outcome.cached_completion_tokens,
                    cost_usd=outcome.cost_usd,
                    provider=context.config.provider_name,
                    working_dir=working_dir,
                ),
            )
            if report.status == "reported":
                routed_result_status = "reported"
            else:
                routed_result_status = "report_failed"
                await _publish_routed_result_delivery_failure(
                    context=context,
                    authority_ref=authority_ref,
                    result_status=result_status,
                )
                log.error(
                    "Failed to report routed task result for %s: %s",
                    context.routed_task_id,
                    report.error or report.status,
                )
        except Exception:
            routed_result_status = "report_failed"
            await _publish_routed_result_delivery_failure(
                context=context,
                authority_ref=authority_ref,
                result_status=result_status,
            )
            log.error(
                "Failed to report routed task result for %s",
                context.routed_task_id,
                exc_info=True,
            )

    usage_status = "skipped"
    timeline_status = "skipped"
    if outcome.status in {"completed", "completed_with_denials"} and context.record_usage is not None:
        try:
            context.record_usage(
                context.config.data_dir,
                conversation_key=context.conversation_key,
                work_item_id=context.item_id,
                provider=context.config.provider_name,
                prompt_tokens=outcome.prompt_tokens,
                completion_tokens=outcome.completion_tokens,
                cost_usd=outcome.cost_usd,
            )
            usage_status = "recorded"
        except Exception:
            usage_status = "record_failed_non_blocking"
            log.warning(
                "Usage accounting failed for work item %s (non-blocking)",
                context.item_id,
                exc_info=True,
            )

    webhook_status = "skipped"
    completion_webhook_url = str(getattr(context.config, "completion_webhook_url", "") or "")
    if (
        completion_webhook_url
        and outcome.status != "delegation_proposed"
        and not context.routed_task_id
        and context.completion_webhook_sender is not None
    ):
        summary = (outcome.reply_text or outcome.error_text or "")[:200]
        completed_at = utc_now_iso()
        asyncio.create_task(
            context.completion_webhook_sender(
                completion_webhook_url,
                chat_id=context.chat_id,
                conversation_ref=context.conversation_ref,
                status=outcome.status,
                summary=summary,
                completed_at=completed_at,
            )
        )
        webhook_status = "scheduled"

    deferred_notification_status = "skipped"
    if context.routed_task_id:
        target_agent_id = str(context.deferred_target_agent_id or "").strip()
        actor_key = str(context.deferred_actor_key or "").strip()
        if target_agent_id and actor_key:
            full_text = _result_full_text(outcome, last_status_text=context.last_status_text)
            result_status = "completed" if outcome.status in {"completed", "completed_with_denials"} else "failed"
            verb = "completed" if result_status == "completed" else "failed"
            title = str(context.deferred_title or "Task").strip() or "Task"
            summary = summarize_text(full_text or outcome.error_text or result_status, limit=240)
            content = f"Task '{title}' {verb}. Summary: {summary}".strip()
            try:
                context.deferred_notifications.enqueue(
                    context.config.data_dir,
                    DeferredNotification(
                        target_agent_id=target_agent_id,
                        actor_key=actor_key,
                        content=content,
                    ),
                )
                deferred_notification_status = "queued"
            except Exception:
                deferred_notification_status = "queue_failed"
                log.warning(
                    "Failed to enqueue deferred notification for routed task %s",
                    context.routed_task_id,
                    exc_info=True,
                )

    return FinalizationOutcome(
        delegation_status=delegation_status,
        routed_result_status=routed_result_status,
        usage_status=usage_status,
        timeline_status=timeline_status,
        webhook_status=webhook_status,
        deferred_notification_status=deferred_notification_status,
    )
