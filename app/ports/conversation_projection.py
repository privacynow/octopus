"""Shared control-plane port for external conversation projection."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ConversationProjectionPort(Protocol):
    async def create_conversation(
        self,
        *,
        target_agent_id: str,
        origin_channel: str,
        external_conversation_ref: str,
        title: str,
    ) -> str:
        """Idempotent get-or-create. Returns conversation_id."""
        ...

    async def publish_events(
        self,
        *,
        conversation_id: str,
        events: list,  # list of ConversationEvent
    ) -> None:
        """Publish events to a registry conversation. Idempotent on event_id."""
        ...


class NoOpConversationProjection:
    async def create_conversation(
        self,
        *,
        target_agent_id: str,
        origin_channel: str,
        external_conversation_ref: str,
        title: str,
    ) -> str:
        del target_agent_id, origin_channel, external_conversation_ref, title
        return ""

    async def publish_events(
        self,
        *,
        conversation_id: str,
        events: list,
    ) -> None:
        del conversation_id, events
