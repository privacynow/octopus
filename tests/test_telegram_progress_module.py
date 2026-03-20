import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.channels.telegram.progress as telegram_progress
from app.ports.agent_directory import NoOpAgentDirectory
from app.ports.health_publication import NoOpHealthPublication
from app.ports.task_routing import NoOpTaskRouting
from app.runtime.services import BotServices, ControlPlaneServices
from app.channels.telegram.state import build_telegram_runtime
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


def _services(*, publish=None) -> BotServices:
    projection = SimpleNamespace(
        bind_external_conversation=AsyncMock(),
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
async def test_keep_typing_uses_explicit_runtime_until_cancelled():
    class _Chat:
        def __init__(self) -> None:
            self.actions: list[str] = []

        async def send_action(self, action: str) -> None:
            self.actions.append(action)

    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-progress"), typing_interval_seconds=0.01),
        FakeProvider("codex"),
    )
    chat = _Chat()

    task = asyncio.create_task(telegram_progress.keep_typing(chat, runtime=runtime))
    await asyncio.sleep(0.03)
    task.cancel()
    await task

    assert chat.actions, "keep_typing should emit at least one typing action"


@pytest.mark.asyncio
async def test_progress_timeline_callback_publishes_progress_event(monkeypatch):
    publish = AsyncMock()
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-progress-timeline")),
        FakeProvider("codex"),
        services=_services(publish=publish),
    )

    await telegram_progress.progress_timeline_callback(
        runtime,
        "telegram:12345",
        "task-1",
        "<i>Working</i>",
    )

    publish.assert_awaited_once_with(
        conversation_ref="telegram:12345",
        kind="progress",
        title="Progress",
        body="<i>Working</i>",
        metadata={"routed_task_id": "task-1"},
    )


@pytest.mark.asyncio
async def test_progress_timeline_callback_uses_port_without_registry_runtime(monkeypatch):
    del monkeypatch
    publish = AsyncMock()
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-progress-fanout")),
        FakeProvider("codex"),
        services=_services(publish=publish),
    )

    await telegram_progress.progress_timeline_callback(
        runtime,
        "telegram:12345",
        "task-1",
        "<i>Working</i>",
    )

    publish.assert_awaited_once_with(
        conversation_ref="telegram:12345",
        kind="progress",
        title="Progress",
        body="<i>Working</i>",
        metadata={"routed_task_id": "task-1"},
    )
