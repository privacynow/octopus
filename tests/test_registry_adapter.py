"""Contract tests for registry channel egress via control-plane ports."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from app.channels.registry.channel import (
    RegistryConversationChannel,
    RegistryTaskChannel,
    register_registry_channels,
)
from app.channels.registry.egress import RegistryChannelEgress
from app.channels.registry.refs import registry_conversation_ref, registry_task_ref
from app.providers.base import RunResult
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime.services import (
    BotServices,
    ControlPlaneServices,
    build_noop_control_plane_services,
)
from tests.support.config_support import make_config, make_registry_connection
from app.agents.types import RegistryConnectionConfig


@dataclass
class _ProjectionRecorder:
    bind_calls: list[dict[str, object]] = field(default_factory=list)
    timeline_calls: list[dict[str, object]] = field(default_factory=list)
    fail_binds: bool = False
    fail_timeline: bool = False

    async def bind_external_conversation(self, **kwargs):
        self.bind_calls.append(kwargs)
        if self.fail_binds:
            raise RuntimeError("bind failed")

    async def publish_external_timeline(self, **kwargs):
        self.timeline_calls.append(kwargs)
        if self.fail_timeline:
            raise RuntimeError("timeline failed")


def _services(recorder: _ProjectionRecorder) -> BotServices:
    noop = build_noop_control_plane_services()
    return BotServices(
        control_plane=ControlPlaneServices(
            conversation_projection=recorder,
            task_routing=noop.task_routing,
            agent_directory=noop.agent_directory,
            health_publication=noop.health_publication,
        )
    )


async def test_registry_channel_publishes_started_event_on_bind(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    projection = _ProjectionRecorder()
    channel_egress = RegistryChannelEgress(
        cfg,
        conversation_ref="conv-1",
        services=_services(projection),
    )

    await channel_egress.bind(title="Spec review", config=cfg)

    assert projection.bind_calls == [
        {
            "conversation_ref": "conv-1",
            "title": "Spec review",
            "origin_channel": "registry",
            "external_id": "conv-1",
        }
    ]
    assert [call["kind"] for call in projection.timeline_calls] == ["started"]
    assert projection.timeline_calls[0]["title"] == "Conversation started"


async def test_registry_channel_sync_binding_uses_projection_port_without_started_event(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    projection = _ProjectionRecorder()
    channel_egress = RegistryChannelEgress(
        cfg,
        conversation_ref="conv-sync",
        services=_services(projection),
    )

    await channel_egress.sync_binding(
        {
            "conversation_ref": "conv-sync",
            "title": "Delegated task",
            "origin_channel": "registry",
            "external_id": "task-1",
        }
    )

    assert projection.bind_calls == [
        {
            "conversation_ref": "conv-sync",
            "title": "Delegated task",
            "origin_channel": "registry",
            "external_id": "task-1",
        }
    ]
    assert projection.timeline_calls == []


async def test_registry_channel_publishes_completed_event_on_outcome(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    projection = _ProjectionRecorder()
    channel_egress = RegistryChannelEgress(
        cfg,
        conversation_ref="conv-2",
        services=_services(projection),
    )

    await channel_egress.on_outcome(RunResult(text="done", returncode=0))

    assert [call["kind"] for call in projection.timeline_calls] == ["completed"]
    assert projection.timeline_calls[0]["body"] == "done"


async def test_registry_channel_rate_limits_progress_events(tmp_path, monkeypatch):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    projection = _ProjectionRecorder()
    channel_egress = RegistryChannelEgress(
        cfg,
        conversation_ref="conv-4",
        services=_services(projection),
    )

    monotonic_values = iter([10.0, 11.0])

    def fake_monotonic() -> float:
        try:
            return next(monotonic_values)
        except StopIteration:
            return 11.0

    monkeypatch.setattr("app.channels.registry.egress.time.monotonic", fake_monotonic)

    handle = await channel_egress.send_text("Working…")
    projection.timeline_calls.clear()
    await handle.edit_text("<i>first update</i>")
    await handle.edit_text("<i>second update</i>")

    progress_events = [event for event in projection.timeline_calls if event["kind"] == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0]["body"] == "first update"


async def test_registry_channel_swallows_projection_failures(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    output_log: list[dict[str, str]] = []
    projection = _ProjectionRecorder(fail_binds=True, fail_timeline=True)
    channel_egress = RegistryChannelEgress(
        cfg,
        conversation_ref="conv-5",
        output_log=output_log,
        services=_services(projection),
    )

    await channel_egress.bind(title="No bind", config=cfg)
    await channel_egress.send_text("hello")
    await channel_egress.on_outcome(SimpleNamespace(status="completed", reply_text="done"))

    assert output_log == [{"type": "send", "text": "hello"}]
    assert channel_egress.sent_messages == ["hello"]
    assert len(projection.bind_calls) == 1
    assert len(projection.timeline_calls) >= 2


async def test_registry_channels_build_scoped_egress_from_qualified_refs(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(),
    )
    registry = RegistryConnectionConfig(
        registry_id="prod",
        url="http://registry.prod",
        enroll_token="enroll-prod",
        registry_scope="full",
        poll_interval_seconds=5.0,
    )
    projection = _ProjectionRecorder()

    conversation_channel = RegistryConversationChannel(
        cfg,
        registry,
        services=_services(projection),
    )
    task_channel = RegistryTaskChannel(
        cfg,
        registry,
        services=_services(projection),
    )

    conversation_egress = conversation_channel.build_egress(
        conversation_ref=registry_conversation_ref("prod", "conv-42"),
        config=cfg,
    )
    task_egress = task_channel.build_egress(
        conversation_ref=registry_task_ref("prod", "task-42"),
        config=cfg,
    )

    await conversation_egress.bind(title="Registry conversation", config=cfg)

    assert conversation_egress.registry_id == "prod"
    assert conversation_egress.external_id == "conv-42"
    assert task_egress.registry_id == "prod"
    assert task_egress.routed_task_id == "task-42"
    assert projection.bind_calls[0]["external_id"] == "conv-42"


def test_register_registry_channels_registers_channels_by_scope(tmp_path):
    prod = RegistryConnectionConfig(
        registry_id="prod",
        url="http://registry.prod",
        enroll_token="enroll-prod",
        registry_scope="channel",
        poll_interval_seconds=5.0,
    )
    ops = RegistryConnectionConfig(
        registry_id="ops",
        url="http://registry.ops",
        enroll_token="enroll-ops",
        registry_scope="coordination",
        poll_interval_seconds=5.0,
    )
    dispatcher = ChannelDispatcher()

    register_registry_channels(
        make_config(
            data_dir=tmp_path,
            agent_mode="registry",
            agent_registries=(prod, ops),
        ),
        (prod, ops),
        dispatcher,
    )

    assert dispatcher.channel_type_for_ref(registry_conversation_ref("prod", "conv-1")) == "registry"
    assert dispatcher.channel_type_for_ref("registry:ops:task:task-1") == "registry"
    assert dispatcher.channel_type_for_ref("registry:prod:task:task-1") is None
    assert dispatcher.active_channel_types() == ["registry"]


def test_registry_task_channel_does_not_contribute_channel_capability(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    registry = RegistryConnectionConfig(
        registry_id="ops",
        url="http://registry.ops",
        enroll_token="enroll-ops",
        registry_scope="coordination",
        poll_interval_seconds=5.0,
    )

    task_channel = RegistryTaskChannel(
        cfg,
        registry,
        services=_services(_ProjectionRecorder()),
    )

    assert task_channel.descriptor.contributes_channel_capability is False
    assert task_channel.descriptor.accepts_channel_input is False
