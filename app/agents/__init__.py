"""Agent/registry foundation for multi-channel, multi-bot runtime."""

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.state import (
    BotIdentityState,
    bot_identity,
    load_bot_identity_state,
    load_registry_connection_state,
    save_registry_connection_state,
)
from app.agents.types import (
    AgentCard,
    AgentDiscoveryQuery,
    ConversationRef,
    RegistryConnectionConfig,
    RegistryConnectionState,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    ChannelBinding,
    ChannelEvent,
)

__all__ = [
    "AgentCard",
    "AgentDiscoveryQuery",
    "AgentRegistryClient",
    "AgentRuntime",
    "BotIdentityState",
    "ConversationRef",
    "RegistryClientError",
    "RegistryConnectionConfig",
    "RegistryConnectionState",
    "RoutedTaskRequest",
    "RoutedTaskResult",
    "RoutedTaskUpdate",
    "ChannelBinding",
    "ChannelEvent",
    "bot_identity",
    "load_bot_identity_state",
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
