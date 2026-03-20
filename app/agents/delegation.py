"""Shared delegation action handlers usable from Telegram and registry channels."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agents.registry_capabilities import registry_id_from_authority_ref
from app.registry_errors import registry_error_summary
from app.agents.types import RoutedTaskRequest
from app.config import BotConfig
from app.identity import parse_conversation_key
from app.ports.agent_directory import AgentDirectoryPort
from app.ports.task_routing import TaskRoutingPort
from app.runtime.session_runtime import load_runtime_session, save_runtime_session
from app.workflows.delegation.coordination import (
    cancel_delegation,
    mark_task_submitted,
    prepare_delegation_approval,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DelegationRuntime:
    config: BotConfig
    provider_name: str
    provider_state_factory: Callable[[], dict[str, Any]]
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort


def build_delegation_runtime(
    *,
    config: BotConfig,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
    task_routing: TaskRoutingPort,
    agent_directory: AgentDirectoryPort,
) -> DelegationRuntime:
    return DelegationRuntime(
        config=config,
        provider_name=provider_name,
        provider_state_factory=provider_state_factory,
        task_routing=task_routing,
        agent_directory=agent_directory,
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


def _coordination_unavailable_message(*, error: str = "") -> str:
    if error == "no control plane":
        return "Delegation unavailable: no coordination-capable registry connections are configured."
    detail = f" {registry_error_summary(error)}" if error else ""
    return (
        "Delegation is unavailable because registry connectivity is degraded."
        " The request was not sent." + detail
    )


async def handle_delegation_approve(
    chat_id: int | str,
    conversation_ref: str,
    channel_egress: Any,
    *,
    runtime: DelegationRuntime,
    retry_markup: Any = None,
) -> None:
    """Approve a pending delegation plan on any conversation channel."""

    session = _load_session(runtime, chat_id)
    approval = prepare_delegation_approval(
        session.pending_delegation,
        conversation_ref=conversation_ref,
    )
    if approval.status != "approve_ready" or approval.pending is None:
        await channel_egress.send_text("Nothing to approve.")
        return
    delegation = approval.pending

    submitted_ids: list[str] = []
    try:
        for task in approval.tasks_to_submit:
            resolution = await runtime.agent_directory.resolve_target_authority(
                target_agent_id=task.target_agent_id,
            )
            if resolution.status != "resolved" or not resolution.authority_ref:
                _save_session(runtime, chat_id, session)
                if resolution.status == "unavailable":
                    await channel_egress.send_text(
                        _coordination_unavailable_message(error=resolution.error),
                        reply_markup=retry_markup,
                    )
                    return
                await channel_egress.send_text(
                    "Delegation unavailable: could not resolve which registry owns"
                    f" target agent {task.target_agent_id or task.routed_task_id}.",
                    reply_markup=retry_markup,
                )
                return
            request = RoutedTaskRequest(
                routed_task_id=task.routed_task_id,
                parent_conversation_id=delegation.conversation_ref,
                origin_agent_id="",
                target_agent_id=task.target_agent_id,
                title=task.title,
                instructions=task.instructions,
            )
            submission = await runtime.task_routing.submit_routed_task(
                request=request,
                authority_ref=resolution.authority_ref,
            )
            if submission.status != "accepted":
                _save_session(runtime, chat_id, session)
                if submission.status == "unavailable":
                    await channel_egress.send_text(
                        _coordination_unavailable_message(error=submission.error),
                        reply_markup=retry_markup,
                    )
                    return
                await channel_egress.send_text(
                    f"Delegation submission failed after {len(submitted_ids)} request(s)."
                    f" {registry_error_summary(submission.error)}"
                    " Please try again after the registry recovers.",
                    reply_markup=retry_markup,
                )
                return
            submitted_ids.append(task.routed_task_id)
            submission = mark_task_submitted(
                session.pending_delegation,
                routed_task_id=task.routed_task_id,
                registry_id=registry_id_from_authority_ref(resolution.authority_ref),
            )
            session.pending_delegation = submission.pending
    except Exception:
        _save_session(runtime, chat_id, session)
        log.exception(
            "Delegation submission failed after %s request(s) due to an unexpected error",
            len(submitted_ids),
        )
        await channel_egress.send_text(
            f"Delegation submission failed after {len(submitted_ids)} request(s)."
            " An unexpected error interrupted the remaining submissions."
            " Please try again.",
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
