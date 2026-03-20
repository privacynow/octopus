"""Focused Telegram channel egress tests."""

from types import SimpleNamespace

import pytest

import app.channels.telegram.egress as telegram_egress
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


@pytest.mark.asyncio
async def test_bind_uses_registry_runtime_fanout_when_available(monkeypatch):
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        config=SimpleNamespace(),
        conversation_ref="telegram:bot-1:12345",
        registry_runtime=object(),
    )
    seen: list[dict[str, object]] = []

    async def _record(registry_runtime, **kwargs):
        seen.append({"registry_runtime": registry_runtime, **kwargs})

    async def _fail(*args, **kwargs):
        raise AssertionError("singleton bind path should not be used when registry runtime is present")

    monkeypatch.setattr(telegram_egress, "bind_conversation_to_registries", _record)
    monkeypatch.setattr(telegram_egress, "bind_conversation", _fail)

    await channel_egress.bind(title="Conversation", config=SimpleNamespace())

    assert seen == [
        {
            "registry_runtime": channel_egress._registry_runtime,
            "conversation_ref": "telegram:bot-1:12345",
            "title": "Conversation",
            "origin_channel": "telegram",
            "external_id": "12345",
        }
    ]


@pytest.mark.asyncio
async def test_on_message_received_uses_registry_runtime_fanout(monkeypatch):
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        config=SimpleNamespace(),
        conversation_ref="telegram:bot-1:12345",
        registry_runtime=object(),
    )
    seen: list[dict[str, object]] = []

    async def _record(registry_runtime, **kwargs):
        seen.append({"registry_runtime": registry_runtime, **kwargs})

    async def _fail(*args, **kwargs):
        raise AssertionError("singleton timeline path should not be used when registry runtime is present")

    monkeypatch.setattr(telegram_egress, "publish_timeline_to_registries", _record)
    monkeypatch.setattr(telegram_egress, "publish_timeline_event", _fail)

    await channel_egress.on_message_received("hello")

    assert seen == [
        {
            "registry_runtime": channel_egress._registry_runtime,
            "conversation_ref": "telegram:bot-1:12345",
            "kind": "channel_input",
            "title": "Telegram message",
            "body": "hello",
        }
    ]
