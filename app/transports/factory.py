"""Factory helpers for outbound interaction surfaces and inbound trust classification."""

from __future__ import annotations

from typing import Any

from app.access import trust_tier
from app.config import BotConfig
from app.identity import telegram_conversation_key, telegram_numeric_id
from app.transports.ports import InteractionSurface


def conversation_surface_name(conversation_ref: str) -> str:
    """Return the canonical surface name for a conversation reference."""
    if conversation_ref.startswith("telegram:"):
        return "telegram"
    return "registry"


def create_outbound_surface(
    conversation_ref: str,
    *,
    config: BotConfig,
    bot: Any,
    conversation_key: str = "",
    chat_id: int | None = None,
    target_message_id: int | None = None,
    source: str,
    routed_task_id: str = "",
    output_log: list | None = None,
) -> InteractionSurface:
    """Construct the correct outbound surface implementation for a conversation."""
    if not conversation_key and chat_id is not None:
        conversation_key = telegram_conversation_key(chat_id)
    if not conversation_key:
        conversation_key = conversation_ref
    if conversation_surface_name(conversation_ref) == "telegram":
        if bot is None:
            raise RuntimeError("Telegram surface requires a bot instance")
        chat_id = telegram_numeric_id(conversation_key)
        if chat_id is None:
            raise RuntimeError(
                f"Telegram surface requires a Telegram conversation key, got {conversation_key!r}"
            )
        from app.transports.telegram_adapter import TelegramConversationIO

        return TelegramConversationIO(
            bot,
            chat_id,
            config=config,
            conversation_ref=conversation_ref,
            mirror_input_event=(source == "telegram"),
            target_message_id=target_message_id,
        )

    from app.transports.registry_adapter import RegistryConversationIO

    return RegistryConversationIO(
        config,
        conversation_ref=conversation_ref,
        routed_task_id=routed_task_id,
        output_log=output_log,
    )


def trust_tier_for_source(source: str, user: Any, *, config: BotConfig) -> str:
    """Return the trust tier implied by the inbound source."""
    if source == "registry":
        return "trusted"
    return trust_tier(config, user)
