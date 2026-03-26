"""Concern-owned post-execution finalization workflow."""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from octopus_sdk.registry.models import RoutedTaskResult, RoutedTaskUpdate
from app.formatting import summarize_text
from octopus_sdk.task_routing import TaskRoutingPort
from octopus_sdk.sessions import SessionState
from octopus_sdk.workflows.delegation import finalize_resumed_delegation
from octopus_sdk.execution import RequestExecutionOutcome

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizationContext:
    config: Any
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
    completion_webhook_sender: Callable[..., Awaitable[None]] | None = None


@dataclass(frozen=True)
class FinalizationOutcome:
    delegation_status: str = ""
    routed_result_status: str = ""
    usage_status: str = "skipped"
    timeline_status: str = "skipped"
    webhook_status: str = "skipped"


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
        result_status = (
            "completed"
            if outcome.status in {"completed", "completed_with_denials"}
            else outcome.status
        )
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
                    artifacts=(),
                    follow_up_questions=(),
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    cost_usd=outcome.cost_usd,
                    provider=context.config.provider_name,
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
    if outcome.status in {"completed", "completed_with_denials"}:
        if context.record_usage is not None:
            try:
                # Usage accounting is explicitly non-blocking. The user-visible
                # execution already succeeded, and worker_loop owns durable
                # completion. Telemetry failure must not convert success into
                # a failed work item.
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
    if (
        context.config.completion_webhook_url
        and outcome.status != "delegation_proposed"
        and not context.routed_task_id
    ):
        sender = context.completion_webhook_sender
        if sender is None:
            from app.webhook import fire_completion_webhook as sender

        summary = (outcome.reply_text or outcome.error_text or "")[:200]
        completed_at = datetime.now(timezone.utc).isoformat()
        asyncio.create_task(
            sender(
                context.config.completion_webhook_url,
                chat_id=context.chat_id,
                conversation_ref=context.conversation_ref,
                status=outcome.status,
                summary=summary,
                completed_at=completed_at,
            )
        )
        webhook_status = "scheduled"

    return FinalizationOutcome(
        delegation_status=delegation_status,
        routed_result_status=routed_result_status,
        usage_status=usage_status,
        timeline_status=timeline_status,
        webhook_status=webhook_status,
    )
