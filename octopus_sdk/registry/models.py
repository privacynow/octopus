"""Registry wire models used by clients, servers, and bot runtimes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from octopus_sdk.realtime import ConversationProgressUpdate


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentCard(BaseModel):
    """Agent identity and capability declaration sent during enrollment/registration."""

    model_config = ConfigDict(extra="forbid")

    bot_key: str = Field(..., min_length=1)
    display_name: str = ""
    slug: str = ""
    role: str = ""
    registry_scope: str = "full"
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    provider: str = ""
    mode: str = "standalone"
    connectivity_state: str = "standalone"
    current_capacity: int = 0
    max_capacity: int = 1
    channel_capabilities: list[str] = Field(default_factory=lambda: ["telegram"])
    version: str = "dev"


class ConversationCreate(BaseModel):
    """Request body for POST /v1/conversations (get-or-create)."""

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


class AgentDiscoveryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    free_text: str = ""
    exclude_agent_ids: list[str] = Field(default_factory=list)
    required_state: str = "connected"


class DiscoveredAgentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_ref: str
    agent_id: str
    display_name: str = ""
    slug: str = ""
    role: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    connectivity_state: str = ""
    current_capacity: int = 0
    max_capacity: int = 1


class RoutedTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str
    parent_conversation_id: str
    origin_agent_id: str
    target_agent_id: str
    title: str
    instructions: str
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_capabilities: list[str] = Field(default_factory=list)
    priority: str = "normal"
    created_at: str = Field(default_factory=utcnow_iso, min_length=1)

    @field_validator("created_at", mode="before")
    @classmethod
    def default_created_at(cls, value: Any) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)


class TimelineEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1)
    conversation_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str = ""
    status: str = ""
    progress: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(..., min_length=1)


class RoutedTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str
    status: str
    summary: str = ""
    timeline_events: list[TimelineEventPayload] = Field(default_factory=list)
    progress: int | None = None
    updated_at: str = Field(default_factory=utcnow_iso, min_length=1)

    @field_validator("updated_at", mode="before")
    @classmethod
    def default_updated_at(cls, value: Any) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)


class RoutedTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str
    status: str
    summary: str = ""
    full_text: str = ""
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    completed_at: str = Field(default_factory=utcnow_iso, min_length=1)

    @field_validator("completed_at", mode="before")
    @classmethod
    def default_completed_at(cls, value: Any) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)
