"""Conversation types for the registry SDK."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class ConversationCreate(BaseModel):
    """Request body for POST /v1/conversations (get-or-create).

    All three identity fields are required and non-empty. The registry enforces
    a unique constraint on (target_agent_id, origin_channel, external_conversation_ref).
    """

    model_config = ConfigDict(extra="forbid")

    target_agent_id: str
    origin_channel: str
    external_conversation_ref: str
    title: str = ""

    @field_validator("target_agent_id", "origin_channel", "external_conversation_ref")
    @classmethod
    def must_not_be_blank(cls, v: str, info) -> str:
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return v.strip()
