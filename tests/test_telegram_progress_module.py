import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.channels.telegram.progress as telegram_progress
from app.agents.types import RoutedTaskUpdate
from app.ports.agent_directory import NoOpAgentDirectory
from app.ports.health_publication import NoOpHealthPublication
from app.ports.task_routing import NoOpTaskRouting
from app.runtime.services import BotServices, ControlPlaneServices
from app.channels.telegram.state import build_telegram_runtime
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


def _services(*, publish=None, task_routing=None) -> BotServices:
    projection = SimpleNamespace(
        bind_external_conversation=AsyncMock(),
        publish_external_timeline=publish or AsyncMock(),
    )
    return BotServices(
        control_plane=ControlPlaneServices(
            conversation_projection=projection,
            task_routing=task_routing or NoOpTaskRouting(),
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


@pytest.mark.asyncio
async def test_routed_task_progress_callback_updates_task_status_via_port() -> None:
    routing = SimpleNamespace(update_routed_task_status=AsyncMock())
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-progress-routed-task")),
        FakeProvider("codex"),
        services=_services(task_routing=routing),
    )

    await telegram_progress.routed_task_progress_callback(
        runtime,
        "task-1",
        "registry:ops",
        "<i>Still working</i>\n<b>Reviewing diff</b>",
        force=True,
    )

    routing.update_routed_task_status.assert_awaited_once()
    kwargs = routing.update_routed_task_status.await_args.kwargs
    assert kwargs["authority_ref"] == "registry:ops"
    update = kwargs["update"]
    assert isinstance(update, RoutedTaskUpdate)
    assert update.routed_task_id == "task-1"
    assert update.status == "running"
    assert update.summary == "Reviewing diff"
    assert update.progress is None
    assert update.timeline_events == ()


@pytest.mark.asyncio
async def test_routed_task_progress_callback_skips_empty_markup() -> None:
    routing = SimpleNamespace(update_routed_task_status=AsyncMock())
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-progress-routed-task-empty")),
        FakeProvider("codex"),
        services=_services(task_routing=routing),
    )

    await telegram_progress.routed_task_progress_callback(
        runtime,
        "task-1",
        "registry:ops",
        "<b> </b>",
    )

    routing.update_routed_task_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_routed_task_progress_callback_maps_terminal_progress_label() -> None:
    routing = SimpleNamespace(update_routed_task_status=AsyncMock())
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-progress-routed-task-terminal")),
        FakeProvider("codex"),
        services=_services(task_routing=routing),
    )

    await telegram_progress.routed_task_progress_callback(
        runtime,
        "task-1",
        "registry:ops",
        "Completed.",
        force=True,
    )

    kwargs = routing.update_routed_task_status.await_args.kwargs
    update = kwargs["update"]
    assert update.status == "completed"
    assert update.summary == "Completed."
