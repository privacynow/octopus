"""Shared delegation action handlers usable across channel entrypoints."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.registry_errors import registry_error_summary
from app.agents.types import RoutedTaskRequest
from app.agents.registry_capabilities import registry_id_from_authority_ref
from app.agents.state import runtime_registry_agent_id


from app.config import BotConfig
from app.ports.agent_directory import AgentDirectoryPort
from app.ports.task_routing import TaskRoutingPort
from app.runtime.session_runtime import load_runtime_session, save_runtime_session
from app.workflows.delegation.coordination import (
    cancel_delegation,
    expire_stale_delegations,
    mark_task_submitted,
    prepare_delegation_approval,
)
from app.workflows.delegation.contracts import DelegationTargetPreview

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DelegationRuntime:
    config: BotConfig
    provider_name: str
    provider_state_factory: Callable[[str], dict[str, Any]]
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort


def resolve_origin_agent_id(config: BotConfig, registry_id: str) -> str:
    """Resolve the bot's registry-assigned agent_id for a specific registry.

    Requires registry_id — no first-hit fallback.
    """
    registry = next(
        (item for item in config.agent_registries if item.registry_id == registry_id),
        None,
    )
    return runtime_registry_agent_id(
        config.data_dir,
        registry_id,
        registry_scope=registry.registry_scope if registry is not None else "full",
    )


def build_delegation_runtime(
    *,
    config: BotConfig,
    provider_name: str,
    provider_state_factory: Callable[[str], dict[str, Any]],
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


def _load_session(runtime: DelegationRuntime, conversation_key: str):
    return load_runtime_session(
        runtime.config.data_dir,
        conversation_key,
        provider_name=runtime.provider_name,
        provider_state_factory=runtime.provider_state_factory,
        approval_mode=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
    )


def _save_session(runtime: DelegationRuntime, conversation_key: str, session) -> None:
    save_runtime_session(runtime.config.data_dir, conversation_key, session)


def _coordination_unavailable_message(*, error: str = "") -> str:
    if error == "no control plane":
        return "Delegation unavailable: no coordination-capable registry connections are configured."
    detail = f" {registry_error_summary(error)}" if error else ""
    return (
        "Delegation is unavailable because registry connectivity is degraded."
        " The request was not sent." + detail
    )


def _coordination_unavailable_detail(*, error: str = "") -> str:
    if error == "no control plane":
        return "No coordination-capable registry connections are configured."
    if error:
        return registry_error_summary(error)
    return "Registry connectivity is degraded."


def _expired_delegation_message(expired_kind: str) -> str:
    if expired_kind == "approval_expired":
        return "Delegation plan expired before approval. Please ask me to delegate again."
    return "Delegation timed out while waiting for delegated results. Please ask me to delegate again if you still need that work."


def _delegation_task_label(task) -> str:
    return task.target_agent_id or task.title or task.routed_task_id


def _task_labels_with_status(pending, expected_status: str) -> list[str]:
    labels: list[str] = []
    for task in pending.tasks if pending is not None else ():
        current_status = getattr(task, "status", "")
        if current_status == expected_status:
            labels.append(_delegation_task_label(task))
    return labels


def _partial_submission_message(
    pending,
    *,
    reason: str,
) -> str:
    submitted = _task_labels_with_status(pending, "submitted")
    remaining = _task_labels_with_status(pending, "proposed")
    lines = [
        (
            "Delegation partially submitted."
            f" Sent {len(submitted)} request(s), but {len(remaining)} could not be sent."
        )
    ]
    if reason:
        lines.append(reason)
    if submitted:
        lines.append(f"Already sent to: {', '.join(submitted)}.")
    if remaining:
        lines.append(f"Still pending: {', '.join(remaining)}.")
    lines.append("Approving again will only send the remaining requests.")
    return " ".join(lines)


async def handle_delegation_approve(
    conversation_key: str,
    conversation_ref: str,
    channel_egress: Any,
    *,
    runtime: DelegationRuntime,
    retry_markup: Any = None,
    event_sink: Any = None,
) -> None:
    """Approve a pending delegation plan on any conversation channel."""

    session = _load_session(runtime, conversation_key)
    expiration = expire_stale_delegations(
        session.pending_delegation,
        timeout_seconds=runtime.config.delegation_timeout_seconds,
    )
    if expiration.expired:
        session.pending_delegation = expiration.pending
        _save_session(runtime, conversation_key, session)
        await channel_egress.send_text(_expired_delegation_message(expiration.expired_kind))
        return
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
                _save_session(runtime, conversation_key, session)
                if resolution.status == "unavailable":
                    if submitted_ids:
                        await channel_egress.send_text(
                            _partial_submission_message(
                                session.pending_delegation,
                                reason=_coordination_unavailable_detail(error=resolution.error),
                            ),
                            reply_markup=retry_markup,
                        )
                        return
                    await channel_egress.send_text(
                        _coordination_unavailable_message(error=resolution.error),
                        reply_markup=retry_markup,
                    )
                    return
                if submitted_ids:
                    await channel_egress.send_text(
                        _partial_submission_message(
                            session.pending_delegation,
                            reason=(
                                "Could not resolve which authority owns "
                                f"{task.target_agent_id or task.routed_task_id}."
                            ),
                        ),
                        reply_markup=retry_markup,
                    )
                    return
                await channel_egress.send_text(
                    "Delegation unavailable: could not resolve which authority owns"
                    f" target agent {task.target_agent_id or task.routed_task_id}.",
                    reply_markup=retry_markup,
                )
                return
            origin_agent_id = resolve_origin_agent_id(
                runtime.config,
                registry_id_from_authority_ref(resolution.authority_ref),
            )
            if not origin_agent_id:
                _save_session(runtime, conversation_key, session)
                detail = (
                    "Delegation unavailable: this bot has no enrolled agent identity for "
                    f"{resolution.authority_ref}."
                )
                if submitted_ids:
                    await channel_egress.send_text(
                        _partial_submission_message(
                            session.pending_delegation,
                            reason=detail,
                        ),
                        reply_markup=retry_markup,
                    )
                    return
                await channel_egress.send_text(
                    detail,
                    reply_markup=retry_markup,
                )
                return
            request = RoutedTaskRequest(
                routed_task_id=task.routed_task_id,
                parent_conversation_id=delegation.conversation_ref,
                origin_agent_id=origin_agent_id,
                target_agent_id=task.target_agent_id,
                title=task.title,
                instructions=task.instructions,
            )
            submission = await runtime.task_routing.submit_routed_task(
                request=request,
                authority_ref=resolution.authority_ref,
            )
            if submission.status != "accepted":
                _save_session(runtime, conversation_key, session)
                if submitted_ids:
                    await channel_egress.send_text(
                        _partial_submission_message(
                            session.pending_delegation,
                            reason=registry_error_summary(submission.error),
                        ),
                        reply_markup=retry_markup,
                    )
                    return
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
                authority_ref=resolution.authority_ref,
            )
            session.pending_delegation = submission.pending
    except Exception:
        _save_session(runtime, conversation_key, session)
        log.exception(
            "Delegation submission failed after %s request(s) due to an unexpected error",
            len(submitted_ids),
        )
        if submitted_ids:
            await channel_egress.send_text(
                _partial_submission_message(
                    session.pending_delegation,
                    reason="An unexpected error interrupted the remaining submissions.",
                ),
                reply_markup=retry_markup,
            )
            return
        await channel_egress.send_text(
            f"Delegation submission failed after {len(submitted_ids)} request(s)."
            " An unexpected error interrupted the remaining submissions."
            " Please try again.",
            reply_markup=retry_markup,
        )
        return

    _save_session(runtime, conversation_key, session)
    if event_sink is not None:
        tasks_summary = [{"title": t.title, "target": t.target_agent_id, "status": "submitted"} for t in session.pending_delegation.tasks]
        await event_sink.on_delegation_submitted(tasks_summary)
    await channel_egress.send_text(
        f"Delegation approved. {len(submitted_ids)} request(s) sent to specialist bots."
        " I'll continue when results arrive."
    )


async def preview_delegation_targets(
    pending,
    *,
    agent_directory: AgentDirectoryPort,
) -> tuple[DelegationTargetPreview, ...]:
    if pending is None:
        return ()
    cached_resolutions: dict[str, Any] = {}
    previews: list[DelegationTargetPreview] = []
    for task in pending.tasks:
        target_agent_id = (task.target_agent_id or "").strip()
        if not target_agent_id:
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="missing_target",
                    detail="No target agent was specified for this task.",
                )
            )
            continue
        resolution = cached_resolutions.get(target_agent_id)
        if resolution is None:
            try:
                resolution = await agent_directory.resolve_target_authority(
                    target_agent_id=target_agent_id,
                )
            except Exception:
                log.exception(
                    "Delegation preview failed while resolving target agent %s",
                    target_agent_id,
                )
                previews.append(
                    DelegationTargetPreview(
                        routed_task_id=task.routed_task_id,
                        status="unavailable",
                        detail=_coordination_unavailable_detail(error="registry_request_failed"),
                    )
                )
                continue
            cached_resolutions[target_agent_id] = resolution
        if resolution.status == "resolved" and resolution.authority_ref:
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="resolved",
                    authority_ref=resolution.authority_ref,
                )
            )
            continue
        if resolution.status == "unavailable":
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="unavailable",
                    detail=_coordination_unavailable_detail(error=resolution.error),
                )
            )
            continue
        previews.append(
            DelegationTargetPreview(
                routed_task_id=task.routed_task_id,
                status="unresolved",
                detail=(
                    "Could not resolve which authority owns "
                    f"{target_agent_id}."
                ),
            )
        )
    return tuple(previews)


async def handle_delegation_cancel(
    conversation_key: str,
    conversation_ref: str,
    channel_egress: Any,
    *,
    runtime: DelegationRuntime,
) -> None:
    """Cancel a pending delegation plan on any conversation channel."""
    session = _load_session(runtime, conversation_key)
    outcome = cancel_delegation(
        session.pending_delegation,
        conversation_ref=conversation_ref,
    )
    if outcome.status != "cancelled":
        await channel_egress.send_text("Nothing to cancel.")
        return
    session.pending_delegation = None
    _save_session(runtime, conversation_key, session)
    await channel_egress.send_text("Delegation cancelled. No requests were sent.")
