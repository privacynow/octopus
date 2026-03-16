"""Shared delegation action handlers usable from Telegram and registry surfaces."""

from __future__ import annotations

import html
from typing import Any

from app.agents.bridge import registry_client
from app.agents.state import load_agent_runtime_state
from app.agents.types import RoutedTaskRequest


async def handle_delegation_approve(
    chat_id: int,
    conversation_ref: str,
    surface: Any,
    *,
    retry_markup: Any = None,
) -> None:
    """Approve a pending delegation plan on any conversation surface."""
    import app.telegram_handlers as th

    cfg = th._cfg()
    state = load_agent_runtime_state(cfg.data_dir)
    if state.connectivity_state != "connected":
        detail = f" Last error: {state.last_error}" if state.last_error else ""
        await surface.send_text(
            "Delegation is unavailable because registry connectivity is degraded."
            " The request was not sent." + detail,
            reply_markup=retry_markup,
        )
        return

    session = th._load(chat_id)
    delegation = session.pending_delegation
    if (
        delegation is None
        or not any(task.status == "proposed" for task in delegation.tasks)
        or (conversation_ref and delegation.conversation_ref and delegation.conversation_ref != conversation_ref)
    ):
        await surface.send_text("Nothing to approve.")
        return

    client = registry_client(cfg)
    if client is None:
        await surface.send_text(
            "Delegation unavailable: registry not enrolled.",
            reply_markup=retry_markup,
        )
        return

    origin_agent_id = state.agent_id or ""
    submitted_ids: list[str] = []
    try:
        for task in delegation.tasks:
            if task.status != "proposed":
                continue
            request = RoutedTaskRequest(
                routed_task_id=task.routed_task_id,
                parent_conversation_id=delegation.conversation_ref,
                origin_agent_id=origin_agent_id,
                target_agent_id=task.target_agent_id,
                title=task.title,
                instructions=task.instructions,
            )
            await client.submit_routed_task(request)
            task.status = "submitted"
            submitted_ids.append(task.routed_task_id)
        if submitted_ids:
            delegation.status = "submitted"
    except Exception as exc:
        if submitted_ids:
            delegation.status = "submitted"
        th._save(chat_id, session)
        await surface.send_text(
            f"Delegation submission failed after {len(submitted_ids)} request(s)."
            f" {html.escape(str(exc))}",
            reply_markup=retry_markup,
        )
        return

    th._save(chat_id, session)
    await surface.send_text(
        f"Delegation approved. {len(submitted_ids)} request(s) sent to specialist bots."
        " I'll continue when results arrive."
    )


async def handle_delegation_cancel(
    chat_id: int,
    conversation_ref: str,
    surface: Any,
) -> None:
    """Cancel a pending delegation plan on any conversation surface."""
    import app.telegram_handlers as th

    session = th._load(chat_id)
    delegation = session.pending_delegation
    if (
        delegation is None
        or (conversation_ref and delegation.conversation_ref and delegation.conversation_ref != conversation_ref)
    ):
        await surface.send_text("Nothing to cancel.")
        return
    session.pending_delegation = None
    th._save(chat_id, session)
    await surface.send_text("Delegation cancelled. No requests were sent.")
