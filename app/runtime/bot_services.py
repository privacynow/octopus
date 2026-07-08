"""Control-plane service graph builders for runtime composition."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import app.runtime_backend as runtime_backend
from app.access import get_authorization
from app.agents.registry_projection_interfaces import registry_id_from_implementation_ref
from app.agents.state import load_runtime_registry_connection_state
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.config import BotConfig
from app.execution_faults import LocalExecutionFaultState
from app.provider_guidance_service import get_provider_guidance_service
from app.runtime.agent_awareness import RuntimeAgentAwarenessService
from app.runtime.artifacts import RuntimeArtifactStore
from app.runtime.composition import compose_workflows
from app.skill_inspection_service import SkillInspectionService
from app.skill_activation_service import get_skill_activation_service
from octopus_sdk.agent_directory import AgentDirectoryPort
from octopus_sdk.authorization import AuthorizationPort
from octopus_sdk.bot_runtime import ExecutionServices, SessionRuntimePort, WorkflowComposition
from octopus_sdk.conversation_projection import ConversationProjectionPort
from octopus_sdk.health_publication import HealthPublicationPort
from octopus_sdk.registry.client import RegistryClient
from octopus_sdk.registry_inspection import RegistryInspectionPort
from octopus_sdk.registry_participant import RegistryParticipantImplementation
from octopus_sdk.task_routing import TaskRoutingPort
from octopus_sdk.work_queue import WorkQueuePort

log = logging.getLogger(__name__)


class RuntimeCapabilityExchangeService:
    def __init__(self, config: BotConfig) -> None:
        self._config = config

    async def exchange_runtime_capability(self, *, authority_ref: str, capability_ref: str) -> str:
        try:
            registry_id = registry_id_from_implementation_ref(authority_ref)
        except ValueError:
            return ""
        registry = next((item for item in self._config.agent_registries if item.registry_id == registry_id), None)
        if registry is None:
            return ""
        state = load_runtime_registry_connection_state(
            self._config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope,
        )
        if not state.agent_token:
            return ""
        result = await RegistryClient(registry.url, agent_token=state.agent_token).exchange_runtime_capability(capability_ref)
        if not bool(result.get("ok", False)):
            return ""
        return str(result.get("bearer_token", "") or "")


@dataclass(frozen=True)
class ControlPlaneServices:
    conversation_projection: ConversationProjectionPort
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort
    registry_inspection: RegistryInspectionPort
    health_publication: HealthPublicationPort


@dataclass(frozen=True)
class BotServices:
    control_plane: ControlPlaneServices
    registry: RegistryParticipantImplementation
    workflows: WorkflowComposition
    sessions: SessionRuntimePort
    execution_services: ExecutionServices
    authorization: AuthorizationPort
    work_queue: WorkQueuePort


def build_bus_control_plane_services(
    bus: ControlPlaneBus,
    directory: ControlPlaneDirectory,
    *,
    config: BotConfig,
    agent_id_for_implementation: Callable[[str], str] | None = None,
) -> ControlPlaneServices:
    from app.control_plane.adapters import (
        BusAgentDirectory,
        BusConversationProjection,
        BusHealthPublication,
        BusRegistryInspection,
        BusTaskRouting,
    )

    def _connectivity_state_for_authority(authority_ref: str) -> str:
        try:
            registry_id = registry_id_from_implementation_ref(authority_ref)
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
            bus,
            directory,
            agent_id_for_implementation=agent_id_for_implementation,
        ),
        task_routing=BusTaskRouting(bus, directory),
        agent_directory=BusAgentDirectory(bus, directory),
        registry_inspection=BusRegistryInspection(bus, directory),
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
    config: BotConfig,
    agent_id_for_implementation: Callable[[str], str] | None = None,
    sessions: SessionRuntimePort,
) -> BotServices:
    from app.runtime.registry_participant import build_control_plane_registry_participant

    try:
        runtime_backend.transport_store()
    except RuntimeError:
        runtime_backend.init(config)

    control_plane = build_bus_control_plane_services(
        bus,
        directory,
        config=config,
        agent_id_for_implementation=agent_id_for_implementation,
    )
    workflow_graph = compose_workflows(config=config, sessions=sessions)
    execution_services = ExecutionServices(
        guidance=get_provider_guidance_service(),
        skill_activation=get_skill_activation_service(),
        runtime_skill_setup=workflow_graph.runtime_skills.setup,
        sessions=sessions,
        artifacts=RuntimeArtifactStore(config),
        skill_inspection=SkillInspectionService(
            config=config,
            workflows=workflow_graph,
            agent_directory=control_plane.agent_directory,
            registry_inspection=control_plane.registry_inspection,
        ),
        execution_faults=LocalExecutionFaultState(config.data_dir),
        agent_directory=control_plane.agent_directory,
        conversation_projection=control_plane.conversation_projection,
        agent_awareness=RuntimeAgentAwarenessService(
            config=config,
            runtime_skill_catalog=workflow_graph.runtime_skills.catalog,
        ),
        runtime_capabilities=RuntimeCapabilityExchangeService(config),
    )
    return BotServices(
        control_plane=control_plane,
        registry=build_control_plane_registry_participant(
            config,
            control_plane,
        ),
        workflows=workflow_graph,
        sessions=sessions,
        execution_services=execution_services,
        authorization=get_authorization(),
        work_queue=runtime_backend.transport_store(),
    )
