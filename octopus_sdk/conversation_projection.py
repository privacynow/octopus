"""Shared control-plane port for external conversation projection."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import CoordinationActionEnvelope, CoordinationActionResult
from octopus_sdk.registry.models import MessageRecord


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
        events: list[ConversationEvent],
    ) -> None:
        """Publish events to a registry conversation. Idempotent on event_id."""
        ...

    async def add_message(
        self,
        *,
        conversation_id: str,
        text: str,
    ) -> MessageRecord:
        """Add one operator/channel message to an existing conversation."""
        ...

    async def submit_action(
        self,
        *,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        """Submit one typed coordination action for an existing conversation."""
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
        events: list[ConversationEvent],
    ) -> None:
        del conversation_id, events

    async def add_message(
        self,
        *,
        conversation_id: str,
        text: str,
    ) -> MessageRecord:
        del conversation_id, text
        return MessageRecord(accepted=False)

    async def submit_action(
        self,
        *,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        del conversation_id, envelope
        return CoordinationActionResult(
            conversation_id="",
            action_id="",
            action="",
            accepted=False,
            status="unavailable",
        )
