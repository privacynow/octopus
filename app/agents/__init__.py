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
]


def __getattr__(name: str):
    if name == "AgentRuntime":
        from app.agents.runtime import AgentRuntime

        return AgentRuntime
    raise AttributeError(name)
