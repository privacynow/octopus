from __future__ import annotations

import pytest

import app.runtime_backend as runtime_backend
from app.agents.state import RegistryConnectionState, save_registry_connection_state
from app.runtime.services import build_runtime
from app.runtime.startup import validate_required_runtime_profile
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.conversation_projection import NoOpConversationProjection
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.task_routing import NoOpTaskRouting
from tests.support.config_support import make_config
from tests.support.config_support import make_registry_connection
from tests.support.handler_support import FakeProvider


def test_telegram_runtime_requires_registry_agent_mode() -> None:
    config = make_config(
        agent_mode="standalone",
        agent_registries=(make_registry_connection(),),
    )

    with pytest.raises(RuntimeError, match="BOT_AGENT_MODE=registry"):
        validate_required_runtime_profile(config)


def test_telegram_runtime_requires_registry_connections() -> None:
    config = make_config(
        agent_mode="registry",
        agent_registries=(),
    )

    with pytest.raises(RuntimeError, match="configured registry connections"):
        validate_required_runtime_profile(config)


def test_telegram_runtime_requires_full_registry_participant_coverage() -> None:
    config = make_config(
        agent_mode="registry",
        agent_registries=(make_registry_connection(registry_scope="channel"),),
    )

    with pytest.raises(RuntimeError, match="channel and coordination capabilities"):
        validate_required_runtime_profile(config)


def test_telegram_runtime_accepts_split_channel_and_coordination_profiles() -> None:
    config = make_config(
        agent_mode="registry",
        agent_registries=(
            make_registry_connection(registry_id="chan", registry_scope="channel"),
            make_registry_connection(registry_id="coord", registry_scope="coordination"),
        ),
    )

    validate_required_runtime_profile(config)


def test_required_telegram_profile_composes_real_services_and_transports(tmp_path) -> None:
    runtime_backend.reset_for_test()
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        runtime_mode="shared",
    )
    runtime_backend.init(config)
    try:
        runtime_process = build_runtime(config, FakeProvider())
    finally:
        runtime_backend.reset_for_test()

    control_plane = runtime_process.services.control_plane
    assert not isinstance(control_plane.conversation_projection, NoOpConversationProjection)
    assert not isinstance(control_plane.task_routing, NoOpTaskRouting)
    assert not isinstance(control_plane.agent_directory, NoOpAgentDirectory)
    assert not isinstance(control_plane.health_publication, NoOpHealthPublication)

    dispatcher = runtime_process.bot_runtime.transport
    assert dispatcher.active_transport_types() == ["telegram", "registry"]
    assert dispatcher.descriptor_for_ref("telegram:test:12345") is not None
    assert dispatcher.descriptor_for_ref("registry:default:conversation:conv-1") is not None


def test_required_telegram_profile_uses_live_registry_participant_when_enrolled(tmp_path) -> None:
    runtime_backend.reset_for_test()
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        runtime_mode="shared",
    )
    save_registry_connection_state(
        config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="agent-1",
            agent_token="token-1",
            connectivity_state="connected",
        ),
    )
    runtime_backend.init(config)
    try:
        runtime_process = build_runtime(config, FakeProvider())
    finally:
        runtime_backend.reset_for_test()

    registry = runtime_process.services.registry
    assert registry.health.current_local_agent_ids() == {"registry:default": "agent-1"}
    assert registry.health.live_local_agent_ids() == {"registry:default": "agent-1"}
