"""Routed task types for the registry SDK."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RoutedTaskRequest(BaseModel):
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
    created_at: str = Field(default_factory=_utcnow_iso)


class RoutedTaskUpdate(BaseModel):
    routed_task_id: str
    status: str
    summary: str = ""
    progress: int | None = None
    updated_at: str = Field(default_factory=_utcnow_iso)


class RoutedTaskResult(BaseModel):
    routed_task_id: str
    status: str
    summary: str = ""
    full_text: str = ""
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    completed_at: str = Field(default_factory=_utcnow_iso)
