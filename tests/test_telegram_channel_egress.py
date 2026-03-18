"""Focused Telegram channel egress tests."""

import pytest

from app.channels.telegram.egress import TelegramChannelEgress, TelegramEditableHandle
from tests.support.handler_support import MinimalFakeBot


@pytest.mark.asyncio
async def test_send_message_delegates_to_send_text():
    bot = MinimalFakeBot()
    surface = TelegramChannelEgress(bot, chat_id=1)

    handle = await surface.send_message("hello")

    assert surface.replies == ["hello"]
    assert isinstance(handle, TelegramEditableHandle)
