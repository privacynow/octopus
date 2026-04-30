"""Registry projection subpackage for Octopus SDK.

Exports are resolved lazily so model-only imports do not eagerly pull in the
HTTP client layer during SDK bootstrap.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_EXPORTS = {
    "RegistryAuthorityClient": "octopus_sdk.registry.authority_client",
    "RegistryClient": "octopus_sdk.registry.client",
    "RegistryClientError": "octopus_sdk.registry.client",
    "AckResult": "octopus_sdk.registry.models",
    "AgentCard": "octopus_sdk.registry.models",
    "AgentDiscoveryQuery": "octopus_sdk.registry.models",
    "AgentRecord": "octopus_sdk.registry.models",
    "ConversationCreate": "octopus_sdk.registry.models",
    "ConversationProgressUpdate": "octopus_sdk.registry.models",
    "ConversationRecord": "octopus_sdk.registry.models",
    "DeliveryPollResult": "octopus_sdk.registry.models",
    "DeliveryRecord": "octopus_sdk.registry.models",
    "DiscoveredAgentRef": "octopus_sdk.registry.models",
    "EnrollmentResult": "octopus_sdk.registry.models",
    "EventRecord": "octopus_sdk.registry.models",
    "HealthSummary": "octopus_sdk.registry.models",
    "MessageRecord": "octopus_sdk.registry.models",
    "MirrorOutcome": "octopus_sdk.registry.models",
    "RuntimeHealthPayload": "octopus_sdk.registry.models",
    "RoutedTaskRequest": "octopus_sdk.registry.models",
    "RoutedTaskResult": "octopus_sdk.registry.models",
    "RoutedTaskUpdate": "octopus_sdk.registry.models",
    "TargetResolutionPreview": "octopus_sdk.registry.models",
    "TaskRecord": "octopus_sdk.registry.models",
    "TimelineEventPayload": "octopus_sdk.registry.models",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from octopus_sdk.registry.authority_client import RegistryAuthorityClient
    from octopus_sdk.registry.client import RegistryClient, RegistryClientError
    from octopus_sdk.registry.models import (
        AckResult,
        AgentCard,
        AgentDiscoveryQuery,
        AgentRecord,
        ConversationCreate,
        ConversationProgressUpdate,
        ConversationRecord,
        DeliveryPollResult,
        DeliveryRecord,
        DiscoveredAgentRef,
        EnrollmentResult,
        EventRecord,
        HealthSummary,
        MessageRecord,
        MirrorOutcome,
        RuntimeHealthPayload,
        RoutedTaskRequest,
        RoutedTaskResult,
        RoutedTaskUpdate,
        TargetResolutionPreview,
        TaskRecord,
        TimelineEventPayload,
    )
