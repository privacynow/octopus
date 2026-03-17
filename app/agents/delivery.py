"""Dispatch polled registry deliveries onto the existing local workflow core."""

from __future__ import annotations

import logging

from app import work_queue
from app.agents.orchestration import (
    apply_routed_result,
    build_resume_prompt,
    delegation_ready_to_resume,
    send_delegation_completion_message,
)
from app.agents.bridge import (
    admit_registry_delivery,
    build_registry_action_envelope,
    build_registry_message_delivery,
    conversation_key_for_ref,
    publish_timeline_event,
)
from app.agents.types import RoutedTaskResult
from app.config import BotConfig
from app.transports import factory
from app.transports.admission import enqueue_inbound_envelope, record_inbound_envelope

log = logging.getLogger(__name__)


def _registry_semantic_action(
    *,
    conversation_ref: str,
    action: str,
    payload: dict[str, object],
    delivery_id: str,
):
    semantic = {
        "approve": "approve_pending",
        "reject": "reject_pending",
        "cancel": "cancel_conversation",
        "retry_skip": "retry_skip",
        "retry_allow": "retry_allow",
        "approve_delegation": "delegation_approve",
        "cancel_delegation": "delegation_cancel",
        "recovery_discard": "recovery_discard",
        "recovery_replay": "recovery_replay",
    }.get(action)
    if not semantic:
        return None

    params = dict(payload)
    if semantic in {"recovery_discard", "recovery_replay"}:
        update_id = int(payload.get("update_id") or 0)
        if update_id <= 0:
            return None
        params["update_id"] = update_id

    return build_registry_action_envelope(
        conversation_ref=conversation_ref,
        action=semantic,
        action_payload=params,
        actor_ref=f"registry-ui:{conversation_ref}",
        delivery_id=delivery_id,
    )


async def handle_registry_delivery(config: BotConfig, delivery: dict[str, object]) -> str:
    kind = str(delivery.get("kind", ""))
    delivery_id = str(delivery.get("delivery_id", ""))
    if kind in {"surface_input", "routed_task"}:
        return await admit_registry_delivery(config, delivery)

    payload = delivery.get("payload", {})
    if not isinstance(payload, dict):
        return "rejected"
    from app import telegram_handlers as th

    if kind == "surface_action":
        conversation_ref = str(payload.get("conversation_ref", "") or payload.get("conversation_id", ""))
        if not conversation_ref:
            return "rejected"
        action_payload = payload.get("payload", {})
        if not isinstance(action_payload, dict):
            action_payload = {}
        action = str(payload.get("action", "")).lower()
        if action in {"recovery_discard", "recovery_replay"} and "update_id" not in action_payload:
            action_payload = dict(action_payload)
            action_payload["update_id"] = payload.get("update_id")
        envelope = _registry_semantic_action(
            conversation_ref=conversation_ref,
            action=action,
            payload=action_payload,
            delivery_id=delivery_id,
        )
        if envelope is None:
            return "rejected"
        if action == "cancel":
            is_new = record_inbound_envelope(config.data_dir, envelope)
            if not is_new:
                return "accepted"
            result = work_queue.request_cancel(
                config.data_dir,
                envelope.conversation_key,
                envelope.actor_key,
                cancel_request_event_id=envelope.event_id,
            )
            if result == work_queue.CancelRequestResult.nothing_to_cancel:
                work_queue.enqueue_work_item(
                    config.data_dir,
                    envelope.conversation_key,
                    envelope.event_id,
                )
            return "accepted"
        enqueue_inbound_envelope(config.data_dir, envelope)
        return "accepted"

    if kind == "control":
        conversation_ref = str(payload.get("conversation_ref", "") or payload.get("conversation_id", ""))
        if not conversation_ref:
            return "rejected"
        action = str(payload.get("action", "")).lower()
        envelope = _registry_semantic_action(
            conversation_ref=conversation_ref,
            action=action,
            payload={},
            delivery_id=delivery_id,
        )
        if envelope is None:
            return "rejected"
        is_new = record_inbound_envelope(config.data_dir, envelope)
        if not is_new:
            return "accepted"
        result = work_queue.request_cancel(
            config.data_dir,
            envelope.conversation_key,
            envelope.actor_key,
            cancel_request_event_id=envelope.event_id,
        )
        if result == work_queue.CancelRequestResult.nothing_to_cancel:
            work_queue.enqueue_work_item(
                config.data_dir,
                envelope.conversation_key,
                envelope.event_id,
            )
        return "accepted"

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
        conversation_key = conversation_key_for_ref(parent_conversation_id)
        session = th._load(conversation_key)
        pending, matched = apply_routed_result(
            session.pending_delegation,
            routed_task_id=routed_task_id,
            result=routed_result,
        )
        if not matched:
            return "accepted"
        session.pending_delegation = pending
        th._save(conversation_key, session)
        if not delegation_ready_to_resume(pending):
            return "accepted"
        continuation_text = build_resume_prompt(pending)
        resume_delivery_id = f"delegation-resume:{parent_conversation_id}:{int(pending.created_at * 1000)}"
        conversation_key, actor_key, event_id, serialized = build_registry_message_delivery(
            conversation_ref=parent_conversation_id,
            text=continuation_text,
            actor_ref=f"delegation-resume:{routed_task_id}",
            delivery_id=resume_delivery_id,
            skip_approval=True,
        )
        admit_status, _ = work_queue.record_and_admit_message(
            config.data_dir,
            event_id,
            conversation_key,
            actor_key,
            "message",
            serialized,
        )
        if admit_status == "admitted":
            surface = factory.create_outbound_surface(
                parent_conversation_id,
                config=config,
                bot=th._bot_instance,
                conversation_key=conversation_key,
                source="registry",
            )
            try:
                await send_delegation_completion_message(pending, surface)
            except Exception:
                log.warning(
                    "Failed to send delegation completion summary for %s",
                    parent_conversation_id,
                    exc_info=True,
                )
            await publish_timeline_event(
                config,
                conversation_ref=parent_conversation_id,
                kind="delegation_ready",
                title="All delegated results received",
                body=continuation_text,
                metadata={"routed_task_id": routed_task_id},
                event_id=f"delegation-ready:{parent_conversation_id}",
            )
        elif admit_status == "duplicate":
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
