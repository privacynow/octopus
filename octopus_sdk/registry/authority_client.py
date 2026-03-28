"""SDK authority-client contract for bot <-> registry server communication."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    AckResult,
    AgentCard,
    AgentDiscoveryQuery,
    AgentId,
    AgentRecord,
    CoordinationActionEnvelope,
    ConversationCreate,
    ConversationId,
    ConversationRecord,
    DeliveryId,
    DeliveryPollResult,
    EnrollmentResult,
    HealthSummary,
    MessageRecord,
    RuntimeHealthPayload,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    TaskRecord,
    TargetSelector,
)
from octopus_sdk.registry.management import ManagementResult


@runtime_checkable
class RegistryAuthorityClient(Protocol):
    async def enroll(self, enrollment_token: str, card: AgentCard) -> EnrollmentResult: ...

    async def renew_enrollment(self, agent_id: AgentId, card: AgentCard) -> EnrollmentResult: ...

    async def disconnect_agent(self, agent_id: AgentId) -> AgentRecord: ...

    async def heartbeat(
        self,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
        runtime_health: RuntimeHealthPayload | None = None,
    ) -> HealthSummary: ...

    async def poll(
        self,
        *,
        cursor: str = "0",
        limit: int = 20,
        wait_seconds: int = 1,
        kind_filter: list[str] | tuple[str, ...] | None = None,
    ) -> DeliveryPollResult: ...

    async def ack(self, delivery_ids: list[str], classification: str = "accepted") -> AckResult: ...

    async def fail_delivery(self, delivery_id: str, reason: str = "") -> AckResult: ...

    async def create_conversation(self, *, target_agent_id: AgentId, origin_channel: str, external_conversation_ref: str, title: str = "") -> ConversationRecord: ...

    async def get_conversation(self, conversation_id: ConversationId) -> ConversationRecord: ...

    async def add_message(self, conversation_id: ConversationId, text: str) -> MessageRecord: ...

    async def submit_action(
        self,
        conversation_id: ConversationId,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult: ...

    async def publish_events(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> None: ...

    async def search(self, query: AgentDiscoveryQuery) -> list[AgentRecord]: ...

    async def submit_routed_task(self, request: RoutedTaskRequest) -> TaskRecord: ...

    async def routed_task_status(
        self,
        routed_task_id: str,
        update: RoutedTaskUpdate,
    ) -> TaskRecord: ...

    async def routed_task_result(
        self,
        routed_task_id: str,
        result: RoutedTaskResult,
    ) -> TaskRecord: ...

    async def management_result(
        self,
        request_id: str,
        result: ManagementResult,
    ) -> ManagementResult: ...
