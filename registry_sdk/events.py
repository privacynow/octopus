"""Conversation event types — the core observability contract.

ConversationEvent is the single event model published by bots to the registry.
event_id is REQUIRED (no default) — publishers must provide a stable ID that
survives retries. The store uses ON CONFLICT DO NOTHING for idempotent inserts.

Each event kind has a typed metadata schema. Unknown kinds are rejected at the
HTTP boundary. The metadata schemas are the machine-checkable contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationEvent(BaseModel):
    """Single event published to a registry conversation."""
    event_id: str                    # REQUIRED — publisher-generated, stable across retries
    kind: str                        # "message.user", "provider.response", etc.
    actor: str = ""                  # display name, not transport-specific ID
    content: str = ""                # text/markdown body
    created_at: str = Field(default_factory=_utcnow_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Typed metadata schemas per event kind
# ---------------------------------------------------------------------------

class MessageMetadata(BaseModel):
    attachments: list[str] = Field(default_factory=list)


class ProviderResponseMetadata(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class ToolExecutionMetadata(BaseModel):
    tool_name: str = ""
    input_summary: str = ""
    output_summary: str = ""
    duration_ms: int = 0


class FileChangeMetadata(BaseModel):
    path: str = ""
    diff_summary: str = ""


class ApprovalMetadata(BaseModel):
    action: str = ""         # what's being approved
    decided_by: str = ""     # who decided (for approval.decided)
    decision: str = ""       # "approved" | "rejected" (for approval.decided)


class DelegationMetadata(BaseModel):
    task_count: int = 0
    target_agents: list[str] = Field(default_factory=list)


class TaskStatusMetadata(BaseModel):
    status: str = ""
    progress: int | None = None


class ErrorMetadata(BaseModel):
    error_type: str = ""
    message: str = ""


EVENT_METADATA_SCHEMAS: dict[str, type[BaseModel]] = {
    "message.user": MessageMetadata,
    "message.bot": MessageMetadata,
    "provider.request": MessageMetadata,  # content field carries the prompt; no extra metadata needed
    "provider.response": ProviderResponseMetadata,
    "tool.execution": ToolExecutionMetadata,
    "file.change": FileChangeMetadata,
    "approval.requested": ApprovalMetadata,
    "approval.decided": ApprovalMetadata,
    "delegation.proposed": DelegationMetadata,
    "delegation.submitted": DelegationMetadata,
    "task.status": TaskStatusMetadata,
    "error": ErrorMetadata,
}


def validate_event_metadata(event: ConversationEvent) -> None:
    """Validate that event.metadata matches the schema for event.kind.

    Raises ValueError for unknown kinds or invalid metadata.
    """
    schema = EVENT_METADATA_SCHEMAS.get(event.kind)
    if schema is None:
        raise ValueError(f"Unknown event kind: {event.kind!r}")
    schema.model_validate(event.metadata)
