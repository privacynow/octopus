"""Dispatch polled registry deliveries onto the existing local workflow core."""

from __future__ import annotations

from app.agents.bridge import (
    admit_registry_delivery,
    conversation_surface_name,
    local_chat_id_for_conversation,
    publish_timeline_event,
)
from app.config import BotConfig
from app.transports.telegram_adapter import TelegramConversationIO
from app.transports.registry_adapter import RegistryConversationIO


async def handle_registry_delivery(config: BotConfig, delivery: dict[str, object]) -> str:
    kind = str(delivery.get("kind", ""))
    if kind in {"surface_input", "routed_task"}:
        return await admit_registry_delivery(config, delivery)

    payload = delivery.get("payload", {})
    if not isinstance(payload, dict):
        return "rejected"

    def _conversation_message(conversation_ref: str):
        chat_id = local_chat_id_for_conversation(conversation_ref)
        if conversation_surface_name(conversation_ref) == "telegram":
            from app import telegram_handlers as th

            if th._bot_instance is None:
                raise RuntimeError("Telegram bot instance is not initialized")
            return chat_id, TelegramConversationIO(th._bot_instance, chat_id)
        return chat_id, RegistryConversationIO(config, conversation_ref=conversation_ref)

    if kind == "surface_action":
        conversation_ref = str(payload.get("conversation_id", ""))
        if not conversation_ref:
            return "rejected"
        action_payload = payload.get("payload", {})
        if not isinstance(action_payload, dict):
            action_payload = {}
        chat_id, message = _conversation_message(conversation_ref)
        from app import telegram_handlers as th
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
        from app import telegram_handlers as th
        action = str(payload.get("action", "")).lower()
        if action == "cancel":
            await th.cancel_chat_operation(chat_id, message, actor_user_id=0, allow_admin_override=True)
            return "accepted"
        return "rejected"

    if kind == "routed_result":
        parent_conversation_id = str(payload.get("parent_conversation_id", ""))
        result = payload.get("result", {})
        if not parent_conversation_id or not isinstance(result, dict):
            return "rejected"
        full_text = str(result.get("full_text", "") or "")
        summary = str(result.get("summary", "") or "")
        status = str(result.get("status", "") or "")
        await publish_timeline_event(
            config,
            conversation_ref=parent_conversation_id,
            kind="delegated_result",
            title="Delegated result received",
            body=full_text or summary,
            status=status,
            metadata={"routed_task_id": str(payload.get("routed_task_id", ""))},
        )
        return "accepted"

    return "rejected"
