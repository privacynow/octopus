"""Focused Telegram channel egress tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels.telegram.egress import TelegramChannelEgress, TelegramEditableHandle
from app.ports.agent_directory import NoOpAgentDirectory
from app.ports.health_publication import NoOpHealthPublication
from app.ports.task_routing import NoOpTaskRouting
from app.runtime.services import BotServices, ControlPlaneServices
from tests.support.handler_support import MinimalFakeBot


def _services(*, bind=None, publish=None) -> BotServices:
    projection = SimpleNamespace(
        bind_external_conversation=bind or AsyncMock(),
        publish_external_timeline=publish or AsyncMock(),
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
async def test_bind_projects_conversation_via_control_plane_port():
    bot = MinimalFakeBot()
    bind = AsyncMock()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(bind=bind),
    )

    await channel_egress.bind(title="Conversation", config=SimpleNamespace())

    bind.assert_awaited_once_with(
        conversation_ref="telegram:bot-1:12345",
        title="Conversation",
        origin_channel="telegram",
        external_id="12345",
    )


@pytest.mark.asyncio
async def test_bind_skips_projection_when_conversation_ref_is_missing():
    bot = MinimalFakeBot()
    bind = AsyncMock()
    channel_egress = TelegramChannelEgress(bot, chat_id=12345, services=_services(bind=bind))

    await channel_egress.bind(title="Conversation", config=SimpleNamespace())

    bind.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_received_projects_input_via_control_plane_port():
    bot = MinimalFakeBot()
    publish = AsyncMock()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(publish=publish),
    )

    await channel_egress.on_message_received("hello")

    publish.assert_awaited_once_with(
        conversation_ref="telegram:bot-1:12345",
        kind="channel_input",
        title="Telegram message",
        body="hello",
    )


@pytest.mark.asyncio
async def test_on_message_received_skips_projection_when_input_mirroring_disabled():
    bot = MinimalFakeBot()
    publish = AsyncMock()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(publish=publish),
        mirror_input_event=False,
    )

    await channel_egress.on_message_received("hello")

    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_outcome_projects_result_via_control_plane_port():
    bot = MinimalFakeBot()
    publish = AsyncMock()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(publish=publish),
    )
    outcome = SimpleNamespace(status="completed", reply_text="done", error_text="")

    await channel_egress.on_outcome(outcome)

    publish.assert_awaited_once_with(
        conversation_ref="telegram:bot-1:12345",
        kind="result",
        title="Bot result",
        body="done",
    )


@pytest.mark.asyncio
async def test_publish_timeline_projects_event_id_and_metadata_via_control_plane_port():
    bot = MinimalFakeBot()
    publish = AsyncMock()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(publish=publish),
    )
    event = SimpleNamespace(
        event_id="evt-1",
        kind="progress",
        title="Working",
        body="step 1",
        status="running",
        progress=10,
        metadata={"phase": "alpha"},
    )

    await channel_egress.publish_timeline(event)

    publish.assert_awaited_once_with(
        conversation_ref="telegram:bot-1:12345",
        kind="progress",
        title="Working",
        body="step 1",
        status="running",
        progress=10,
        metadata={"phase": "alpha"},
        event_id="evt-1",
    )
