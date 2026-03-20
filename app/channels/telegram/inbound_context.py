"""Telegram inbound ref/trust helpers shared by ingress paths."""

from __future__ import annotations

from app.agents.bridge import telegram_conversation_ref
from app.identity import telegram_numeric_id
from app.runtime.work_admission import trust_tier_for_ref


def event_conversation_ref(*, config, event) -> str:
    conversation_ref = str(getattr(event, "conversation_ref", "") or "")
    if conversation_ref:
        return conversation_ref
    chat_id = getattr(event, "chat_id", None)
    if isinstance(chat_id, int):
        return telegram_conversation_ref(config, chat_id)
    conversation_key = str(getattr(event, "conversation_key", "") or "")
    numeric_chat_id = telegram_numeric_id(conversation_key)
    if numeric_chat_id is not None:
        return telegram_conversation_ref(config, numeric_chat_id)
    return ""


def event_trust_tier(*, config, dispatcher, event) -> str:
    return trust_tier_for_ref(
        event_conversation_ref(config=config, event=event),
        event.user,
        config=config,
        dispatcher=dispatcher,
    )
