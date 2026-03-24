"""Conversation event types — the core observability contract.

ConversationEvent is the single event model published by bots to the registry.
event_id is REQUIRED (no default) — publishers must provide a stable ID that
survives retries. The store uses ON CONFLICT DO NOTHING for idempotent inserts.

Each event kind has a typed metadata schema. Unknown kinds are rejected at the
HTTP boundary. The metadata schemas are the machine-checkable contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationEvent(BaseModel):
    """Single event published to a registry conversation."""

    model_config = ConfigDict(extra="forbid")

    event_id: str                    # REQUIRED — publisher-generated, stable across retries
    kind: str                        # "message.user", "provider.response", etc.
    actor: str = ""                  # display name, not transport-specific ID
    content: str = ""                # text/markdown body
    created_at: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Typed metadata schemas per event kind
# ---------------------------------------------------------------------------

class MessageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachments: list[str] = Field(default_factory=list)


class ProviderResponseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    cost_usd: float = Field(..., ge=0.0)
    provider: str = Field(..., min_length=1)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class ApprovalMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., min_length=1)
    decided_by: str = Field(..., min_length=1)
    decision: Literal["approved", "rejected"]


class DelegationTaskSummary(BaseModel):
    """One task in a delegation plan."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)  # target agent slug or agent_id
    status: str = Field(..., min_length=1)  # proposed, submitted, completed, failed


class DelegationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[DelegationTaskSummary] = Field(..., min_length=1)


class TaskStatusMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., min_length=1)
    progress: int | None = None


class ErrorMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_type: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


EVENT_METADATA_SCHEMAS: dict[str, type[BaseModel]] = {
    "message.user": MessageMetadata,
    "message.bot": MessageMetadata,
    "provider.response": ProviderResponseMetadata,
    "approval.decided": ApprovalMetadata,
    "delegation.proposed": DelegationMetadata,
    "delegation.submitted": DelegationMetadata,
    "delegation.completed": DelegationMetadata,
    "task.status": TaskStatusMetadata,
    "error": ErrorMetadata,
}


def validate_event_metadata(event: ConversationEvent) -> dict[str, Any]:
    """Validate that event.metadata matches the schema for event.kind.

    Returns the normalized metadata payload.
    Raises ValueError for unknown kinds or invalid metadata.
    """
    schema = EVENT_METADATA_SCHEMAS.get(event.kind)
    if schema is None:
        raise ValueError(f"Unknown event kind: {event.kind!r}")
    return schema.model_validate(event.metadata).model_dump(
        exclude_defaults=True,
        exclude_none=True,
    )
