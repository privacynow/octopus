"""Task-routing control-plane payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TimelineEventPayload(BaseModel):
    event_id: str = Field(..., min_length=1)
    conversation_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str = ""
    status: str = ""
    progress: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(..., min_length=1)


class SubmitRoutedTaskPayload(BaseModel):
    routed_task_id: str = Field(..., min_length=1)
    parent_conversation_id: str = Field(..., min_length=1)
    origin_agent_id: str = Field(..., min_length=1)
    target_agent_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_capabilities: list[str] = Field(default_factory=list)
    priority: str = "normal"
    created_at: str = Field(..., min_length=1)


class UpdateRoutedTaskStatusPayload(BaseModel):
    routed_task_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    transition_id: str = Field(..., min_length=1)
    summary: str = ""
    timeline_events: list[TimelineEventPayload] = Field(default_factory=list)
    progress: int | None = None
    updated_at: str = Field(..., min_length=1)


class ReportTaskResultPayload(BaseModel):
    routed_task_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    transition_id: str = Field(..., min_length=1)
    summary: str = ""
    full_text: str = ""
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    completed_at: str = Field(..., min_length=1)
