"""Registry-inspection control-plane payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GetConversationRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1)


class GetTaskRequest(BaseModel):
    routed_task_id: str = Field(..., min_length=1)


class ListConversationEventsRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    kind: str = ""
    before_seq: int = Field(default=0, ge=0)
    after_seq: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
