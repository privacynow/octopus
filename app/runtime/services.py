"""Runtime composition builders."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.registry_projection_interfaces import (
    registry_projection_interfaces_by_implementation_ref,
    registry_id_from_implementation_ref,
)
from app.agents.state import runtime_registry_agent_id
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
from app.config import BotConfig
from app.runtime.bot_services import BotServices, ControlPlaneServices, build_bus_bot_services
from app.runtime.session_runtime import LocalSessionRuntime
from app.skill_activation_service import get_skill_activation_service
from octopus_sdk.bot_runtime import BotRuntime
from octopus_sdk.providers import Provider

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class RuntimeBuild:
    boot_id: str
    services: BotServices
    bot_runtime: BotRuntime


def build_runtime(config: BotConfig, provider: Provider) -> RuntimeBuild:
    from app.runtime.transport_builders import build_runtime_transport_stack

    bus = ControlPlaneBus(config.data_dir)
    workflow_holder: dict[str, object] = {}
    sessions = LocalSessionRuntime(
        config,
        catalog=lambda: workflow_holder["workflows"].runtime_skills.catalog,  # type: ignore[return-value]
        activation=get_skill_activation_service(),
    )
    implemented_admin_interfaces = (
        registry_projection_interfaces_by_implementation_ref(config.agent_registries)
        if config.agent_registries
        else {}
    )
    directory = build_control_plane_directory(implemented_admin_interfaces)

    def _agent_id_for_implementation(implementation_ref: str) -> str:
        try:
            registry_id = registry_id_from_implementation_ref(implementation_ref)
        except ValueError:
            return ""
        registry = next(
            (item for item in config.agent_registries if item.registry_id == registry_id),
            None,
        )
        return runtime_registry_agent_id(
            config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope if registry is not None else "full",
        )

    services = build_bus_bot_services(
        bus,
        directory,
        config=config,
        agent_id_for_implementation=_agent_id_for_implementation,
        sessions=sessions,
    )
    workflow_holder["workflows"] = services.workflows
    if implemented_admin_interfaces and not services.registry.health.live_local_agent_ids():
        log.warning(
            "Registry admin_interfaces configured but no agent enrollment found. "
            "Event publishing and delegation will not work until bots enroll."
        )

    transport_build = build_runtime_transport_stack(
        config,
        provider,
        services=services,
        bus=bus,
        directory=directory,
    )

    bot_runtime = BotRuntime(
        config=config,
        transport=transport_build.dispatcher,
        registry=services.registry,
        provider=provider,
        sessions=sessions,
        workflows=services.workflows,
        authorization=services.authorization,
        work_queue=services.work_queue,
        control_plane=services.control_plane,
        execution_services=services.execution_services,
        boot_id=transport_build.boot_id,
        cancellations=transport_build.telegram_runtime.cancellation_registry,
        execution_inflight=getattr(
            transport_build.telegram_runtime,
            "execution_inflight",
            set(),
        ),
    )

    return RuntimeBuild(
        boot_id=transport_build.boot_id,
        services=services,
        bot_runtime=bot_runtime,
    )
