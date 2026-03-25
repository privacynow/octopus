"""Focused Telegram channel egress tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels.telegram.egress import TelegramChannelEgress, TelegramEditableHandle
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.task_routing import NoOpTaskRouting
from app.runtime.services import BotServices, ControlPlaneServices
from tests.support.handler_support import MinimalFakeBot


def _services(*, publish=None) -> BotServices:
    projection = SimpleNamespace(
        create_conversation=AsyncMock(return_value="conv-1"),
        publish_events=publish or AsyncMock(),
    )
    return BotServices(
        control_plane=ControlPlaneServices(
            conversation_projection=projection,
            task_routing=NoOpTaskRouting(),
            agent_directory=NoOpAgentDirectory(),
            health_publication=NoOpHealthPublication(),
        )
    )


@pytest.mark.asyncio
async def test_send_message_delegates_to_send_text():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(bot, chat_id=1)

    handle = await channel_egress.send_message("hello")

    assert channel_egress.replies == ["hello"]
    assert isinstance(handle, TelegramEditableHandle)


@pytest.mark.asyncio
async def test_send_recovery_notice_uses_presenter_markup_shape():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(bot, chat_id=1)

    await channel_egress.send_recovery_notice(
        preview="preview",
        prompt="prompt",
        run_again_label="Run again",
        skip_label="Skip",
        update_id=601,
    )

    sent = bot.sent_messages[-1]
    markup = sent["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "recovery_replay:601"
    assert markup.inline_keyboard[0][1].callback_data == "recovery_discard:601"


@pytest.mark.asyncio
async def test_bind_is_noop_for_telegram():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(),
    )

    await channel_egress.bind(title="Conversation", config=SimpleNamespace())
    # Telegram egress bind is a no-op (no projection)


@pytest.mark.asyncio
async def test_on_message_received_is_noop_for_telegram():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(),
    )

    await channel_egress.on_message_received("hello")
    # Telegram egress on_message_received is a no-op


@pytest.mark.asyncio
async def test_on_outcome_is_noop_for_telegram():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(),
    )
    outcome = SimpleNamespace(status="completed", reply_text="done", error_text="")

    await channel_egress.on_outcome(outcome)
    # Telegram egress on_outcome is a no-op


