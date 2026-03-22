"""Telegram delegation channel helpers."""

from __future__ import annotations

from typing import Any

from app.formatting import summarize_text
from app.identity import telegram_conversation_ref
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.session_io import save as save_session
from app.channels.telegram.state import TelegramRuntime
from app.agents.delegation import (
    DelegationRuntime,
    handle_delegation_approve as handle_channel_delegation_approve,
    handle_delegation_cancel as handle_channel_delegation_cancel,
    preview_delegation_targets,
)
from app.session_state import PendingDelegation, SessionState
from app.workflows.delegation.coordination import build_delegation_plan
from app.channels.telegram.session_io import load as load_session
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


class _AutoSubmitEgress:
    """Egress adapter for autonomous delegation auto-submit.

    Sends status text inline via the message object, stripping reply_markup
    since there are no buttons in autonomous mode.
    """

    def __init__(self, message) -> None:
        self._message = message

    async def send_text(self, text: str, **kwargs: Any) -> DelegationCallbackHandle:
        kwargs.pop("reply_markup", None)
        send = getattr(self._message, "send_text", None) or getattr(self._message, "reply_text")
        await send(text, **kwargs)
        return DelegationCallbackHandle()


async def publish_delegation_proposed_event(
    runtime: TelegramRuntime,
    message,
    delegation: PendingDelegation,
) -> None:
    """Publish a delegation-proposed event via the new publish_events API.

    This is a best-effort notification; failures are silently ignored since the
    delegation flow does not depend on timeline persistence.
    """
    from app.config import should_publish_event
    from app.workflows.execution.registry_publish import _publish_to_registry

    config = runtime.config
    if not should_publish_event(config, "delegation.proposed"):
        return

    chat_id = str(getattr(message, "chat_id", "") or getattr(getattr(message, "chat", None), "id", ""))

    try:
        projection = runtime.services.control_plane.conversation_projection
        await _publish_to_registry(
            projection,
            config,
            "delegation.proposed",
            origin_channel="telegram",
            external_conversation_ref=chat_id,
            target_agent_id=config.instance,
            title=delegation.title or "Delegation",
            actor=config.instance,
            content=delegation.title or "",
            metadata={
                "task_count": len(delegation.tasks),
                "target_agents": [],
            },
        )
    except Exception:
        pass  # Best-effort; delegation flow doesn't depend on this


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
    previews = await preview_delegation_targets(
        delegation,
        agent_directory=runtime.services.control_plane.agent_directory,
    )
    session.pending_delegation = delegation
    save_session(runtime, chat_id, session)
    await publish_delegation_proposed_event(runtime, message, delegation)

    # Autonomous mode: auto-submit delegation without buttons.
    if runtime.config.autonomous and session.approval_mode != "on":
        from app.agents.delegation import build_delegation_runtime
        conversation_ref_resolved = telegram_conversation_ref(runtime.config, chat_id)
        delegation_rt = build_delegation_runtime(
            config=runtime.config,
            provider_name=runtime.provider.name,
            provider_state_factory=runtime.provider.new_provider_state,
            task_routing=runtime.services.control_plane.task_routing,
            agent_directory=runtime.services.control_plane.agent_directory,
        )
        try:
            await handle_channel_delegation_approve(
                chat_id,
                conversation_ref_resolved,
                _AutoSubmitEgress(message),
                runtime=delegation_rt,
                retry_markup=None,
            )
        except Exception:
            # Ensure pending_delegation is not stuck in proposed state
            session_after = load_session(runtime, chat_id)
            if (
                session_after.pending_delegation
                and session_after.pending_delegation.status == "proposed"
            ):
                session_after.pending_delegation.status = "cancelled"
                save_session(runtime, chat_id, session_after)
            raise
        return RequestExecutionOutcome(status="delegation_submitted")

    send_plan = getattr(message, "send_text", None) or getattr(message, "reply_text")
    rendered = telegram_presenters.delegation_plan_message(
        delegation,
        previews=previews,
    )
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
