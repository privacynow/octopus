"""HTTP client for the central agent registry control plane."""

from __future__ import annotations

import httpx

from octopus_sdk.registry.models import AgentCard
from octopus_sdk.registry.client import RegistryClient as SdkRegistryClient
from octopus_sdk.registry.client import RegistryClientError
from octopus_sdk.registry.models import AckResult
from octopus_sdk.registry.models import AgentRecord
from octopus_sdk.registry.models import AgentDiscoveryQuery
from octopus_sdk.registry.models import CoordinationActionEnvelope
from octopus_sdk.registry.models import CoordinationActionResult
from octopus_sdk.registry.models import DeliveryPollResult
from octopus_sdk.registry.models import EnrollmentResult
from octopus_sdk.registry.models import HealthSummary
from octopus_sdk.registry.models import MessageRecord
from octopus_sdk.registry.models import RuntimeHealthPayload
from octopus_sdk.realtime import ConversationProgressUpdate as SdkConversationProgressUpdate
from octopus_sdk.registry.models import TaskRecord
from octopus_sdk.registry.models import RoutedTaskRequest
from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.registry.models import RoutedTaskUpdate


def _sdk_conversation_progress(content: str, *, created_at: str) -> SdkConversationProgressUpdate:
    return SdkConversationProgressUpdate(content=content, created_at=created_at)


class AgentRegistryClient(SdkRegistryClient):
    def __init__(
        self,
        base_url: str,
        *,
        agent_token: str = "",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            base_url,
            agent_token=agent_token,
            timeout_seconds=timeout_seconds,
            client=client,
        )

    async def enroll(self, card: AgentCard, enrollment_token: str) -> EnrollmentResult:
        return await super().enroll(enrollment_token, card)

    async def register(
        self,
        card: AgentCard,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
    ) -> HealthSummary:
        return await super().register(
            card,
            connectivity_state=connectivity_state,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
        )

    async def heartbeat(
        self,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
        runtime_health: RuntimeHealthPayload | None = None,
    ) -> HealthSummary:
        return await super().heartbeat(
            connectivity_state=connectivity_state,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            runtime_health=runtime_health,
        )

    async def search(self, query: AgentDiscoveryQuery) -> list[AgentRecord]:
        return await super().search(query)

    async def add_message(self, conversation_id: str, text: str) -> MessageRecord:
        return await super().add_message(conversation_id, text)

    async def submit_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        return await super().submit_action(conversation_id, envelope)

    async def submit_routed_task(self, request: RoutedTaskRequest) -> TaskRecord:
        return await super().submit_routed_task(request)

    async def routed_task_status(
        self,
        routed_task_id: str,
        update: RoutedTaskUpdate,
    ) -> TaskRecord:
        return await super().routed_task_status(
            routed_task_id,
            update,
        )

    async def routed_task_result(
        self,
        routed_task_id: str,
        result: RoutedTaskResult,
    ) -> TaskRecord:
        return await super().routed_task_result(
            routed_task_id,
            result,
        )

    async def poll(
        self,
        *,
        cursor: str = "0",
        limit: int = 20,
        wait_seconds: int = 1,
        kind_filter: list[str] | tuple[str, ...] | None = None,
    ) -> DeliveryPollResult:
        return await super().poll(
            cursor=cursor,
            limit=limit,
            wait_seconds=wait_seconds,
            kind_filter=kind_filter,
        )

    async def ack(self, delivery_ids: list[str], classification: str = "accepted") -> AckResult:
        return await super().ack(delivery_ids, classification=classification)

    async def deregister(self) -> AgentRecord:
        return await super().deregister()

    async def renew_enrollment(self, agent_id: str, card: AgentCard) -> EnrollmentResult:
        return await super().renew_enrollment(agent_id, card)

    async def publish_progress(
        self,
        conversation_id: str,
        *,
        content: str,
        created_at: str,
    ) -> None:
        await super().publish_progress(
            conversation_id,
            _sdk_conversation_progress(content, created_at=created_at),
        )
