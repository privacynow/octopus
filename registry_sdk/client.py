"""HTTP client for bot → registry communication.

Methods are async (HTTP I/O). This does not imply the registry store should be
async — the client and store run in different processes.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from registry_sdk.events import ConversationEvent, validate_event_metadata


class RegistryClientError(Exception):
    """Raised when the registry returns a non-success response."""

    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Registry error {status_code}: {detail}")


class RegistryClient:
    """Async HTTP client wrapping the registry's /v1/ endpoints."""

    def __init__(self, base_url: str, agent_token: str, *, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._agent_token = agent_token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._agent_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers(),
                **kwargs,
            )
        if resp.status_code >= 400:
            detail = resp.text[:500] if resp.text else ""
            raise RegistryClientError(resp.status_code, detail)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    async def create_conversation(
        self,
        *,
        target_agent_id: str,
        origin_channel: str,
        external_conversation_ref: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Idempotent get-or-create. Returns { conversation_id, ... }."""
        return await self._request("POST", "/v1/conversations", json={
            "target_agent_id": target_agent_id,
            "origin_channel": origin_channel,
            "external_conversation_ref": external_conversation_ref,
            "title": title,
        })

    async def publish_events(
        self,
        conversation_id: str,
        events: list[ConversationEvent],
    ) -> None:
        """Publish events to a conversation. Idempotent on event_id."""
        for event in events:
            validate_event_metadata(event)
        await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/events",
            json=[event.model_dump() for event in events],
        )

    async def enroll(self, enrollment_token: str, card: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers()
        headers["X-Enrollment-Token"] = enrollment_token
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/v1/agents/enroll",
                headers=headers,
                json=card,
            )
        if resp.status_code >= 400:
            raise RegistryClientError(resp.status_code, resp.text[:500])
        return resp.json()

    async def register(self, card: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        payload = {"agent_card": card, **kwargs}
        return await self._request("POST", "/v1/agents/register", json=payload)

    async def heartbeat(self, **kwargs: Any) -> dict[str, Any]:
        return await self._request("POST", "/v1/agents/heartbeat", json=kwargs)

    async def poll(self, cursor: str = "0", limit: int = 20) -> dict[str, Any]:
        return await self._request("GET", "/v1/agents/poll", params={"cursor": cursor, "limit": limit})

    async def ack(self, delivery_ids: list[str], classification: str = "accepted") -> dict[str, Any]:
        return await self._request("POST", "/v1/agents/ack", json={
            "delivery_ids": delivery_ids,
            "classification": classification,
        })
