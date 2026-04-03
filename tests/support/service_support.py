"""Explicit test service builders."""

from __future__ import annotations

from tests.support.config_support import make_config
from app.agents.registry_capabilities import registry_authority_capabilities
from app.agents.registry_capabilities import registry_id_from_authority_ref
from app.agents.state import load_registry_connection_state
from app.access import get_authorization
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
from app.runtime import composition
import app.runtime_backend as runtime_backend
from app.runtime.services import BotServices, ControlPlaneServices, build_bus_bot_services
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.conversation_projection import NoOpConversationProjection
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.task_routing import NoOpTaskRouting
from tests.support.registry_participant_support import build_noop_registry_participant


def _noop_control_plane_services() -> ControlPlaneServices:
    return ControlPlaneServices(
        conversation_projection=NoOpConversationProjection(),
        task_routing=NoOpTaskRouting(),
        agent_directory=NoOpAgentDirectory(),
        health_publication=NoOpHealthPublication(),
    )


def build_test_bot_services(*, config=None) -> BotServices:
    effective_config = config or make_config()
    runtime_backend.init(effective_config)
    if config is not None:
        authority_capabilities = registry_authority_capabilities(config.agent_registries)
        directory = build_control_plane_directory(authority_capabilities)

        def _agent_id_for_authority(authority_ref: str) -> str:
            try:
                registry_id = registry_id_from_authority_ref(authority_ref)
            except ValueError:
                return ""
            return load_registry_connection_state(config.data_dir, registry_id).agent_id

        return build_bus_bot_services(
            ControlPlaneBus(config.data_dir),
            directory,
            config=config,
            agent_id_for_authority=_agent_id_for_authority,
        )
    return BotServices(
        control_plane=_noop_control_plane_services(),
        registry=build_noop_registry_participant(),
        workflows=composition.workflows_for_config(effective_config),
        authorization=get_authorization(),
        work_queue=runtime_backend.transport_store(),
    )
