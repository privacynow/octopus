"""Focused Telegram channel egress tests."""

import pytest

from app.channels.telegram.egress import TelegramChannelEgress, TelegramEditableHandle
from tests.support.handler_support import MinimalFakeBot


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
