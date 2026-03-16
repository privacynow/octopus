"""Focused Telegram surface adapter tests."""

import pytest

from app.transports.telegram_adapter import TelegramConversationIO, TelegramEditableMessageHandle
from tests.support.handler_support import MinimalFakeBot


@pytest.mark.asyncio
async def test_send_message_delegates_to_send_text():
    bot = MinimalFakeBot()
    surface = TelegramConversationIO(bot, chat_id=1)

    handle = await surface.send_message("hello")

    assert surface.replies == ["hello"]
    assert isinstance(handle, TelegramEditableMessageHandle)
