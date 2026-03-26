"""Runtime-owned shared service containers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import app.runtime_backend as runtime_backend
from app.agents.registry_capabilities import registry_id_from_authority_ref
from app.agents.state import load_runtime_registry_connection_state
from app.access import get_authorization
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.config import BotConfig
from app.runtime.composition import workflows
from octopus_sdk.agent_directory import AgentDirectoryPort
from octopus_sdk.authorization import AuthorizationPort
from octopus_sdk.bot_runtime import WorkflowComposition
from octopus_sdk.conversation_projection import ConversationProjectionPort
from octopus_sdk.health_publication import HealthPublicationPort
from octopus_sdk.registry_participant import RegistryParticipantImplementation
from octopus_sdk.task_routing import TaskRoutingPort
from octopus_sdk.work_queue import WorkQueuePort


@dataclass(frozen=True)
class ControlPlaneServices:
    conversation_projection: ConversationProjectionPort
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort
    health_publication: HealthPublicationPort


@dataclass(frozen=True)
class BotServices:
    control_plane: ControlPlaneServices
    registry: RegistryParticipantImplementation
    workflows: WorkflowComposition
    authorization: AuthorizationPort
    work_queue: WorkQueuePort


def build_bus_control_plane_services(
    bus: ControlPlaneBus,
    directory: ControlPlaneDirectory,
    *,
    config: BotConfig,
    agent_id_for_authority: Callable[[str], str] | None = None,
) -> ControlPlaneServices:
    from app.control_plane.adapters import (
        BusAgentDirectory,
        BusConversationProjection,
        BusHealthPublication,
        BusTaskRouting,
    )

    def _connectivity_state_for_authority(authority_ref: str) -> str:
        try:
            registry_id = registry_id_from_authority_ref(authority_ref)
        except ValueError:
            return "offline"
        registry = next(
            (item for item in config.agent_registries if item.registry_id == registry_id),
            None,
        )
        if registry is None:
            return "offline"
        state = load_runtime_registry_connection_state(
            config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope,
        )
        return str(state.connectivity_state or "offline")

    return ControlPlaneServices(
        conversation_projection=BusConversationProjection(
            bus, directory, agent_id_for_authority=agent_id_for_authority,
        ),
        task_routing=BusTaskRouting(bus, directory),
        agent_directory=BusAgentDirectory(bus, directory),
        health_publication=BusHealthPublication(
            bus,
            directory,
            connectivity_state_for_authority=_connectivity_state_for_authority,
        ),
    )


def build_bus_bot_services(
    bus: ControlPlaneBus,
    directory: ControlPlaneDirectory,
    *,
    config,
    agent_id_for_authority: Callable[[str], str] | None = None,
) -> BotServices:
    from app.runtime.registry_participant import build_control_plane_registry_participant

    control_plane = build_bus_control_plane_services(
        bus,
        directory,
        config=config,
        agent_id_for_authority=agent_id_for_authority,
    )
    return BotServices(
        control_plane=control_plane,
        registry=build_control_plane_registry_participant(
            config,
            control_plane,
        ),
        workflows=workflows(),
        authorization=get_authorization(),
        work_queue=runtime_backend.transport_store(),
    )
