"""Agent/registry foundation for multi-channel, multi-bot runtime."""

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.state import (
    AgentRuntimeState,
    BotIdentityState,
    bot_identity,
    load_agent_runtime_state,
    load_bot_identity_state,
    load_registry_connection_state,
    save_agent_runtime_state,
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
    TimelineEvent,
)

__all__ = [
    "AgentCard",
    "AgentDiscoveryQuery",
    "AgentRegistryClient",
    "AgentRuntime",
    "AgentRuntimeState",
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
    "TimelineEvent",
    "bot_identity",
    "load_agent_runtime_state",
    "load_bot_identity_state",
    "load_registry_connection_state",
    "save_agent_runtime_state",
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
