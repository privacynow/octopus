"""Shared delegation action handlers usable from Telegram and registry channels."""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agents.bridge import registry_client
from app.registry_errors import registry_error_summary
from app.agents.state import load_agent_runtime_state
from app.agents.types import RoutedTaskRequest
from app.config import BotConfig
from app.identity import parse_conversation_key
from app.runtime.session_runtime import load_runtime_session, save_runtime_session
from app.workflows.delegation.coordination import (
    cancel_delegation,
    mark_task_submitted,
    prepare_delegation_approval,
)


@dataclass(frozen=True)
class DelegationRuntime:
    config: BotConfig
    provider_name: str
    provider_state_factory: Callable[[], dict[str, Any]]


def build_delegation_runtime(
    *,
    config: BotConfig,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
) -> DelegationRuntime:
    return DelegationRuntime(
        config=config,
        provider_name=provider_name,
        provider_state_factory=provider_state_factory,
    )


def _load_session(runtime: DelegationRuntime, chat_id: int | str):
    return load_runtime_session(
        runtime.config.data_dir,
        parse_conversation_key(chat_id),
        provider_name=runtime.provider_name,
        provider_state_factory=runtime.provider_state_factory,
        approval_mode=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
    )


def _save_session(runtime: DelegationRuntime, chat_id: int | str, session) -> None:
    save_runtime_session(runtime.config.data_dir, parse_conversation_key(chat_id), session)


async def handle_delegation_approve(
    chat_id: int | str,
    conversation_ref: str,
    channel_egress: Any,
    *,
    runtime: DelegationRuntime,
    retry_markup: Any = None,
) -> None:
    """Approve a pending delegation plan on any conversation channel."""
    cfg = runtime.config
    state = load_agent_runtime_state(cfg.data_dir)
    if state.connectivity_state != "connected":
        detail = f" {registry_error_summary(state.last_error)}" if state.last_error else ""
        await channel_egress.send_text(
            "Delegation is unavailable because registry connectivity is degraded."
            " The request was not sent." + detail,
            reply_markup=retry_markup,
        )
        return

    session = _load_session(runtime, chat_id)
    approval = prepare_delegation_approval(
        session.pending_delegation,
        conversation_ref=conversation_ref,
    )
    if approval.status != "approve_ready" or approval.pending is None:
        await channel_egress.send_text("Nothing to approve.")
        return
    delegation = approval.pending

    client = registry_client(cfg)
    if client is None:
        await channel_egress.send_text(
            "Delegation unavailable: registry not enrolled.",
            reply_markup=retry_markup,
        )
        return

    origin_agent_id = state.agent_id or ""
    submitted_ids: list[str] = []
    try:
        for task in approval.tasks_to_submit:
            request = RoutedTaskRequest(
                routed_task_id=task.routed_task_id,
                parent_conversation_id=delegation.conversation_ref,
                origin_agent_id=origin_agent_id,
                target_agent_id=task.target_agent_id,
                title=task.title,
                instructions=task.instructions,
            )
            await client.submit_routed_task(request)
            submitted_ids.append(task.routed_task_id)
            submission = mark_task_submitted(
                session.pending_delegation,
                routed_task_id=task.routed_task_id,
            )
            session.pending_delegation = submission.pending
    except Exception as exc:
        _save_session(runtime, chat_id, session)
        await channel_egress.send_text(
            f"Delegation submission failed after {len(submitted_ids)} request(s)."
            f" {html.escape(str(exc))}",
            reply_markup=retry_markup,
        )
        return

    _save_session(runtime, chat_id, session)
    await channel_egress.send_text(
        f"Delegation approved. {len(submitted_ids)} request(s) sent to specialist bots."
        " I'll continue when results arrive."
    )


async def handle_delegation_cancel(
    chat_id: int | str,
    conversation_ref: str,
    channel_egress: Any,
    *,
    runtime: DelegationRuntime,
) -> None:
    """Cancel a pending delegation plan on any conversation channel."""
    session = _load_session(runtime, chat_id)
    outcome = cancel_delegation(
        session.pending_delegation,
        conversation_ref=conversation_ref,
    )
    if outcome.status != "cancelled":
        await channel_egress.send_text("Nothing to cancel.")
        return
    session.pending_delegation = None
    _save_session(runtime, chat_id, session)
    await channel_egress.send_text("Delegation cancelled. No requests were sent.")
