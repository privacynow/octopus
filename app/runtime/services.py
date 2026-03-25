"""Runtime-owned shared service containers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from octopus_sdk.agent_directory import AgentDirectoryPort
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.conversation_projection import ConversationProjectionPort
from octopus_sdk.conversation_projection import NoOpConversationProjection
from octopus_sdk.health_publication import HealthPublicationPort
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.task_routing import TaskRoutingPort
from octopus_sdk.task_routing import NoOpTaskRouting


@dataclass(frozen=True)
class ControlPlaneServices:
    conversation_projection: ConversationProjectionPort
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort
    health_publication: HealthPublicationPort


@dataclass(frozen=True)
class BotServices:
    control_plane: ControlPlaneServices


def build_noop_control_plane_services() -> ControlPlaneServices:
    return ControlPlaneServices(
        conversation_projection=NoOpConversationProjection(),
        task_routing=NoOpTaskRouting(),
        agent_directory=NoOpAgentDirectory(),
        health_publication=NoOpHealthPublication(),
    )


def build_bus_control_plane_services(
    bus: ControlPlaneBus,
    directory: ControlPlaneDirectory,
    *,
    agent_id_for_authority: Callable[[str], str] | None = None,
) -> ControlPlaneServices:
    from app.control_plane.adapters import (
        BusAgentDirectory,
        BusConversationProjection,
        BusHealthPublication,
        BusTaskRouting,
    )

    return ControlPlaneServices(
        conversation_projection=BusConversationProjection(
            bus, directory, agent_id_for_authority=agent_id_for_authority,
        ),
        task_routing=BusTaskRouting(bus, directory),
        agent_directory=BusAgentDirectory(bus, directory),
        health_publication=BusHealthPublication(bus, directory),
    )


def build_noop_bot_services() -> BotServices:
    return BotServices(control_plane=build_noop_control_plane_services())


def build_bus_bot_services(
    bus: ControlPlaneBus,
    directory: ControlPlaneDirectory,
    *,
    agent_id_for_authority: Callable[[str], str] | None = None,
) -> BotServices:
    return BotServices(
        control_plane=build_bus_control_plane_services(
            bus, directory, agent_id_for_authority=agent_id_for_authority,
        ),
    )
