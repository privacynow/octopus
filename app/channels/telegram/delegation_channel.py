"""Telegram delegation channel helpers."""

from __future__ import annotations

from typing import Any

from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.session_io import save as save_session
from app.channels.telegram.state import TelegramRuntime
from app.agents.bridge import publish_timeline_event, summarize_text, telegram_conversation_ref
from app.agents.delegation import (
    DelegationRuntime,
    handle_delegation_approve as handle_channel_delegation_approve,
    handle_delegation_cancel as handle_channel_delegation_cancel,
)
from app.agents.types import TimelineEvent
from app.session_state import PendingDelegation, SessionState
from app.workflows.delegation.coordination import build_delegation_plan
from app.workflows.execution.contracts import RequestExecutionOutcome


def delegation_reply_markup(chat_id: int):
    return telegram_presenters.delegation_reply_markup(chat_id)


class DelegationCallbackHandle:
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del text, kwargs
        return None

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs
        return None


class DelegationCallbackChannel:
    def __init__(self, query) -> None:
        self._query = query

    async def send_text(self, text: str, **kwargs: Any) -> DelegationCallbackHandle:
        await self._query.edit_message_text(text, **kwargs)
        return DelegationCallbackHandle()


async def publish_delegation_proposed_event(
    runtime: TelegramRuntime,
    message,
    delegation: PendingDelegation,
) -> None:
    body = "\n".join(
        [
            "Delegation plan:",
            *[
                f"{index}. {task.title or task.routed_task_id} -> {task.target_agent_id or 'unassigned'}"
                for index, task in enumerate(delegation.tasks, start=1)
            ],
        ]
    )
    event = TimelineEvent(
        event_id=f"delegation-proposed:{delegation.conversation_ref}:{int(delegation.created_at * 1000)}",
        conversation_id=delegation.conversation_ref,
        kind="delegation_proposed",
        title="Delegation plan proposed",
        body=body,
        status=delegation.status,
    )
    publisher = getattr(message, "publish_timeline", None)
    if callable(publisher):
        await publisher(event)
        return
    await publish_timeline_event(
        runtime.config,
        conversation_ref=delegation.conversation_ref,
        kind=event.kind,
        title=event.title,
        body=event.body,
        status=event.status,
        event_id=event.event_id,
    )


async def propose_delegation_plan(
    runtime: TelegramRuntime,
    chat_id: int,
    message,
    session: SessionState,
    *,
    conversation_ref: str,
    result,
) -> RequestExecutionOutcome:
    title = result.delegation_title.strip() or summarize_text(result.text) or "Delegation plan"
    delegation = build_delegation_plan(
        conversation_ref,
        title,
        result.delegation_resume_instruction,
        list(result.delegation_tasks),
    )
    session.pending_delegation = delegation
    save_session(runtime, chat_id, session)
    await publish_delegation_proposed_event(runtime, message, delegation)

    send_plan = getattr(message, "send_text", None) or getattr(message, "reply_text")
    rendered = telegram_presenters.delegation_plan_message(delegation)
    await send_plan(
        rendered.text,
        parse_mode=rendered.parse_mode,
        reply_markup=delegation_reply_markup(chat_id),
    )
    return RequestExecutionOutcome(status="delegation_proposed")


def parse_delegation_callback(data: str) -> tuple[str, int] | None:
    parts = (data or "").split(":", 1)
    if len(parts) != 2:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


async def handle_delegation_approve(
    runtime: TelegramRuntime,
    chat_id: int,
    query,
    *,
    delegation_runtime: DelegationRuntime,
) -> None:
    conversation_ref = telegram_conversation_ref(runtime.config, chat_id)
    await handle_channel_delegation_approve(
        chat_id,
        conversation_ref,
        DelegationCallbackChannel(query),
        runtime=delegation_runtime,
        retry_markup=delegation_reply_markup(chat_id),
    )


async def handle_delegation_cancel(
    runtime: TelegramRuntime,
    chat_id: int,
    query,
    *,
    delegation_runtime: DelegationRuntime,
) -> None:
    conversation_ref = telegram_conversation_ref(runtime.config, chat_id)
    await handle_channel_delegation_cancel(
        chat_id,
        conversation_ref,
        DelegationCallbackChannel(query),
        runtime=delegation_runtime,
    )
