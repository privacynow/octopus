"""HTTP client for bot → registry communication.

Methods are async (HTTP I/O). This does not imply the registry store should be
async — the client and store run in different processes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel

from registry_sdk.agents import AgentCard
from registry_sdk.conversations import ConversationCreate
from registry_sdk.discovery import AgentDiscoveryQuery
from registry_sdk.events import ConversationEvent, validate_event_metadata
from registry_sdk.realtime import ConversationProgressUpdate
from registry_sdk.tasks import RoutedTaskRequest, RoutedTaskResult, RoutedTaskUpdate


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
    value: BaseModel | Mapping[str, Any],
    schema: type[BaseModel],
) -> BaseModel:
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
        **kwargs: Any,
    ) -> Any:
        headers = self._headers(require_auth=require_auth)

        async def _do(client: httpx.AsyncClient) -> Any:
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
    ) -> dict[str, Any]:
        """Idempotent get-or-create. Returns { conversation_id, ... }."""
        payload = ConversationCreate(
            target_agent_id=target_agent_id,
            origin_channel=origin_channel,
            external_conversation_ref=external_conversation_ref,
            title=title,
        )
        return await self._request("POST", "/v1/conversations", json=payload.model_dump())

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/conversations/{conversation_id}")

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
        progress: ConversationProgressUpdate | Mapping[str, Any],
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
        card: AgentCard | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Enroll a new agent. No bearer token needed — uses enrollment_token in body."""
        agent_card = _validated_model(card, AgentCard)
        return await self._request(
            "POST",
            "/v1/agents/enroll",
            json={
                "enrollment_token": enrollment_token,
                "agent_card": agent_card.model_dump(exclude_unset=True),
            },
            require_auth=False,
        )

    async def register(
        self,
        card: AgentCard | Mapping[str, Any],
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
    ) -> dict[str, Any]:
        agent_card = _validated_model(card, AgentCard)
        payload = {
            "agent_card": agent_card.model_dump(exclude_unset=True),
            "connectivity_state": connectivity_state,
            "current_capacity": current_capacity,
            "max_capacity": max_capacity,
        }
        return await self._request("POST", "/v1/agents/register", json=payload)

    async def heartbeat(
        self,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
        runtime_health: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connectivity_state": connectivity_state,
            "current_capacity": current_capacity,
            "max_capacity": max_capacity,
        }
        if runtime_health is not None:
            payload["runtime_health"] = runtime_health
        return await self._request("POST", "/v1/agents/heartbeat", json=payload)

    async def search(
        self,
        query: AgentDiscoveryQuery | Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        payload = _validated_model(query, AgentDiscoveryQuery)
        result = await self._request(
            "POST",
            "/v1/agents/discovery/search",
            json=payload.model_dump(exclude_unset=True),
        )
        return list(result.get("agents", []))

    async def submit_routed_task(
        self,
        request: RoutedTaskRequest | Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = _validated_model(request, RoutedTaskRequest)
        return await self._request(
            "POST",
            "/v1/agents/routed-tasks",
            json=payload.model_dump(exclude_unset=True),
        )

    async def routed_task_status(
        self,
        routed_task_id: str,
        update: RoutedTaskUpdate | Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = _validated_model(update, RoutedTaskUpdate)
        return await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/status",
            json=payload.model_dump(exclude_unset=True),
        )

    async def routed_task_result(
        self,
        routed_task_id: str,
        result: RoutedTaskResult | Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = _validated_model(result, RoutedTaskResult)
        return await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/result",
            json=payload.model_dump(exclude_unset=True),
        )

    async def poll(
        self,
        *,
        cursor: str = "0",
        limit: int = 20,
        wait_seconds: int = 1,
        kind_filter: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "cursor": cursor,
            "limit": limit,
            "wait_seconds": wait_seconds,
        }
        if kind_filter is not None:
            params["kind_filter"] = list(kind_filter)
        return await self._request("GET", "/v1/agents/poll", params=params)

    async def ack(self, delivery_ids: list[str], classification: str = "accepted") -> dict[str, Any]:
        return await self._request("POST", "/v1/agents/ack", json={
            "delivery_ids": delivery_ids,
            "classification": classification,
        })

    async def deregister(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/agents/deregister", json={})
