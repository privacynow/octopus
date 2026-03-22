"""Registry SDK — contract types and client for bot ↔ registry communication.

Import direction: app/ may import from registry_sdk/. registry_sdk/ must NOT
import from app/.
"""

from registry_sdk.events import (
    ConversationEvent,
    EVENT_METADATA_SCHEMAS,
    ApprovalMetadata,
    DelegationMetadata,
    ErrorMetadata,
    FileChangeMetadata,
    MessageMetadata,
    ProviderResponseMetadata,
    TaskStatusMetadata,
    ToolExecutionMetadata,
)
from registry_sdk.agents import AgentCard
from registry_sdk.conversations import ConversationCreate
from registry_sdk.tasks import RoutedTaskRequest, RoutedTaskResult, RoutedTaskUpdate
from registry_sdk.discovery import AgentDiscoveryQuery, DiscoveredAgentRef

__all__ = [
    "ConversationEvent",
    "EVENT_METADATA_SCHEMAS",
    "ApprovalMetadata",
    "DelegationMetadata",
    "ErrorMetadata",
    "FileChangeMetadata",
    "MessageMetadata",
    "ProviderResponseMetadata",
    "TaskStatusMetadata",
    "ToolExecutionMetadata",
    "AgentCard",
    "ConversationCreate",
    "RoutedTaskRequest",
    "RoutedTaskResult",
    "RoutedTaskUpdate",
    "AgentDiscoveryQuery",
    "DiscoveredAgentRef",
]
