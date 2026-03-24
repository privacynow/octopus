"""Routed task types for the registry SDK."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: str = Field(..., min_length=1)


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

    status: str
    summary: str = ""
    timeline_events: list[TimelineEventPayload] = Field(default_factory=list)
    progress: int | None = None
    updated_at: str = Field(..., min_length=1)


class RoutedTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    summary: str = ""
    full_text: str = ""
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    completed_at: str = Field(..., min_length=1)
