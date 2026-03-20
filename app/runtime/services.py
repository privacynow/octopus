"""Runtime-owned shared service containers."""

from __future__ import annotations

from dataclasses import dataclass

from app.ports.agent_directory import AgentDirectoryPort
from app.ports.conversation_projection import ConversationProjectionPort
from app.ports.health_publication import HealthPublicationPort
from app.ports.task_routing import TaskRoutingPort


@dataclass(frozen=True)
class ControlPlaneServices:
    conversation_projection: ConversationProjectionPort
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort
    health_publication: HealthPublicationPort


@dataclass(frozen=True)
class BotServices:
    control_plane: ControlPlaneServices
