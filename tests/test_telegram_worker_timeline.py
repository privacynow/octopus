from pathlib import Path

import pytest

import app.channels.telegram.worker as telegram_worker
from app.channels.telegram.state import build_telegram_runtime
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


@pytest.mark.asyncio
async def test_publish_timeline_event_for_runtime_fans_out_telegram_refs(monkeypatch):
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-worker-timeline-fanout")),
        FakeProvider("codex"),
    )
    runtime.registry_runtime = object()
    published: list[dict[str, object]] = []

    async def _record(registry_runtime, **kwargs):
        published.append({"registry_runtime": registry_runtime, **kwargs})

    async def _fail(*args, **kwargs):
        raise AssertionError("singleton timeline path should not be used for Telegram refs")

    monkeypatch.setattr(telegram_worker, "publish_timeline_to_registries", _record)
    monkeypatch.setattr(telegram_worker, "publish_single_registry_timeline", _fail)

    await telegram_worker._publish_timeline_event_for_runtime(
        runtime,
        config=runtime.config,
        conversation_ref="telegram:bot-1:12345",
        kind="usage",
        title="Token usage",
        metadata={"prompt_tokens": 12},
    )

    assert published == [
        {
            "registry_runtime": runtime.registry_runtime,
            "conversation_ref": "telegram:bot-1:12345",
            "kind": "usage",
            "title": "Token usage",
            "body": "",
            "status": "",
            "progress": None,
            "metadata": {"prompt_tokens": 12},
            "event_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_publish_timeline_event_for_runtime_keeps_registry_refs_single_scoped(monkeypatch):
    runtime = build_telegram_runtime(
        make_config(data_dir=Path("/tmp/telegram-worker-timeline-single")),
        FakeProvider("codex"),
    )
    runtime.registry_runtime = object()
    published: list[dict[str, object]] = []

    async def _record(config, **kwargs):
        published.append({"config": config, **kwargs})

    async def _fail(*args, **kwargs):
        raise AssertionError("fan-out path should not be used for registry refs")

    monkeypatch.setattr(telegram_worker, "publish_single_registry_timeline", _record)
    monkeypatch.setattr(telegram_worker, "publish_timeline_to_registries", _fail)

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
