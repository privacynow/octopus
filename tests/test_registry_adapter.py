"""Contract tests for the registry channel egress."""

from __future__ import annotations

import types

import pytest

from app.providers.base import RunResult
from app.channels.registry.egress import RegistryChannelEgress
from tests.support.config_support import make_config


class _FakeRegistryClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published = []

    async def publish_timeline(self, events, *, checkpoint: str = ""):
        del checkpoint
        if self.fail:
            raise RuntimeError("registry unavailable")
        self.published.extend(events)
        return {"accepted": len(events)}


async def _noop_bind(*args, **kwargs):
    del args, kwargs
    return None


async def test_registry_surface_publishes_started_event_on_bind(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    surface = RegistryChannelEgress(cfg, conversation_ref="conv-1")
    monkeypatch.setattr("app.channels.registry.egress.bind_conversation", _noop_bind)
    monkeypatch.setattr(surface, "_registry_client", lambda: client)

    await surface.bind(title="Spec review", config=cfg)

    assert [event.kind for event in client.published] == ["started"]
    assert client.published[0].title == "Conversation started"


async def test_registry_surface_publishes_completed_event_on_outcome(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    surface = RegistryChannelEgress(cfg, conversation_ref="conv-2")
    monkeypatch.setattr(surface, "_registry_client", lambda: client)

    await surface.on_outcome(RunResult(text="done", returncode=0))

    assert [event.kind for event in client.published] == ["completed"]
    assert client.published[0].body == "done"


async def test_registry_surface_publishes_failed_event_on_outcome(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    surface = RegistryChannelEgress(cfg, conversation_ref="conv-3")
    monkeypatch.setattr(surface, "_registry_client", lambda: client)

    await surface.on_outcome(RunResult(text="boom", returncode=1))

    assert [event.kind for event in client.published] == ["failed"]
    assert client.published[0].body == "Exited 1"


async def test_registry_surface_rate_limits_progress_events(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    client = _FakeRegistryClient()
    surface = RegistryChannelEgress(cfg, conversation_ref="conv-4")
    monkeypatch.setattr(surface, "_registry_client", lambda: client)

    monotonic_values = iter([10.0, 11.0])

    def fake_monotonic() -> float:
        try:
            return next(monotonic_values)
        except StopIteration:
            return 11.0

    monkeypatch.setattr("app.channels.registry.egress.time.monotonic", fake_monotonic)

    handle = await surface.send_text("Working…")
    client.published.clear()
    await handle.edit_text("<i>first update</i>")
    await handle.edit_text("<i>second update</i>")

    progress_events = [event for event in client.published if event.kind == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0].body == "first update"


async def test_registry_surface_swallows_publish_error(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    output_log: list[dict[str, str]] = []
    surface = RegistryChannelEgress(cfg, conversation_ref="conv-5", output_log=output_log)
    monkeypatch.setattr(surface, "_registry_client", lambda: _FakeRegistryClient(fail=True))

    await surface.send_text("hello")
    await surface.on_outcome(types.SimpleNamespace(status="completed", reply_text="done"))

    assert output_log == [{"type": "send", "text": "hello"}]
    assert surface.sent_messages == ["hello"]


async def test_registry_surface_caches_missing_client_state(monkeypatch, tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
    )
    calls = {"count": 0}

    def fake_load_agent_runtime_state(data_dir):
        del data_dir
        calls["count"] += 1
        return types.SimpleNamespace(agent_token="")

    surface = RegistryChannelEgress(cfg, conversation_ref="conv-6")
    monkeypatch.setattr("app.channels.registry.egress.load_agent_runtime_state", fake_load_agent_runtime_state)
    monkeypatch.setattr("app.channels.registry.egress.bind_conversation", _noop_bind)

    await surface.bind(title="No enrollment yet", config=cfg)
    await surface.send_text("hello")
    await surface.on_outcome(types.SimpleNamespace(status="completed", reply_text="done"))

    assert calls["count"] == 1
