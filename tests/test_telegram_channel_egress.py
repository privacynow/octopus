"""Focused Telegram channel egress tests."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.access import get_authorization
from app.channels.telegram.egress import TelegramChannelEgress, TelegramEditableHandle
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.task_routing import NoOpTaskRouting
from app.runtime.services import BotServices, ControlPlaneServices
from app.runtime import composition
import app.runtime_backend as runtime_backend
from tests.support.handler_support import MinimalFakeBot
from tests.support.config_support import make_config
from tests.support.registry_participant_support import build_noop_registry_participant


def _services(*, publish=None, config=None) -> BotServices:
    effective_config = config or make_config()
    runtime_backend.init(effective_config)
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
        ),
        registry=build_noop_registry_participant(),
        workflows=composition.workflows_for_config(effective_config),
        authorization=get_authorization(),
        work_queue=runtime_backend.transport_store(),
    )


@pytest.mark.asyncio
async def test_send_message_delegates_to_send_text():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(bot, chat_id=1, services=_services())

    handle = await channel_egress.send_message("hello")

    assert channel_egress.replies == ["hello"]
    assert isinstance(handle, TelegramEditableHandle)


@pytest.mark.asyncio
async def test_send_recovery_notice_uses_presenter_markup_shape():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(bot, chat_id=1, services=_services())

    await channel_egress.send_recovery_notice(
        preview="preview",
        prompt="prompt",
        run_again_label="Run again",
        skip_label="Skip",
        recovery_id="tg:601",
    )

    sent = bot.sent_messages[-1]
    markup = sent["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "recovery_replay:tg:601"
    assert markup.inline_keyboard[0][1].callback_data == "recovery_discard:tg:601"


@pytest.mark.asyncio
async def test_bind_updates_telegram_egress_binding_state():
    bot = MinimalFakeBot()
    channel_egress = TelegramChannelEgress(
        bot,
        chat_id=12345,
        conversation_ref="telegram:bot-1:12345",
        services=_services(),
    )

    await channel_egress.bind(title="Conversation", config=SimpleNamespace())
    assert channel_egress.title == "Conversation"
    assert channel_egress.external_id == "12345"
