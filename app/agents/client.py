"""HTTP client for the central agent registry control plane."""

from __future__ import annotations

import httpx

from octopus_sdk.registry.models import AgentCard
from octopus_sdk.registry.client import RegistryClient as SdkRegistryClient
from octopus_sdk.registry.client import RegistryClientError
from octopus_sdk.registry.models import AgentDiscoveryQuery
from octopus_sdk.realtime import ConversationProgressUpdate as SdkConversationProgressUpdate
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

    async def enroll(self, card: AgentCard, enrollment_token: str) -> dict[str, object]:
        return await super().enroll(enrollment_token, card)

    async def register(
        self,
        card: AgentCard,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
    ) -> dict[str, object]:
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
        runtime_health: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return await super().heartbeat(
            connectivity_state=connectivity_state,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            runtime_health=runtime_health,
        )

    async def search(self, query: AgentDiscoveryQuery) -> list[dict[str, object]]:
        return await super().search(query)

    async def submit_routed_task(self, request: RoutedTaskRequest) -> dict[str, object]:
        return await super().submit_routed_task(request)

    async def routed_task_status(
        self,
        routed_task_id: str,
        update: RoutedTaskUpdate,
    ) -> dict[str, object]:
        return await super().routed_task_status(
            routed_task_id,
            update,
        )

    async def routed_task_result(
        self,
        routed_task_id: str,
        result: RoutedTaskResult,
    ) -> dict[str, object]:
        return await super().routed_task_result(
            routed_task_id,
            result,
        )

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
