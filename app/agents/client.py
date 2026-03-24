"""HTTP client for the central agent registry control plane."""

from __future__ import annotations

import httpx

from app.agents.types import (
    AgentCard,
    AgentDiscoveryQuery,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    to_wire,
)
from registry_sdk.agents import AgentCard as SdkAgentCard
from registry_sdk.client import RegistryClient as SdkRegistryClient
from registry_sdk.client import RegistryClientError
from registry_sdk.discovery import AgentDiscoveryQuery as SdkAgentDiscoveryQuery
from registry_sdk.realtime import ConversationProgressUpdate as SdkConversationProgressUpdate
from registry_sdk.tasks import RoutedTaskRequest as SdkRoutedTaskRequest
from registry_sdk.tasks import RoutedTaskResult as SdkRoutedTaskResult
from registry_sdk.tasks import RoutedTaskUpdate as SdkRoutedTaskUpdate


def _sdk_agent_card(card: AgentCard) -> SdkAgentCard:
    return SdkAgentCard.model_validate(to_wire(card))


def _sdk_discovery_query(query: AgentDiscoveryQuery) -> SdkAgentDiscoveryQuery:
    return SdkAgentDiscoveryQuery.model_validate(to_wire(query))


def _sdk_routed_task_request(request: RoutedTaskRequest) -> SdkRoutedTaskRequest:
    return SdkRoutedTaskRequest.model_validate(to_wire(request))


def _sdk_routed_task_update(update: RoutedTaskUpdate) -> SdkRoutedTaskUpdate:
    payload = dict(to_wire(update))
    payload.pop("routed_task_id", None)
    return SdkRoutedTaskUpdate.model_validate(payload)


def _sdk_routed_task_result(result: RoutedTaskResult) -> SdkRoutedTaskResult:
    payload = dict(to_wire(result))
    payload.pop("routed_task_id", None)
    return SdkRoutedTaskResult.model_validate(payload)


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
        return await super().enroll(enrollment_token, _sdk_agent_card(card))

    async def register(
        self,
        card: AgentCard,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
    ) -> dict[str, object]:
        return await super().register(
            _sdk_agent_card(card),
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
        return await super().search(_sdk_discovery_query(query))

    async def submit_routed_task(self, request: RoutedTaskRequest) -> dict[str, object]:
        return await super().submit_routed_task(_sdk_routed_task_request(request))

    async def routed_task_status(
        self,
        routed_task_id: str,
        update: RoutedTaskUpdate,
    ) -> dict[str, object]:
        return await super().routed_task_status(
            routed_task_id,
            _sdk_routed_task_update(update),
        )

    async def routed_task_result(
        self,
        routed_task_id: str,
        result: RoutedTaskResult,
    ) -> dict[str, object]:
        return await super().routed_task_result(
            routed_task_id,
            _sdk_routed_task_result(result),
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
