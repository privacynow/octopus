"""In-process WebSocket pub/sub for real-time registry event push."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket
from octopus_sdk.realtime import (
    RealtimeEventEnvelope,
    RealtimeHeartbeatEnvelope,
    RealtimeInvalidationEnvelope,
    RealtimeInvalidationPayload,
    RealtimeProgressEnvelope,
)

log = logging.getLogger(__name__)


@dataclass
class WSClient:
    ws: WebSocket
    subscriptions: set[str] = field(default_factory=set)  # "agent:<id>", "conversation:<id>"


class WebSocketManager:
    """In-process pub/sub. Single-process only — no cross-replica broadcast."""

    def __init__(self) -> None:
        self._clients: list[WSClient] = []

    async def connect(self, ws: WebSocket) -> WSClient:
        await ws.accept()
        client = WSClient(ws=ws)
        self._clients.append(client)
        return client

    def disconnect(self, client: WSClient) -> None:
        if client in self._clients:
            self._clients.remove(client)

    async def handle_subscription(self, client: WSClient, message: dict) -> None:
        """Process subscription messages: {"subscribe": ["agent:x", "conversation:y"]}"""
        if message.get("ping"):
            await client.ws.send_text(json.dumps({"pong": True}))
            return
        if "subscribe" in message:
            for topic in message["subscribe"]:
                client.subscriptions.add(topic)
        if "unsubscribe" in message:
            for topic in message["unsubscribe"]:
                client.subscriptions.discard(topic)

    async def _broadcast_topics(self, topics: set[str], message: dict) -> None:
        encoded = json.dumps(message)
        disconnected: list[WSClient] = []
        for client in self._clients:
            if client.subscriptions & topics:
                try:
                    await client.ws.send_text(encoded)
                except Exception:
                    disconnected.append(client)
        for client in disconnected:
            self.disconnect(client)

    async def broadcast_event(self, conversation_id: str, agent_id: str, event_data: dict) -> None:
        """Push event to clients subscribed to the conversation or agent."""
        topics = {f"conversation:{conversation_id}", f"agent:{agent_id}"}
        await self._broadcast_topics(
            topics,
            RealtimeEventEnvelope(type="event", data=event_data).model_dump(),
        )

    async def broadcast_heartbeat(self, agent_id: str, status_data: dict) -> None:
        """Push agent status update to subscribers."""
        topic = f"agent:{agent_id}"
        await self._broadcast_topics(
            {topic},
            RealtimeHeartbeatEnvelope(type="heartbeat", data=status_data).model_dump(),
        )

    async def broadcast_progress(self, conversation_id: str, agent_id: str, progress_data: dict) -> None:
        topics = {f"conversation:{conversation_id}", f"agent:{agent_id}"}
        await self._broadcast_topics(
            topics,
            RealtimeProgressEnvelope(type="progress", data=progress_data).model_dump(),
        )

    async def broadcast_invalidation(
        self,
        topic: str,
        *,
        reason: str,
        conversation_id: str = "",
        agent_id: str = "",
        routed_task_id: str = "",
    ) -> None:
        await self._broadcast_topics(
            {topic},
            RealtimeInvalidationEnvelope(
                type="invalidate",
                data=RealtimeInvalidationPayload(
                    topic=topic,
                    reason=reason,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    routed_task_id=routed_task_id,
                ),
            ).model_dump(),
        )
