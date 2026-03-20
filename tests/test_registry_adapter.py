"""Contract tests for the registry channel egress."""

from __future__ import annotations

import types

import pytest

from app.agents.state import save_registry_connection_state
from app.agents.types import RegistryConnectionConfig, RegistryConnectionState
from app.channels.registry.channel import RegistryConversationChannel, RegistryTaskChannel
from app.providers.base import RunResult
from app.channels.registry.egress import RegistryChannelEgress
from app.channels.registry.refs import registry_conversation_ref, registry_task_ref
from tests.support.config_support import make_config


class _FakeRegistryClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published = []
        self.bound = []

    async def sync_binding(self, **kwargs):
        self.bound.append(kwargs)
        return {"ok": True}

    async def publish_timeline(self, events, *, checkpoint: str = ""):
        del checkpoint
        if self.fail:
            raise RuntimeError("registry unavailable")
        self.published.extend(events)
        return {"accepted": len(events)}


async def _noop_bind(*args, **kwargs):
    del args, kwargs
    return None


async def test_registry_channel_publishes_started_event_on_bind(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    channel_egress = RegistryChannelEgress(cfg, conversation_ref="conv-1")
    monkeypatch.setattr("app.channels.registry.egress.bind_conversation", _noop_bind)
    monkeypatch.setattr(channel_egress, "_registry_client", lambda: client)

    await channel_egress.bind(title="Spec review", config=cfg)

    assert [event.kind for event in client.published] == ["started"]
    assert client.published[0].title == "Conversation started"


async def test_registry_channel_publishes_completed_event_on_outcome(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    channel_egress = RegistryChannelEgress(cfg, conversation_ref="conv-2")
    monkeypatch.setattr(channel_egress, "_registry_client", lambda: client)

    await channel_egress.on_outcome(RunResult(text="done", returncode=0))

    assert [event.kind for event in client.published] == ["completed"]
    assert client.published[0].body == "done"


async def test_registry_channel_publishes_failed_event_on_outcome(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    channel_egress = RegistryChannelEgress(cfg, conversation_ref="conv-3")
    monkeypatch.setattr(channel_egress, "_registry_client", lambda: client)

    await channel_egress.on_outcome(RunResult(text="boom", returncode=1))

    assert [event.kind for event in client.published] == ["failed"]
    assert client.published[0].body == "Exited 1"


async def test_registry_channel_rate_limits_progress_events(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    channel_egress = RegistryChannelEgress(cfg, conversation_ref="conv-4")
    monkeypatch.setattr(channel_egress, "_registry_client", lambda: client)

    monotonic_values = iter([10.0, 11.0])

    def fake_monotonic() -> float:
        try:
            return next(monotonic_values)
        except StopIteration:
            return 11.0

    monkeypatch.setattr("app.channels.registry.egress.time.monotonic", fake_monotonic)

    handle = await channel_egress.send_text("Working…")
    client.published.clear()
    await handle.edit_text("<i>first update</i>")
    await handle.edit_text("<i>second update</i>")

    progress_events = [event for event in client.published if event.kind == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0].body == "first update"


async def test_registry_channel_swallows_publish_error(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    output_log: list[dict[str, str]] = []
    channel_egress = RegistryChannelEgress(cfg, conversation_ref="conv-5", output_log=output_log)
    monkeypatch.setattr(channel_egress, "_registry_client", lambda: _FakeRegistryClient(fail=True))

    await channel_egress.send_text("hello")
    await channel_egress.on_outcome(types.SimpleNamespace(status="completed", reply_text="done"))

    assert output_log == [{"type": "send", "text": "hello"}]
    assert channel_egress.sent_messages == ["hello"]


async def test_registry_channel_caches_missing_client_state(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    calls = {"count": 0}

    def fake_registry_client(config, *, registry_id=None):
        del config, registry_id
        calls["count"] += 1
        return None

    channel_egress = RegistryChannelEgress(cfg, conversation_ref="conv-6")
    monkeypatch.setattr("app.channels.registry.egress.registry_client", fake_registry_client)
    monkeypatch.setattr("app.channels.registry.egress.bind_conversation", _noop_bind)

    await channel_egress.bind(title="No enrollment yet", config=cfg)
    await channel_egress.send_text("hello")
    await channel_egress.on_outcome(types.SimpleNamespace(status="completed", reply_text="done"))

    assert calls["count"] == 1


async def test_registry_channels_build_scoped_egress_from_qualified_refs(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(),
        agent_registry_url="http://registry.default",
    )
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="prod",
            registry_scope="full",
            agent_id="agent-prod",
            agent_token="prod-token",
        ),
    )
    registry = RegistryConnectionConfig(
        registry_id="prod",
        url="http://registry.prod",
        enroll_token="enroll-prod",
        registry_scope="full",
        poll_interval_seconds=5.0,
    )
    client = _FakeRegistryClient()
    bound: list[dict[str, object]] = []

    async def fake_bind_conversation(*args, **kwargs):
        del args
        bound.append(kwargs)

    conversation_channel = RegistryConversationChannel(
        cfg,
        registry,
        registry_client_factory=lambda: client,
    )
    task_channel = RegistryTaskChannel(
        cfg,
        registry,
        registry_client_factory=lambda: client,
    )

    conversation_egress = conversation_channel.build_egress(
        conversation_ref=registry_conversation_ref("prod", "conv-42"),
        config=cfg,
    )
    task_egress = task_channel.build_egress(
        conversation_ref=registry_task_ref("prod", "task-42"),
        config=cfg,
    )

    monkeypatch.setattr("app.channels.registry.egress.bind_conversation", fake_bind_conversation)
    await conversation_egress.bind(title="Registry conversation", config=cfg)

    assert conversation_egress.registry_id == "prod"
    assert conversation_egress.external_id == "conv-42"
    assert task_egress.registry_id == "prod"
    assert task_egress.routed_task_id == "task-42"
    assert bound[0]["external_id"] == "conv-42"


def test_registry_task_channel_does_not_contribute_channel_capability(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    registry = RegistryConnectionConfig(
        registry_id="ops",
        url="http://registry.ops",
        enroll_token="enroll-ops",
        registry_scope="coordination",
        poll_interval_seconds=5.0,
    )

    task_channel = RegistryTaskChannel(cfg, registry)

    assert task_channel.descriptor.contributes_channel_capability is False
    assert task_channel.descriptor.accepts_channel_input is False
