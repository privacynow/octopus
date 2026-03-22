"""Shared control-plane port for external conversation projection."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConversationProjectionPort(Protocol):
    async def bind_external_conversation(
        self,
        *,
        conversation_ref: str,
        title: str,
        origin_channel: str,
        external_id: str,
    ) -> None: ...

    async def publish_external_timeline(
        self,
        *,
        conversation_ref: str,
        kind: str,
        title: str,
        body: str = "",
        status: str = "",
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> None: ...


class NoOpConversationProjection:
    async def bind_external_conversation(
        self,
        *,
        conversation_ref: str,
        title: str,
        origin_channel: str,
        external_id: str,
    ) -> None:
        del conversation_ref, title, origin_channel, external_id
        return None

    async def publish_external_timeline(
        self,
        *,
        conversation_ref: str,
        kind: str,
        title: str,
        body: str = "",
        status: str = "",
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> None:
        del conversation_ref, kind, title, body, status, progress, metadata, event_id
        return None
