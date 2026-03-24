"""Realtime registry websocket and progress contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CollectionTopic = Literal[
    "summary",
    "agents",
    "conversations",
    "tasks",
    "approvals",
    "usage",
]


class ConversationProgressUpdate(BaseModel):
    """Ephemeral operator-visible progress for one conversation."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1)
    created_at: str = Field(..., min_length=1)


class RealtimeEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["event"]
    data: dict[str, Any]


class RealtimeHeartbeatEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["heartbeat"]
    data: dict[str, Any]


class RealtimeProgressEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["progress"]
    data: dict[str, Any]


class RealtimeInvalidationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: CollectionTopic
    reason: str = Field(..., min_length=1)
    conversation_id: str = ""
    agent_id: str = ""
    routed_task_id: str = ""


class RealtimeInvalidationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["invalidate"]
    data: RealtimeInvalidationPayload
