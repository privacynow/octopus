"""Explicit test service builders."""

from __future__ import annotations

from app.execution_faults import LocalExecutionFaultState
from app.provider_guidance_service import get_provider_guidance_service
from app.runtime.artifacts import RuntimeArtifactStore
from app.runtime.composition import compose_workflows
from app.runtime.session_runtime import LocalSessionRuntime
from app.skill_inspection_service import SkillInspectionService
from app.skill_activation_service import get_skill_activation_service
from tests.support.config_support import make_config
from app.agents.registry_projection_interfaces import registry_projection_interfaces_by_implementation_ref
from app.agents.registry_projection_interfaces import registry_id_from_implementation_ref
from app.agents.state import load_registry_connection_state
from app.access import get_authorization
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
import app.runtime_backend as runtime_backend
from app.runtime.services import BotServices, ControlPlaneServices, build_bus_bot_services
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.conversation_projection import NoOpConversationProjection
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.bot_runtime import ExecutionServices
from octopus_sdk.registry_inspection import NoOpRegistryInspection
from octopus_sdk.task_routing import NoOpTaskRouting
from tests.support.registry_participant_support import build_noop_registry_participant


def _noop_control_plane_services() -> ControlPlaneServices:
    return ControlPlaneServices(
        conversation_projection=NoOpConversationProjection(),
        task_routing=NoOpTaskRouting(),
        agent_directory=NoOpAgentDirectory(),
        registry_inspection=NoOpRegistryInspection(),
        health_publication=NoOpHealthPublication(),
    )


def _build_local_bot_services(
    *,
    config,
    control_plane: ControlPlaneServices,
) -> BotServices:
    holder: dict[str, object] = {}
    activation = get_skill_activation_service()
    sessions = LocalSessionRuntime(
        config,
        catalog=lambda: holder["workflows"].runtime_skills.catalog,  # type: ignore[index,union-attr]
        activation=activation,
    )
    workflows = compose_workflows(config=config, sessions=sessions)
    holder["workflows"] = workflows
    return BotServices(
        control_plane=control_plane,
        registry=build_noop_registry_participant(),
        workflows=workflows,
        sessions=sessions,
        execution_services=ExecutionServices(
            guidance=get_provider_guidance_service(),
            skill_activation=activation,
            runtime_skill_setup=workflows.runtime_skills.setup,
            sessions=sessions,
            artifacts=RuntimeArtifactStore(config),
            skill_inspection=SkillInspectionService(
                config=config,
                workflows=workflows,
                agent_directory=control_plane.agent_directory,
                registry_inspection=control_plane.registry_inspection,
            ),
            execution_faults=LocalExecutionFaultState(config.data_dir),
            agent_directory=control_plane.agent_directory,
            conversation_projection=control_plane.conversation_projection,
        ),
        authorization=get_authorization(),
        work_queue=runtime_backend.transport_store(),
    )


def build_test_bot_services(
    *,
    config=None,
    control_plane: ControlPlaneServices | None = None,
    agent_id_for_implementation=None,
) -> BotServices:
    effective_config = config or make_config()
    runtime_backend.init(effective_config)
    effective_control_plane = control_plane or _noop_control_plane_services()
    if control_plane is not None:
        return _build_local_bot_services(
            config=effective_config,
            control_plane=effective_control_plane,
        )
    if config is not None:
        implemented_admin_interfaces = registry_projection_interfaces_by_implementation_ref(config.agent_registries)
        directory = build_control_plane_directory(implemented_admin_interfaces)

        def _default_agent_id_for_implementation(implementation_ref: str) -> str:
            try:
                registry_id = registry_id_from_implementation_ref(implementation_ref)
            except ValueError:
                return ""
            return load_registry_connection_state(config.data_dir, registry_id).agent_id

        holder: dict[str, object] = {}
        sessions = LocalSessionRuntime(
            config,
            catalog=lambda: holder["workflows"].runtime_skills.catalog,  # type: ignore[index,union-attr]
            activation=get_skill_activation_service(),
        )
        services = build_bus_bot_services(
            ControlPlaneBus(config.data_dir),
            directory,
            config=config,
            agent_id_for_implementation=agent_id_for_implementation or _default_agent_id_for_implementation,
            sessions=sessions,
        )
        holder["workflows"] = services.workflows
        return services
    return _build_local_bot_services(config=effective_config, control_plane=effective_control_plane)
