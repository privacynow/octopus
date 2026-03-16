"""HTTP client for the central agent registry control plane."""

from __future__ import annotations

from typing import Any

import httpx

from app.agents.types import (
    AgentCard,
    AgentDiscoveryQuery,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    TimelineEvent,
    to_wire,
)


class RegistryClientError(RuntimeError):
    """Registry request failed or returned an unexpected response."""


class AgentRegistryClient:
    def __init__(
        self,
        base_url: str,
        *,
        agent_token: str = "",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.agent_token = agent_token
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        require_auth: bool = True,
    ) -> Any:
        headers: dict[str, str] = {}
        if require_auth:
            if not self.agent_token:
                raise RegistryClientError("Missing agent token for authenticated registry call")
            headers["Authorization"] = f"Bearer {self.agent_token}"

        async def _do(client: httpx.AsyncClient) -> Any:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                json=json_data,
                params=params,
                headers=headers,
            )
            if response.status_code >= 400:
                raise RegistryClientError(
                    f"Registry {method} {path} failed: {response.status_code} {response.text}"
                )
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text

        if self._client is not None:
            return await _do(self._client)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await _do(client)

    async def enroll(self, card: AgentCard, enrollment_token: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/agents/enroll",
            json_data={
                "enrollment_token": enrollment_token,
                "agent_card": to_wire(card),
            },
            require_auth=False,
        )

    async def register(
        self,
        card: AgentCard,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/agents/register",
            json_data={
                "agent_card": to_wire(card),
                "connectivity_state": connectivity_state,
                "current_capacity": current_capacity,
                "max_capacity": max_capacity,
            },
        )

    async def heartbeat(
        self,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
        active_work_count: int = 0,
        timeline_checkpoint: str = "",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/agents/heartbeat",
            json_data={
                "connectivity_state": connectivity_state,
                "current_capacity": current_capacity,
                "max_capacity": max_capacity,
                "active_work_count": active_work_count,
                "timeline_checkpoint": timeline_checkpoint,
            },
        )

    async def publish_timeline(self, events: list[TimelineEvent], *, checkpoint: str = "") -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/agents/timeline",
            json_data={
                "events": [to_wire(event) for event in events],
                "checkpoint": checkpoint,
            },
        )

    async def sync_binding(
        self,
        *,
        conversation_id: str,
        title: str,
        origin_surface: str,
        external_id: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/agents/conversations/bind",
            json_data={
                "conversation_id": conversation_id,
                "title": title,
                "origin_surface": origin_surface,
                "external_id": external_id,
            },
        )

    async def search(self, query: AgentDiscoveryQuery) -> list[dict[str, Any]]:
        result = await self._request(
            "POST",
            "/v1/agents/discovery/search",
            json_data=to_wire(query),
        )
        return list(result.get("agents", []))

    async def submit_routed_task(self, request: RoutedTaskRequest) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/agents/routed-tasks",
            json_data=to_wire(request),
        )

    async def poll(self, *, cursor: str = "0", limit: int = 20, wait_seconds: int = 1) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/agents/poll",
            params={
                "cursor": cursor,
                "limit": limit,
                "wait_seconds": wait_seconds,
            },
        )

    async def ack(self, delivery_ids: list[str], *, classification: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/agents/ack",
            json_data={
                "delivery_ids": delivery_ids,
                "classification": classification,
            },
        )

    async def routed_task_status(self, routed_task_id: str, update: RoutedTaskUpdate) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/status",
            json_data=to_wire(update),
        )

    async def routed_task_result(self, routed_task_id: str, result: RoutedTaskResult) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/result",
            json_data=to_wire(result),
        )

    async def deregister(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/agents/deregister", json_data={})
