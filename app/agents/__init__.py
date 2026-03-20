"""Agent/registry foundation for multi-channel, multi-bot runtime."""

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.runtime import AgentRuntime, start_agent_runtime_task
from app.agents.state import (
    AgentRuntimeState,
    BotIdentityState,
    bot_identity,
    load_agent_runtime_state,
    load_bot_identity_state,
    save_agent_runtime_state,
)
from app.agents.types import (
    AgentCard,
    AgentDiscoveryQuery,
    ConversationRef,
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
    "RoutedTaskRequest",
    "RoutedTaskResult",
    "RoutedTaskUpdate",
    "ChannelBinding",
    "ChannelEvent",
    "TimelineEvent",
    "bot_identity",
    "load_agent_runtime_state",
    "load_bot_identity_state",
    "save_agent_runtime_state",
    "start_agent_runtime_task",
]
