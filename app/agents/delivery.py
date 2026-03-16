"""Dispatch polled registry deliveries onto the existing local workflow core."""

from __future__ import annotations

import uuid

from app import work_queue
from app.agents.orchestration import (
    apply_routed_result,
    build_resume_prompt,
    delegation_ready_to_resume,
)
from app.agents.bridge import (
    admit_registry_delivery,
    build_registry_message_delivery,
    local_chat_id_for_conversation,
    publish_timeline_event,
)
from app.agents.types import RoutedTaskResult
from app.config import BotConfig
from app.transports import factory


async def handle_registry_delivery(config: BotConfig, delivery: dict[str, object]) -> str:
    kind = str(delivery.get("kind", ""))
    if kind in {"surface_input", "routed_task"}:
        return await admit_registry_delivery(config, delivery)

    payload = delivery.get("payload", {})
    if not isinstance(payload, dict):
        return "rejected"
    from app import telegram_handlers as th

    def _conversation_message(conversation_ref: str):
        chat_id = local_chat_id_for_conversation(conversation_ref)
        return chat_id, factory.create_outbound_surface(
            conversation_ref,
            config=config,
            bot=th._bot_instance,
            chat_id=chat_id,
            source="registry",
        )

    if kind == "surface_action":
        conversation_ref = str(payload.get("conversation_id", ""))
        if not conversation_ref:
            return "rejected"
        action_payload = payload.get("payload", {})
        if not isinstance(action_payload, dict):
            action_payload = {}
        chat_id, message = _conversation_message(conversation_ref)
        action = str(payload.get("action", "")).lower()
        if action == "approve":
            await th.approve_pending(chat_id, message)
            return "accepted"
        if action == "reject":
            await th.reject_pending(chat_id, message)
            return "accepted"
        if action == "cancel":
            await th.cancel_chat_operation(chat_id, message, actor_user_id=0, allow_admin_override=True)
            return "accepted"
        if action == "retry_skip":
            await th.retry_skip_pending(chat_id, message)
            return "accepted"
        if action == "retry_allow":
            await th.retry_allow_pending(chat_id, message)
            return "accepted"
        if action in {"recovery_discard", "recovery_replay"}:
            update_id = int(action_payload.get("update_id") or payload.get("update_id") or 0)
            if update_id <= 0:
                return "rejected"
            await th.handle_recovery_action(chat_id, action, update_id, message)
            return "accepted"
        return "rejected"

    if kind == "control":
        conversation_ref = str(payload.get("conversation_id", ""))
        if not conversation_ref:
            return "rejected"
        chat_id, message = _conversation_message(conversation_ref)
        action = str(payload.get("action", "")).lower()
        if action == "cancel":
            await th.cancel_chat_operation(chat_id, message, actor_user_id=0, allow_admin_override=True)
            return "accepted"
        return "rejected"

    if kind == "routed_result":
        routed_task_id = str(payload.get("routed_task_id", ""))
        parent_conversation_id = str(payload.get("parent_conversation_id", ""))
        result = payload.get("result", {})
        if not parent_conversation_id or not routed_task_id or not isinstance(result, dict):
            return "rejected"
        routed_result = RoutedTaskResult(
            routed_task_id=routed_task_id,
            status=str(result.get("status", "") or ""),
            summary=str(result.get("summary", "") or ""),
            full_text=str(result.get("full_text", "") or ""),
            artifacts=tuple(result.get("artifacts", ()) or ()),
            follow_up_questions=tuple(str(item) for item in (result.get("follow_up_questions", ()) or ()) if item),
            completed_at=str(result.get("completed_at", "") or ""),
        )
        await publish_timeline_event(
            config,
            conversation_ref=parent_conversation_id,
            kind="delegated_result",
            title="Delegated result received",
            body=routed_result.full_text or routed_result.summary,
            status=routed_result.status,
            metadata={"routed_task_id": routed_task_id},
            event_id=f"delegated-result:{routed_task_id}",
        )
        if getattr(th, "_config", None) is None or getattr(th, "_provider", None) is None:
            return "retry_later"
        chat_id = local_chat_id_for_conversation(parent_conversation_id)
        session = th._load(chat_id)
        pending, matched = apply_routed_result(
            session.pending_delegation,
            routed_task_id=routed_task_id,
            result=routed_result,
        )
        if not matched:
            return "accepted"
        session.pending_delegation = pending
        th._save(chat_id, session)
        if not delegation_ready_to_resume(pending):
            return "accepted"
        continuation_text = build_resume_prompt(pending)
        resume_delivery_id = f"delegation-resume:{uuid.uuid4().hex}"
        _, user_id, update_id, serialized = build_registry_message_delivery(
            conversation_ref=parent_conversation_id,
            text=continuation_text,
            actor_ref=f"delegation-resume:{routed_task_id}",
            delivery_id=resume_delivery_id,
            skip_approval=True,
        )
        admit_status, _ = work_queue.record_and_admit_message(
            config.data_dir,
            update_id,
            chat_id,
            user_id,
            "message",
            serialized,
        )
        if admit_status == "busy":
            return "retry_later"
        if admit_status in {"admitted", "duplicate"}:
            session = th._load(chat_id)
            if (
                session.pending_delegation is not None
                and session.pending_delegation.conversation_ref == parent_conversation_id
            ):
                session.pending_delegation = None
                th._save(chat_id, session)
            await publish_timeline_event(
                config,
                conversation_ref=parent_conversation_id,
                kind="delegation_ready",
                title="All delegated results received",
                body=continuation_text,
                metadata={"routed_task_id": routed_task_id},
                event_id=f"delegation-ready:{parent_conversation_id}",
            )
        return "accepted"

    return "rejected"
