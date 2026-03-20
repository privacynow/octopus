from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.channels.telegram.worker as telegram_worker
from app.channels.telegram.state import build_telegram_runtime
from app.ports.agent_directory import NoOpAgentDirectory
from app.ports.health_publication import NoOpHealthPublication
from app.ports.task_routing import NoOpTaskRouting
from app.runtime.services import BotServices, ControlPlaneServices
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
async def test_publish_timeline_event_for_runtime_projects_telegram_refs_via_port(monkeypatch):
    del monkeypatch
    publish = AsyncMock()
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-worker-timeline-fanout")),
        FakeProvider("codex"),
        services=_services(publish=publish),
    )
    runtime.channel_dispatcher = SimpleNamespace(
        channel_type_for_ref=lambda conversation_ref: (
            "telegram" if conversation_ref.startswith("telegram:") else "registry"
        )
    )

    await telegram_worker._publish_timeline_event_for_runtime(
        runtime,
        config=runtime.config,
        conversation_ref="telegram:bot-1:12345",
        kind="usage",
        title="Token usage",
        metadata={"prompt_tokens": 12},
    )

    publish.assert_awaited_once_with(
        conversation_ref="telegram:bot-1:12345",
        kind="usage",
        title="Token usage",
        body="",
        status="",
        progress=None,
        metadata={"prompt_tokens": 12},
        event_id=None,
    )


@pytest.mark.asyncio
async def test_publish_timeline_event_for_runtime_keeps_registry_refs_single_scoped(monkeypatch):
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-worker-timeline-single")),
        FakeProvider("codex"),
        services=_services(),
    )
    runtime.channel_dispatcher = SimpleNamespace(
        channel_type_for_ref=lambda conversation_ref: (
            "telegram" if conversation_ref.startswith("telegram:") else "registry"
        )
    )
    published: list[dict[str, object]] = []

    async def _record(config, **kwargs):
        published.append({"config": config, **kwargs})

    runtime.services.control_plane.conversation_projection.publish_external_timeline = AsyncMock(
        side_effect=AssertionError("control-plane projection path should not be used for registry refs")
    )

    monkeypatch.setattr(telegram_worker, "publish_single_registry_timeline", _record)

    await telegram_worker._publish_timeline_event_for_runtime(
        runtime,
        config=runtime.config,
        registry_id="prod",
        conversation_ref="registry:prod:conversation:conv-1",
        kind="usage",
        title="Token usage",
        metadata={"prompt_tokens": 12},
    )

    assert published == [
        {
            "config": runtime.config,
            "registry_id": "prod",
            "conversation_ref": "registry:prod:conversation:conv-1",
            "kind": "usage",
            "title": "Token usage",
            "metadata": {"prompt_tokens": 12},
        }
    ]
