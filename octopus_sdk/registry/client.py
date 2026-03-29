"""HTTP client for bot -> registry communication.

Methods are async (HTTP I/O). This does not imply the registry store should be
async — the client and store run in different processes.
"""

from __future__ import annotations

from typing import TypeVar

import httpx
from pydantic import BaseModel

from octopus_sdk.events import ConversationEvent, validate_event_metadata
from octopus_sdk.registry.management import ManagementResult
from octopus_sdk.registry.models import (
    AckResult,
    AgentCard,
    AgentDiscoveryQuery,
    AgentRecord,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    ConversationCreate,
    ConversationRecord,
    ConversationProgressUpdate,
    DeliveryPollResult,
    EnrollmentResult,
    HealthSummary,
    MessageRecord,
    RuntimeHealthPayload,
    RoutedTaskRequest,
    RoutedTaskResult,
    TaskRecord,
    RoutedTaskUpdate,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class RegistryClientError(RuntimeError):
    """Raised when the registry returns a non-success response."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "registry_request_failed",
        operator_detail: str = "",
        status_code: int | None = None,
    ) -> None:
        self.error_code = error_code
        self.operator_detail = operator_detail or message
        self.status_code = status_code
        super().__init__(message)


def _registry_http_error_code(status_code: int) -> str:
    if status_code in {401, 403}:
        return "registry_auth_failed"
    if status_code in {408, 504}:
        return "registry_timeout"
    if status_code >= 500:
        return "registry_server_error"
    return "registry_request_failed"


def _validated_model(
    value: ModelT | Mapping[str, object],
    schema: type[ModelT],
) -> ModelT:
    if isinstance(value, schema):
        return value
    return schema.model_validate(dict(value))


class RegistryClient:
    """Async HTTP client wrapping the registry's /v1/ endpoints."""

    def __init__(
        self,
        base_url: str,
        agent_token: str = "",
        *,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_token = agent_token
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _headers(self, *, require_auth: bool) -> dict[str, str]:
        headers: dict[str, str] = {}
        if require_auth:
            if not self._agent_token:
                raise RegistryClientError(
                    "Missing agent token for authenticated registry call",
                    error_code="registry_auth_failed",
                    operator_detail="Authenticated registry call attempted without an agent token.",
                )
            headers["Authorization"] = f"Bearer {self._agent_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        require_auth: bool = True,
        **kwargs: object,
    ) -> object:
        headers = self._headers(require_auth=require_auth)

        async def _do(client: httpx.AsyncClient) -> object:
            try:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                raise RegistryClientError(
                    f"Registry {method} {path} timed out",
                    error_code="registry_timeout",
                    operator_detail=f"Registry {method} {path} timed out ({exc.__class__.__name__}).",
                ) from exc
            except httpx.RequestError as exc:
                raise RegistryClientError(
                    f"Registry {method} {path} failed",
                    error_code="registry_unreachable",
                    operator_detail=(
                        f"Registry {method} {path} failed with {exc.__class__.__name__}."
                    ),
                ) from exc
            if response.status_code >= 400:
                raise RegistryClientError(
                    f"Registry {method} {path} failed: HTTP {response.status_code}",
                    error_code=_registry_http_error_code(response.status_code),
                    operator_detail=f"Registry {method} {path} failed with HTTP {response.status_code}.",
                    status_code=response.status_code,
                )
            if response.status_code == 204 or not response.content:
                return {}
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text

        if self._client is not None:
            return await _do(self._client)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await _do(client)

    async def create_conversation(
        self,
        *,
        target_agent_id: str,
        origin_channel: str,
        external_conversation_ref: str,
        title: str = "",
    ) -> ConversationRecord:
        """Idempotent get-or-create. Returns { conversation_id, ... }."""
        payload = ConversationCreate(
            target_agent_id=target_agent_id,
            origin_channel=origin_channel,
            external_conversation_ref=external_conversation_ref,
            title=title,
        )
        result = await self._request("POST", "/v1/conversations", json=payload.model_dump())
        return ConversationRecord.model_validate(result)

    async def get_conversation(self, conversation_id: str) -> ConversationRecord:
        result = await self._request("GET", f"/v1/conversations/{conversation_id}")
        return ConversationRecord.model_validate(result)

    async def add_message(self, conversation_id: str, text: str) -> MessageRecord:
        result = await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            json={"text": text},
        )
        return MessageRecord.model_validate(result)

    async def submit_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        payload = _validated_model(envelope, CoordinationActionEnvelope)
        result = await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/actions",
            json=payload.model_dump(exclude_unset=True),
        )
        return CoordinationActionResult.model_validate(result)

    async def get_agent_status(self, agent_id: str) -> AgentRecord:
        result = await self._request("GET", f"/v1/agents/{agent_id}/status")
        return AgentRecord.model_validate(result)

    async def publish_events(
        self,
        conversation_id: str,
        events: list[ConversationEvent],
    ) -> None:
        """Publish events to a conversation. Idempotent on event_id."""
        validated_events = [
            event.model_copy(update={"metadata": validate_event_metadata(event)})
            for event in events
        ]
        await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/events",
            json={"events": [event.model_dump() for event in validated_events]},
        )

    async def publish_progress(
        self,
        conversation_id: str,
        progress: ConversationProgressUpdate,
    ) -> None:
        payload = _validated_model(progress, ConversationProgressUpdate)
        await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/progress",
            json=payload.model_dump(),
        )

    async def enroll(
        self,
        enrollment_token: str,
        card: AgentCard,
    ) -> EnrollmentResult:
        """Enroll a new agent. No bearer token needed — uses enrollment_token in body."""
        agent_card = _validated_model(card, AgentCard)
        result = await self._request(
            "POST",
            "/v1/agents/enroll",
            json={
                "enrollment_token": enrollment_token,
                "agent_card": agent_card.model_dump(exclude_unset=True),
            },
            require_auth=False,
        )
        return EnrollmentResult.model_validate(result)

    async def register(
        self,
        card: AgentCard,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
    ) -> HealthSummary:
        agent_card = _validated_model(card, AgentCard)
        payload = {
            "agent_card": agent_card.model_dump(exclude_unset=True),
            "connectivity_state": connectivity_state,
            "current_capacity": current_capacity,
            "max_capacity": max_capacity,
        }
        result = await self._request("POST", "/v1/agents/register", json=payload)
        return HealthSummary.model_validate(result)

    async def heartbeat(
        self,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
        runtime_health: RuntimeHealthPayload | None = None,
    ) -> HealthSummary:
        payload: dict[str, object] = {
            "connectivity_state": connectivity_state,
            "current_capacity": current_capacity,
            "max_capacity": max_capacity,
        }
        if runtime_health is not None:
            payload["runtime_health"] = _validated_model(
                runtime_health,
                RuntimeHealthPayload,
            ).model_dump(exclude_unset=True)
        result = await self._request("POST", "/v1/agents/heartbeat", json=payload)
        return HealthSummary.model_validate(result)

    async def search(
        self,
        query: AgentDiscoveryQuery,
    ) -> list[AgentRecord]:
        payload = _validated_model(query, AgentDiscoveryQuery)
        result = await self._request(
            "POST",
            "/v1/agents/discovery/search",
            json=payload.model_dump(exclude_unset=True),
        )
        return [AgentRecord.model_validate(item) for item in list(result.get("agents", []))]

    async def submit_routed_task(
        self,
        request: RoutedTaskRequest,
    ) -> TaskRecord:
        payload = _validated_model(request, RoutedTaskRequest)
        body = payload.model_dump(exclude_unset=True)
        # created_at is server-visible request identity and must survive the client dump
        # even when populated by the model default.
        body["created_at"] = payload.created_at
        result = await self._request(
            "POST",
            "/v1/agents/routed-tasks",
            json=body,
        )
        return TaskRecord.model_validate(result)

    async def routed_task_status(
        self,
        routed_task_id: str,
        update: RoutedTaskUpdate,
    ) -> TaskRecord:
        payload = _validated_model(update, RoutedTaskUpdate)
        body = payload.model_dump(exclude_unset=True)
        # The routed task id is carried in the URL path; the registry rejects it in the body.
        body.pop("routed_task_id", None)
        body["updated_at"] = payload.updated_at
        body["transition_id"] = payload.transition_id
        result = await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/status",
            json=body,
        )
        return TaskRecord.model_validate(result)

    async def routed_task_result(
        self,
        routed_task_id: str,
        result: RoutedTaskResult,
    ) -> TaskRecord:
        payload = _validated_model(result, RoutedTaskResult)
        body = payload.model_dump(exclude_unset=True)
        # The routed task id is carried in the URL path; the registry rejects it in the body.
        body.pop("routed_task_id", None)
        body["completed_at"] = payload.completed_at
        body["transition_id"] = payload.transition_id
        response = await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/result",
            json=body,
        )
        return TaskRecord.model_validate(response)

    async def management_result(
        self,
        request_id: str,
        result: ManagementResult,
    ) -> ManagementResult:
        payload = _validated_model(result, ManagementResult)
        body = payload.model_dump(by_alias=True)
        response = await self._request(
            "POST",
            f"/v1/agents/management-requests/{request_id}/result",
            json=body,
        )
        return ManagementResult.model_validate(response)

    async def poll(
        self,
        *,
        cursor: str = "0",
        limit: int = 20,
        wait_seconds: int = 1,
        kind_filter: list[str] | tuple[str, ...] | None = None,
    ) -> DeliveryPollResult:
        params: dict[str, object] = {
            "cursor": cursor,
            "limit": limit,
            "wait_seconds": wait_seconds,
        }
        if kind_filter is not None:
            params["kind_filter"] = list(kind_filter)
        result = await self._request("GET", "/v1/agents/poll", params=params)
        return DeliveryPollResult.model_validate(result)

    async def ack(self, delivery_ids: list[str], classification: str = "accepted") -> AckResult:
        result = await self._request("POST", "/v1/agents/ack", json={
            "delivery_ids": delivery_ids,
            "classification": classification,
        })
        return AckResult.model_validate(result)

    async def deregister(self) -> AgentRecord:
        result = await self._request("POST", "/v1/agents/deregister", json={})
        return AgentRecord.model_validate(result)

    async def renew_enrollment(
        self,
        agent_id: str,
        card: AgentCard,
    ) -> EnrollmentResult:
        del agent_id
        agent_card = _validated_model(card, AgentCard)
        summary = await self.register(
            agent_card,
            connectivity_state=agent_card.connectivity_state or "connected",
            current_capacity=agent_card.current_capacity,
            max_capacity=agent_card.max_capacity,
        )
        agent = summary.agent
        return EnrollmentResult(
            agent_id=agent.agent_id if agent is not None else "",
            agent_token=self._agent_token,
            slug=agent.slug if agent is not None else agent_card.slug,
            poll_cursor="0",
        )

    async def disconnect_agent(self, agent_id: str) -> AgentRecord:
        return await self.deregister()

    async def fail_delivery(self, delivery_id: str, reason: str = "") -> AckResult:
        return await self.ack([delivery_id], classification="rejected")
