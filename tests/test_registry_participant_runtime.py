from __future__ import annotations

import asyncio

import pytest

from app.agents.state import RegistryConnectionState, save_registry_connection_state
from app.runtime.registry_participant import build_control_plane_registry_participant
from tests.support.config_support import make_config, make_registry_connection
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.conversation_projection import NoOpConversationProjection
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.registry_inspection import NoOpRegistryInspection
from octopus_sdk.registry.models import AgentDiscoveryQuery, ConversationId, TargetSelector
from octopus_sdk.task_routing import NoOpTaskRouting
from app.runtime.services import ControlPlaneServices


def _noop_control_plane_services() -> ControlPlaneServices:
    return ControlPlaneServices(
        conversation_projection=NoOpConversationProjection(),
        task_routing=NoOpTaskRouting(),
        agent_directory=NoOpAgentDirectory(),
        registry_inspection=NoOpRegistryInspection(),
        health_publication=NoOpHealthPublication(),
    )


def test_participant_health_live_local_agent_ids_ignores_unenrolled_registry(tmp_path) -> None:
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    save_registry_connection_state(
        config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="",
            connectivity_state="standalone",
        ),
    )
    participant = build_control_plane_registry_participant(
        config,
        _noop_control_plane_services(),
    )

    assert participant.health.current_local_agent_ids() == {"registry:default": ""}
    assert participant.health.live_local_agent_ids() == {}


def test_participant_health_live_local_agent_ids_returns_connected_enrollment(tmp_path) -> None:
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
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
    participant = build_control_plane_registry_participant(
        config,
        _noop_control_plane_services(),
    )

    assert participant.health.current_local_agent_ids() == {"registry:default": "agent-1"}
    assert participant.health.live_local_agent_ids() == {"registry:default": "agent-1"}


def test_participant_discovery_returns_unavailable_when_registry_connectivity_is_offline(tmp_path) -> None:
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    save_registry_connection_state(
        config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="agent-1",
            agent_token="token-1",
            connectivity_state="offline",
        ),
    )
    participant = build_control_plane_registry_participant(
        config,
        _noop_control_plane_services(),
    )

    result = asyncio.run(
        participant.discovery.search_agents(
            query=AgentDiscoveryQuery(free_text="m2"),
        )
    )

    assert result.status == "unavailable"
    assert result.agents == []


def test_participant_coordination_preview_reports_unavailable_when_registry_connectivity_is_offline(tmp_path) -> None:
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    save_registry_connection_state(
        config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="agent-1",
            agent_token="token-1",
            connectivity_state="offline",
        ),
    )
    participant = build_control_plane_registry_participant(
        config,
        _noop_control_plane_services(),
    )

    preview = asyncio.run(
        participant.coordination.preview_target_resolution(
            TargetSelector(kind="agent", value="m2"),
        )
    )

    assert preview.status == "unavailable"
    assert preview.error == "registry_unreachable"


def test_participant_coordination_direct_assign_raises_degraded_when_registry_connectivity_is_offline(tmp_path) -> None:
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    save_registry_connection_state(
        config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="agent-1",
            agent_token="token-1",
            connectivity_state="offline",
        ),
    )
    participant = build_control_plane_registry_participant(
        config,
        _noop_control_plane_services(),
    )

    with pytest.raises(RuntimeError, match="registry connectivity is degraded"):
        asyncio.run(
            participant.coordination.direct_assign(
                ConversationId("conv-1"),
                selector=TargetSelector(kind="agent", value="m2"),
                title="Test assignment",
                instructions="Do the thing",
            )
        )
