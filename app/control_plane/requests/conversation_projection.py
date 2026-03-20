"""Conversation-projection control-plane payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BindConversationRequest(BaseModel):
    conversation_ref: str = Field(..., min_length=1)
    title: str = ""
    origin_channel: str = Field(..., min_length=1)
    external_id: str = Field(..., min_length=1)


class PublishTimelineRequest(BaseModel):
    conversation_ref: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str = ""
    status: str = ""
    progress: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None
