"""Agent/registry foundation for multi-channel, multi-bot runtime."""

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.state import (
    RegistryConnectionState,
    load_registry_connection_state,
    save_registry_connection_state,
)
from octopus_sdk.config import RegistryConnectionConfig
from octopus_sdk.registry.models import (
    AgentCard,
    AgentDiscoveryQuery,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
)

__all__ = [
    "AgentCard",
    "AgentDiscoveryQuery",
    "AgentRegistryClient",
    "AgentRuntime",
    "RegistryClientError",
    "RegistryConnectionConfig",
    "RegistryConnectionState",
    "RoutedTaskRequest",
    "RoutedTaskResult",
    "RoutedTaskUpdate",
    "load_registry_connection_state",
    "save_registry_connection_state",
    "AgentRuntime",
    "start_agent_runtime_task",
]


def __getattr__(name: str):
    if name in {"AgentRuntime", "start_agent_runtime_task"}:
        from app.agents.runtime import AgentRuntime, start_agent_runtime_task

        return {
            "AgentRuntime": AgentRuntime,
            "start_agent_runtime_task": start_agent_runtime_task,
        }[name]
    raise AttributeError(name)
