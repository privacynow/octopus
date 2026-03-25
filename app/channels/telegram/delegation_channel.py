"""Telegram delegation channel helpers."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from app.formatting import summarize_text
from app.registry_errors import registry_error_summary
from octopus_sdk.agent_directory import AgentSearchResult, AuthorityResolution
from octopus_sdk.identity import normalize_conversation_id, telegram_numeric_id
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.session_io import load as load_session
from app.channels.telegram.session_io import save as save_session
from app.channels.telegram.state import TelegramRuntime
from app.workflows.delegation.coordination import (
    build_delegation_plan,
    expire_stale_delegations,
    prepare_delegation_approval,
)
from octopus_sdk.execution import RequestExecutionOutcome
from octopus_sdk.registry.models import (
    AgentDiscoveryQuery,
    ApproveDelegationActionPayload,
    CancelDelegationActionPayload,
    CoordinationActionEnvelope,
    DelegateTasksActionPayload,
    DirectAssignActionPayload,
    TargetSelector,
)
from octopus_sdk.sessions import PendingDelegation, SessionState


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


def _coordination_unavailable_outcome(detail: str) -> RequestExecutionOutcome:
    return RequestExecutionOutcome(
        status="failed",
        error_text=detail,
    )


def _target_agent_for_projection(runtime: TelegramRuntime) -> str:
    for registry in runtime.config.agent_registries:
        agent_id = runtime.config.agent_id_for_registry(registry.registry_id)
        if agent_id:
            return agent_id
    for agent_id in runtime.config.registry_agent_ids.values():
        if agent_id:
            return agent_id
    return ""


async def _coordination_conversation_id(
    runtime: TelegramRuntime,
    conversation_key_value: str,
    *,
    conversation_ref: str,
    message,
) -> str:
    if conversation_ref.startswith("registry:"):
        return normalize_conversation_id(conversation_ref)
    projection = runtime.services.control_plane.conversation_projection
    target_agent_id = _target_agent_for_projection(runtime)
    if not target_agent_id:
        raise RuntimeError("Delegation unavailable: this bot is not enrolled in a coordination-capable registry.")
    external_ref = str(getattr(message, "external_id", "") or "")
    if not external_ref:
        numeric_chat_id = telegram_numeric_id(conversation_key_value)
        external_ref = str(numeric_chat_id) if numeric_chat_id is not None else conversation_key_value
    return await projection.create_conversation(
        target_agent_id=target_agent_id,
        origin_channel="telegram",
        external_conversation_ref=external_ref,
        title=f"Telegram {external_ref}",
    )


async def _preview_selector(
    runtime: TelegramRuntime,
    selector: TargetSelector,
) -> tuple[str, str]:
    directory = runtime.services.control_plane.agent_directory
    if selector.kind == "agent":
        target_agent_id = selector.preferred_agent_id or selector.value
        resolution = await directory.resolve_target_authority(target_agent_id=target_agent_id)
        if resolution.status == "resolved":
            return "resolved", resolution.authority_ref
        if resolution.status == "unavailable":
            return "unavailable", resolution.error or "registry_unreachable"
        return "unresolved", target_agent_id

    query = AgentDiscoveryQuery(
        role=selector.value if selector.kind == "role" else "",
        capabilities=[selector.value] if selector.kind == "capability" else [],
        required_state="connected",
    )
    result = await directory.search_agents(query=query)
    if result.status == "unavailable":
        return "unavailable", "registry_unreachable"
    if not result.agents:
        return "unresolved", selector.value
    return "resolved", result.agents[0].authority_ref


async def _preview_intent_targets(
    runtime: TelegramRuntime,
    delegation: PendingDelegation,
    selectors: dict[str, TargetSelector],
):
    from app.workflows.delegation.contracts import DelegationTargetPreview

    previews: list[DelegationTargetPreview] = []
    for task in delegation.tasks:
        selector = selectors.get(task.routed_task_id)
        if selector is None:
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="missing_target",
                    detail="No target selector was specified for this task.",
                )
            )
            continue
        try:
            status, detail = await _preview_selector(runtime, selector)
        except Exception:
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="unavailable",
                    detail="Registry unavailable.",
                )
            )
            continue
        if status == "resolved":
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="resolved",
                    authority_ref=detail,
                )
            )
        elif status == "unavailable":
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="unavailable",
                    detail=registry_error_summary(detail),
                )
            )
        else:
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="unresolved",
                    detail=f"Could not resolve target {detail}.",
                )
            )
    return tuple(previews)


def parse_target_selector(token: str) -> TargetSelector | None:
    raw = str(token or "").strip()
    if not raw.startswith("@"):
        return None
    body = raw[1:]
    if body.startswith("cap:"):
        value = body[4:].strip()
        if not value:
            return None
        return TargetSelector(kind="capability", value=value)
    if body.startswith("role:"):
        value = body[5:].strip()
        if not value:
            return None
        return TargetSelector(kind="role", value=value)
    value = body.strip()
    if not value:
        return None
    return TargetSelector(kind="agent", value=value, preferred_agent_id=value)


async def submit_direct_assignment(
    runtime: TelegramRuntime,
    conversation_key_value: str,
    message,
    *,
    conversation_ref: str,
    selector: TargetSelector,
    title: str,
    instructions: str,
):
    conversation_id = await _coordination_conversation_id(
        runtime,
        conversation_key_value,
        conversation_ref=conversation_ref,
        message=message,
    )
    envelope = CoordinationActionEnvelope(
        action_id=uuid4().hex,
        action="direct_assign",
        payload=DirectAssignActionPayload(
            selector=selector,
            title=title,
            instructions=instructions,
        ).model_dump(exclude_unset=True),
    )
    return await runtime.services.control_plane.conversation_projection.submit_action(
        conversation_id=conversation_id,
        envelope=envelope,
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
    try:
        conversation_id = await _coordination_conversation_id(
            runtime,
            conversation_key_value,
            conversation_ref=conversation_ref,
            message=message,
        )
        proposal_result = await runtime.services.control_plane.conversation_projection.submit_action(
            conversation_id=conversation_id,
            envelope=CoordinationActionEnvelope(
                action_id=uuid4().hex,
                action="delegate_tasks",
                payload=DelegateTasksActionPayload(
                    title=title,
                    resume_instruction=intent.resume_instruction,
                    tasks=list(intent.tasks),
                ).model_dump(exclude_unset=True),
            ),
        )
    except Exception as exc:
        return _coordination_unavailable_outcome(str(exc))
    delegation = build_delegation_plan(
        conversation_id,
        title,
        intent.resume_instruction,
        [
            {
                "draft_id": item.draft_id,
                "title": item.title,
                "target_agent_id": item.selector.preferred_agent_id,
                "target": item.selector.preferred_agent_id or item.selector.value,
                "selector_kind": item.selector.kind,
                "selector_value": item.selector.value,
                "instructions": item.instructions,
                "priority": item.priority,
                "requested_capabilities": list(item.requested_capabilities),
                "context": dict(item.context),
            }
            for item in intent.tasks
        ],
        proposal_id=proposal_result.proposal_id or proposal_result.action_id,
    )
    previews = await _preview_intent_targets(
        runtime,
        delegation,
        {item.draft_id: item.selector for item in intent.tasks},
    )
    session.pending_delegation = delegation
    save_session(runtime, conversation_key_value, session)
    numeric_chat_id = telegram_numeric_id(conversation_key_value)

    if runtime.config.autonomous and session.approval_mode != "on":
        try:
            approval_result = await runtime.services.control_plane.conversation_projection.submit_action(
                conversation_id=conversation_id,
                envelope=CoordinationActionEnvelope(
                    action_id=uuid4().hex,
                    action="approve_delegation",
                    payload=ApproveDelegationActionPayload(
                        proposal_id=delegation.proposal_id,
                    ).model_dump(exclude_unset=True),
                ),
            )
        except Exception:
            session_after = load_session(runtime, conversation_key_value)
            if (
                session_after.pending_delegation
                and session_after.pending_delegation.status == "proposed"
            ):
                session_after.pending_delegation.status = "cancelled"
                save_session(runtime, conversation_key_value, session_after)
            raise
        if session.pending_delegation is not None:
            session.pending_delegation.status = "submitted"
            for index, task_ref in enumerate(approval_result.routed_tasks):
                if index >= len(session.pending_delegation.tasks):
                    break
                session.pending_delegation.tasks[index].routed_task_id = task_ref.routed_task_id
                session.pending_delegation.tasks[index].target_agent_id = (
                    task_ref.target_agent_id or session.pending_delegation.tasks[index].target_agent_id
                )
                session.pending_delegation.tasks[index].authority_ref = (
                    task_ref.authority_ref or session.pending_delegation.tasks[index].authority_ref
                )
                session.pending_delegation.tasks[index].status = "submitted"
                session.pending_delegation.tasks[index].submitted_at = time.time()
            save_session(runtime, conversation_key_value, session)
        rendered = telegram_presenters.pending_plain_outcome_message(
            "Delegation approved. Specialist requests were sent."
        )
        await _AutoSubmitEgress(message).send_text(rendered.text, **rendered.kwargs())
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
    from app.channels.telegram.session_io import conversation_key as _conversation_key
    conv_key = _conversation_key(chat_id)
    session = load_session(runtime, conv_key)
    pending = session.pending_delegation
    channel = DelegationCallbackChannel(query)
    if pending is None or not pending.proposal_id or not pending.conversation_ref:
        await channel.send_text("Nothing to approve.")
        return
    expiration = expire_stale_delegations(
        pending,
        timeout_seconds=runtime.config.delegation_timeout_seconds,
    )
    if expiration.expired:
        session.pending_delegation = expiration.pending
        save_session(runtime, conv_key, session)
        if expiration.expired_kind == "approval_expired":
            await channel.send_text("Delegation plan expired before approval. Please ask me to delegate again.")
        else:
            await channel.send_text(
                "Delegation timed out while waiting for delegated results. Please ask me to delegate again if you still need that work."
            )
        return
    approval = prepare_delegation_approval(
        pending,
        conversation_ref=pending.conversation_ref,
    )
    if approval.status != "approve_ready":
        await channel.send_text("Nothing to approve.")
        return
    try:
        result = await runtime.services.control_plane.conversation_projection.submit_action(
            conversation_id=normalize_conversation_id(pending.conversation_ref),
            envelope=CoordinationActionEnvelope(
                action_id=uuid4().hex,
                action="approve_delegation",
                payload=ApproveDelegationActionPayload(
                    proposal_id=pending.proposal_id,
                ).model_dump(exclude_unset=True),
            ),
        )
    except Exception as exc:
        error_code = str(exc)
        if error_code in {"registry_unreachable", "registry_timeout", "registry_request_failed", "no control plane"}:
            await channel.send_text(
                "Delegation is unavailable because registry connectivity is degraded. "
                f"The request was not sent. {registry_error_summary(error_code)}"
            )
            return
        await channel.send_text(
            "Delegation submission failed. "
            f"{registry_error_summary(error_code)} Please try again after the registry recovers."
        )
        return
    pending.status = "submitted"
    for index, task_ref in enumerate(result.routed_tasks):
        if index >= len(pending.tasks):
            break
        pending.tasks[index].routed_task_id = task_ref.routed_task_id
        pending.tasks[index].target_agent_id = task_ref.target_agent_id or pending.tasks[index].target_agent_id
        pending.tasks[index].authority_ref = task_ref.authority_ref or pending.tasks[index].authority_ref
        pending.tasks[index].status = "submitted"
        pending.tasks[index].submitted_at = time.time()
    save_session(runtime, conv_key, session)
    await channel.send_text("Delegation approved. Specialist requests were sent.")


async def handle_delegation_cancel(
    runtime: TelegramRuntime,
    chat_id: int,
    query,
) -> None:
    from app.channels.telegram.session_io import conversation_key as _conversation_key
    conv_key = _conversation_key(chat_id)
    session = load_session(runtime, conv_key)
    pending = session.pending_delegation
    channel = DelegationCallbackChannel(query)
    if pending is None:
        await channel.send_text("Nothing to cancel.")
        return
    if pending.proposal_id and pending.conversation_ref:
        try:
            await runtime.services.control_plane.conversation_projection.submit_action(
                conversation_id=normalize_conversation_id(pending.conversation_ref),
                envelope=CoordinationActionEnvelope(
                    action_id=uuid4().hex,
                    action="cancel_delegation",
                    payload=CancelDelegationActionPayload(
                        proposal_id=pending.proposal_id,
                    ).model_dump(exclude_unset=True),
                ),
            )
        except Exception:
            await channel.send_text("Delegation could not be cancelled right now.")
            return
    session.pending_delegation = None
    save_session(runtime, conv_key, session)
    await channel.send_text("Delegation cancelled. No requests were sent.")
