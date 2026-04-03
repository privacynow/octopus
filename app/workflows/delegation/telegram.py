"""Telegram delegation presentation helpers over shared SDK delegation logic."""

from __future__ import annotations

from app.formatting import summarize_text
from octopus_sdk.identity import telegram_actor_key, telegram_numeric_id
from app.presentation import telegram as telegram_presenters
from app.channels.telegram.state import TelegramRuntime
from octopus_sdk.execution import RequestExecutionOutcome
from octopus_sdk.registry.models import (
    DelegationIntent,
    parse_target_selector,
    TargetSelector,
)
from octopus_sdk.sessions import SessionState
from octopus_sdk.workflows.delegation import (
    ParticipantDelegationRuntime,
    approve_participant_delegation,
    cancel_participant_delegation,
    propose_participant_delegation,
    submit_participant_direct_assignment,
)


def delegation_reply_markup(chat_id: int):
    return telegram_presenters.delegation_reply_markup(chat_id)


def _coordination_unavailable_outcome(detail: str) -> RequestExecutionOutcome:
    return RequestExecutionOutcome(
        status="failed",
        error_text=detail,
    )


def _participant_runtime(runtime: TelegramRuntime):
    return ParticipantDelegationRuntime(
        config=runtime.config,
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        coordination=runtime.services.registry.coordination,
        sessions=runtime.services.sessions,
    )


async def submit_direct_assignment(
    runtime: TelegramRuntime,
    conversation_key_value: str,
    message,
    *,
    conversation_ref: str,
    selector: TargetSelector,
    title: str,
    instructions: str,
    message_text: str = "",
):
    external_ref = str(getattr(message, "external_id", "") or "")
    if not external_ref:
        numeric_chat_id = telegram_numeric_id(conversation_key_value)
        external_ref = str(numeric_chat_id) if numeric_chat_id is not None else conversation_key_value
    return await submit_participant_direct_assignment(
        _participant_runtime(runtime),
        conversation_key_value,
        conversation_ref=conversation_ref,
        selector=selector,
        title=title,
        instructions=instructions,
        message_text=message_text,
        origin_channel="telegram",
        external_ref=external_ref,
        authorized_actor_key=telegram_actor_key(getattr(getattr(message, "from_user", None), "id", "")),
    )



async def propose_delegation_plan(
    runtime: TelegramRuntime,
    conversation_key_value: str,
    message,
    session: SessionState,
    *,
    conversation_ref: str,
    result,
) -> RequestExecutionOutcome:
    intent = getattr(result, "coordination_intent", None)
    if intent is None or not intent.tasks:
        return RequestExecutionOutcome(status="failed", error_text="No coordination intent was supplied.")
    title = intent.title.strip() or summarize_text(result.text) or "Delegation plan"
    numeric_chat_id = telegram_numeric_id(conversation_key_value)
    external_ref = str(getattr(message, "external_id", "") or "")
    if not external_ref:
        external_ref = str(numeric_chat_id) if numeric_chat_id is not None else conversation_key_value
    try:
        plan = await propose_participant_delegation(
            _participant_runtime(runtime),
            conversation_key_value,
            session,
            conversation_ref=conversation_ref,
            title=title,
            intent=DelegationIntent(
                title=title,
                resume_instruction=intent.resume_instruction,
                tasks=list(intent.tasks),
            ),
            origin_channel="telegram",
            external_ref=external_ref,
            authorized_actor_key=telegram_actor_key(getattr(getattr(message, "from_user", None), "id", "")),
        )
    except Exception as exc:
        return _coordination_unavailable_outcome(str(exc))
    delegation = plan.pending
    previews = plan.previews
    if plan.status == "delegation_submitted":
        rendered = telegram_presenters.pending_plain_outcome_message(
            "Delegation approved. Specialist requests were sent."
        )
        send = getattr(message, "send_text", None) or getattr(message, "reply_text")
        await send(rendered.text, **rendered.kwargs())
        return RequestExecutionOutcome(status="delegation_submitted")

    send_plan = getattr(message, "send_text", None) or getattr(message, "reply_text")
    rendered = telegram_presenters.delegation_plan_message(
        delegation,
        previews=previews,
    )
    await send_plan(
        rendered.text,
        parse_mode=rendered.parse_mode,
        reply_markup=delegation_reply_markup(numeric_chat_id) if numeric_chat_id is not None else None,
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
) -> None:
    from app.runtime.telegram_session_io import conversation_key as _conversation_key
    outcome = await approve_participant_delegation(
        _participant_runtime(runtime),
        _conversation_key(chat_id),
    )
    await query.edit_message_text(outcome.message)


async def handle_delegation_cancel(
    runtime: TelegramRuntime,
    chat_id: int,
    query,
) -> None:
    from app.runtime.telegram_session_io import conversation_key as _conversation_key
    outcome = await cancel_participant_delegation(
        _participant_runtime(runtime),
        _conversation_key(chat_id),
    )
    await query.edit_message_text(outcome.message)
