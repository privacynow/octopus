"""Conversation-projection control-plane payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field

from octopus_sdk.registry.models import CoordinationActionEnvelope


class AddConversationMessagePayload(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class SubmitConversationActionPayload(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    envelope: CoordinationActionEnvelope
