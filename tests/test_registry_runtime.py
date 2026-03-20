import asyncio
from pathlib import Path

import pytest

from app.agents.registry_runtime import RegistryRuntime
from app.agents.runtime import AgentRuntime
from app.agents.state import AgentRuntimeState, load_agent_runtime_state, load_registry_connection_state, save_agent_runtime_state
from app.agents.types import RegistryConnectionConfig, RegistryConnectionState
from app.channels.registry.refs import registry_conversation_ref
from app.runtime.channel_dispatcher import ChannelDispatcher
from tests.support.config_support import make_config


async def test_registry_runtime_annotates_deliveries_and_scopes_poll(monkeypatch, tmp_path: Path):
    poll_calls: list[tuple[str, tuple[str, ...] | None]] = []
    seen_registry_ids: list[str] = []
    stop_event = asyncio.Event()

    class FakeRegistryClient:
        def __init__(self, base_url: str, *, agent_token: str = "", timeout_seconds: float = 10.0, client=None):
            self.base_url = base_url
            self.agent_token = agent_token

        async def enroll(self, card, enrollment_token: str):
            return {
                "agent_id": "agent-prod",
                "slug": "prod-bot",
                "agent_token": "secret-token",
                "poll_cursor": "0",
            }

        async def register(self, card, *, connectivity_state: str, current_capacity: int, max_capacity: int):
            return {"ok": True}

        async def heartbeat(self, *, connectivity_state: str, current_capacity: int, max_capacity: int, active_work_count: int = 0, timeline_checkpoint: str = "", runtime_health=None):
            return {"ok": True}

        async def poll(self, *, cursor: str = "0", limit: int = 20, wait_seconds: int = 1, kind_filter=None):
            poll_calls.append((cursor, tuple(kind_filter) if kind_filter is not None else None))
            return {
                "deliveries": [
                    {
                        "delivery_id": "delivery-1",
                        "kind": "channel_input",
                        "payload": {"conversation_id": "conv-1", "text": "hello"},
                    }
                ],
                "next_cursor": "1",
            }

        async def ack(self, delivery_ids, *, classification: str):
            return {"ok": True}

    monkeypatch.setattr("app.agents.runtime.AgentRegistryClient", FakeRegistryClient)

    async def handler(delivery):
        seen_registry_ids.append(str(delivery["registry_id"]))
        stop_event.set()
        return "accepted"

    registry = RegistryConnectionConfig(
        registry_id="prod",
        url="http://registry.test",
        enroll_token="enroll-secret",
        registry_scope="channel",
        poll_interval_seconds=0.01,
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
        agent_registry_url=registry.url,
        agent_registry_enroll_token=registry.enroll_token,
        agent_poll_interval_seconds=registry.poll_interval_seconds,
    )
    runtime = RegistryRuntime(
        config.agent_registries,
        ChannelDispatcher(),
        handler,
        config=config,
    )
    runtime.register_channels()

    await runtime.start(stop_event=stop_event)
    await asyncio.wait_for(stop_event.wait(), timeout=0.5)
    await runtime.stop()

    assert seen_registry_ids == ["prod"]
    assert poll_calls == [("0", ("channel_input", "channel_action"))]
    assert runtime.channel_capabilities() == ("registry",)
    state = load_registry_connection_state(tmp_path, "prod")
    assert state == RegistryConnectionState(
        registry_id="prod",
        registry_scope="channel",
        agent_id="agent-prod",
        agent_token="secret-token",
        poll_cursor="1",
        registered_slug="prod-bot",
        connectivity_state="connected",
        last_successful_contact_at=state.last_successful_contact_at,
        last_error="",
        last_error_detail="",
    )


async def test_agent_runtime_default_registry_projects_legacy_state_and_dual_writes(tmp_path: Path):
    save_agent_runtime_state(
        tmp_path,
        AgentRuntimeState(
            agent_id="legacy-agent",
            agent_token="legacy-token",
            poll_cursor="8",
            registered_slug="legacy-bot",
            connectivity_state="connected",
        ),
    )
    registry = RegistryConnectionConfig(
        registry_id="default",
        url="http://registry.test",
        enroll_token="enroll-secret",
        registry_scope="full",
        poll_interval_seconds=5.0,
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
        agent_registry_url=registry.url,
        agent_registry_enroll_token=registry.enroll_token,
    )

    runtime = AgentRuntime(config, registry=registry)

    assert runtime.state == RegistryConnectionState(
        registry_id="default",
        registry_scope="full",
        agent_id="legacy-agent",
        agent_token="legacy-token",
        poll_cursor="8",
        registered_slug="legacy-bot",
        connectivity_state="connected",
    )

    runtime._mark_state("degraded", error="registry_timeout", detail="Registry sync timed out.")

    new_state = load_registry_connection_state(tmp_path, "default")
    legacy_state = load_agent_runtime_state(tmp_path)
    assert new_state.connectivity_state == "degraded"
    assert new_state.last_error == "registry_timeout"
    assert legacy_state.connectivity_state == "degraded"
    assert legacy_state.last_error == "registry_timeout"


async def test_registry_runtime_start_surfaces_wrapped_agent_runtime_failures(monkeypatch, tmp_path: Path):
    async def failing_run_forever(self, stop_event, *, kind_filter=None):
        del stop_event, kind_filter
        raise RuntimeError("runtime boom")

    monkeypatch.setattr("app.agents.runtime.AgentRuntime.run_forever", failing_run_forever)

    registry = RegistryConnectionConfig(
        registry_id="prod",
        url="http://registry.test",
        enroll_token="enroll-secret",
        registry_scope="full",
        poll_interval_seconds=5.0,
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
        agent_registry_url=registry.url,
        agent_registry_enroll_token=registry.enroll_token,
    )
    runtime = RegistryRuntime(
        config.agent_registries,
        ChannelDispatcher(),
        None,
        config=config,
    )

    with pytest.raises(RuntimeError, match="runtime boom"):
        await runtime.start(stop_event=asyncio.Event())


def test_registry_runtime_register_channels_by_scope(tmp_path: Path):
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
    runtime = RegistryRuntime(
        (prod, ops),
        dispatcher,
        None,
        config=make_config(
            data_dir=tmp_path,
            agent_mode="registry",
            agent_registries=(prod, ops),
            agent_registry_url=prod.url,
            agent_registry_enroll_token=prod.enroll_token,
        ),
    )

    runtime.register_channels()

    assert dispatcher.channel_type_for_ref(registry_conversation_ref("prod", "conv-1")) == "registry"
    assert dispatcher.channel_type_for_ref("registry:ops:task:task-1") == "registry"
    assert dispatcher.channel_type_for_ref("registry:prod:task:task-1") is None
    assert dispatcher.active_channel_types() == ["registry"]
