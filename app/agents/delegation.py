"""Shared delegation action handlers usable from Telegram and registry channels."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agents.client import RegistryClientError
from app.agents.bridge import registry_connection_client, resolve_registry_connection
from app.registry_errors import registry_error_summary
from app.agents.state import load_runtime_registry_connection_state
from app.agents.types import RoutedTaskRequest
from app.agents.registry_runtime import RegistryRuntime
from app.config import BotConfig
from app.identity import parse_conversation_key
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
    registry_runtime: RegistryRuntime | None = None


def build_delegation_runtime(
    *,
    config: BotConfig,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
    registry_runtime: RegistryRuntime | None = None,
) -> DelegationRuntime:
    return DelegationRuntime(
        config=config,
        provider_name=provider_name,
        provider_state_factory=provider_state_factory,
        registry_runtime=registry_runtime,
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
    if runtime.registry_runtime is not None:
        if not runtime.registry_runtime.has_coordination_connections():
            await channel_egress.send_text(
                "Delegation unavailable: no coordination-capable registry connections are configured.",
                reply_markup=retry_markup,
            )
            return
        if not runtime.registry_runtime.has_connected_coordination_connection():
            if not runtime.registry_runtime.has_enrolled_coordination_connection():
                await channel_egress.send_text(
                    "Delegation unavailable: registry not enrolled.",
                    reply_markup=retry_markup,
                )
                return
            detail_code = runtime.registry_runtime.first_coordination_error()
            detail = f" {registry_error_summary(detail_code)}" if detail_code else ""
            await channel_egress.send_text(
                "Delegation is unavailable because registry connectivity is degraded."
                " The request was not sent." + detail,
                reply_markup=retry_markup,
            )
            return
    else:
        registry = resolve_registry_connection(cfg)
        if registry is None or registry.registry_scope not in {"coordination", "full"}:
            await channel_egress.send_text(
                "Delegation unavailable: no coordination-capable registry connections are configured.",
                reply_markup=retry_markup,
            )
            return
        state = load_runtime_registry_connection_state(
            cfg.data_dir,
            registry.registry_id,
            registry_scope=registry.registry_scope,
        )
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

    submitted_ids: list[str] = []
    try:
        for task in approval.tasks_to_submit:
            registry_id = task.registry_id
            origin_agent_id = ""
            client = None
            if runtime.registry_runtime is not None:
                registry_id = await runtime.registry_runtime.resolve_target_registry_id(
                    task.target_agent_id,
                    hinted_registry_id=task.registry_id,
                )
                if not registry_id:
                    _save_session(runtime, chat_id, session)
                    await channel_egress.send_text(
                        "Delegation unavailable: could not resolve which registry owns"
                        f" target agent {task.target_agent_id or task.routed_task_id}.",
                        reply_markup=retry_markup,
                    )
                    return
                client = runtime.registry_runtime.client_for_registry(registry_id)
                origin_agent_id = runtime.registry_runtime.origin_agent_id(registry_id)
            else:
                registry = resolve_registry_connection(cfg)
                if registry is None or registry.registry_scope not in {"coordination", "full"}:
                    _save_session(runtime, chat_id, session)
                    await channel_egress.send_text(
                        "Delegation unavailable: no coordination-capable registry connections are configured.",
                        reply_markup=retry_markup,
                    )
                    return
                registry_id = registry.registry_id
                state = load_runtime_registry_connection_state(
                    cfg.data_dir,
                    registry.registry_id,
                    registry_scope=registry.registry_scope,
                )
                client = registry_connection_client(cfg, registry_id=registry.registry_id)
                origin_agent_id = state.agent_id or ""
            if client is None or not origin_agent_id:
                _save_session(runtime, chat_id, session)
                await channel_egress.send_text(
                    "Delegation unavailable: registry not enrolled.",
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
            await client.submit_routed_task(request)
            submitted_ids.append(task.routed_task_id)
            submission = mark_task_submitted(
                session.pending_delegation,
                routed_task_id=task.routed_task_id,
                registry_id=registry_id,
            )
            session.pending_delegation = submission.pending
    except RegistryClientError as exc:
        _save_session(runtime, chat_id, session)
        log.warning(
            "Delegation submission failed after %s request(s): %s",
            len(submitted_ids),
            exc.operator_detail,
            exc_info=True,
        )
        await channel_egress.send_text(
            f"Delegation submission failed after {len(submitted_ids)} request(s)."
            f" {registry_error_summary(exc.error_code)}"
            " Please try again after the registry recovers.",
            reply_markup=retry_markup,
        )
        return
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
