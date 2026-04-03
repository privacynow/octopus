"""Agent/registry foundation for multi-channel, multi-bot runtime."""

from app.agents.state import (
    RegistryConnectionState,
    load_registry_connection_state,
    save_registry_connection_state,
)
from octopus_sdk.config import RegistryConnectionConfig
from octopus_sdk.registry.client import RegistryClient, RegistryClientError
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
    "RegistryClient",
    "RegistryClientError",
    "RegistryConnectionConfig",
    "RegistryConnectionState",
    "RoutedTaskRequest",
    "RoutedTaskResult",
    "RoutedTaskUpdate",
    "load_registry_connection_state",
    "save_registry_connection_state",
]
