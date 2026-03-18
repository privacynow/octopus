"""Concrete outbound egress construction shared by non-channel layers."""

from __future__ import annotations

from typing import Any

from app.config import BotConfig
from app.identity import telegram_conversation_key, telegram_numeric_id
from app.ports.egress import ChannelEgress
from app.runtime.composition import conversation_channel_name


def create_channel_egress(
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
) -> ChannelEgress:
    if not conversation_key and chat_id is not None:
        conversation_key = telegram_conversation_key(chat_id)
    if not conversation_key:
        conversation_key = conversation_ref
    if conversation_channel_name(conversation_ref) == "telegram":
        if bot is None:
            raise RuntimeError("Telegram channel requires a bot instance")
        numeric_chat_id = telegram_numeric_id(conversation_key)
        if numeric_chat_id is None:
            raise RuntimeError(
                f"Telegram channel requires a Telegram conversation key, got {conversation_key!r}"
            )
        from app.channels.telegram.egress import TelegramChannelEgress

        return TelegramChannelEgress(
            bot,
            numeric_chat_id,
            config=config,
            conversation_ref=conversation_ref,
            mirror_input_event=(source == "telegram"),
            target_message_id=target_message_id,
        )

    from app.channels.registry.egress import RegistryChannelEgress

    return RegistryChannelEgress(
        config,
        conversation_ref=conversation_ref,
        routed_task_id=routed_task_id,
        output_log=output_log,
    )
