"""Conversation event types — the core observability contract.

ConversationEvent is the single event model published by bots to the registry.
event_id is REQUIRED (no default) — publishers must provide a stable ID that
survives retries. The store uses ON CONFLICT DO NOTHING for idempotent inserts.

Each event kind has a typed metadata schema. Unknown kinds are rejected at the
HTTP boundary. The metadata schemas are the machine-checkable contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ConversationEvent(BaseModel):
    """Single event published to a registry conversation."""

    model_config = ConfigDict(extra="forbid")

    event_id: str                    # REQUIRED — publisher-generated, stable across retries
    kind: str                        # "message.user", "provider.response", etc.
    actor: str = ""                  # display name, not transport-specific ID
    content: str = ""                # text/markdown body
    created_at: str = Field(..., min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


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
    cached_prompt_tokens: int | None = Field(default=None, ge=0)
    cached_completion_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float = Field(..., ge=0.0)
    provider: str = Field(..., min_length=1)


class ProviderRequestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    execution_mode: Literal["run", "resume", "preflight", "retry"]
    working_dir: str = Field(..., min_length=1)
    file_policy: str = Field(..., min_length=1)
    image_count: int = Field(..., ge=0)
    prompt_char_count: int = Field(..., ge=0)


class FileChangeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    change_type: Literal["created", "modified", "deleted", "renamed"]
    summary: str = Field(..., min_length=1)


class ToolExecutionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(..., min_length=1)
    call_id: str = Field(..., min_length=1)
    status: Literal["completed", "failed", "denied"]
    input_summary: str = Field(..., min_length=1)
    output_summary: str = Field(..., min_length=1)
    duration_ms: int | None = Field(default=None, ge=0)
    file_changes: list[FileChangeSummary] = Field(default_factory=list)


class ApprovalMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., min_length=1)
    decided_by: str = Field(..., min_length=1)
    decision: Literal["approved", "rejected"]


class ApprovalRequestedMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_kind: Literal["preflight", "retry", "delegation", "recovery"]
    actor_key: str = Field(..., min_length=1)
    trust_tier: str = Field(..., min_length=1)
    expires_at: str | None = None
    recovery_id: str | None = None


class DelegationTaskSummary(BaseModel):
    """One task in a delegation plan."""

    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)  # target agent slug or agent_id
    status: str = Field(..., min_length=1)  # proposed, submitted, completed, failed
    routed_task_id: str = ""
    selector_kind: str = ""
    selector_value: str = ""
    instructions: str = ""
    priority: str = ""
    requested_capabilities: list[str] = Field(default_factory=list)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class DelegationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(..., min_length=1)
    tasks: list[DelegationTaskSummary] = Field(..., min_length=1)


class TaskStatusMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    progress: int | None = None
    transition_id: str = ""
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cached_prompt_tokens: int | None = Field(default=None, ge=0)
    cached_completion_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    provider: str | None = None


class ErrorMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_type: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


EVENT_METADATA_SCHEMAS: dict[str, type[BaseModel]] = {
    "message.user": MessageMetadata,
    "message.bot": MessageMetadata,
    "provider.request": ProviderRequestMetadata,
    "provider.response": ProviderResponseMetadata,
    "tool.execution": ToolExecutionMetadata,
    "approval.requested": ApprovalRequestedMetadata,
    "approval.decided": ApprovalMetadata,
    "delegation.proposed": DelegationMetadata,
    "delegation.submitted": DelegationMetadata,
    "delegation.completed": DelegationMetadata,
    "task.status": TaskStatusMetadata,
    "error": ErrorMetadata,
}


def validate_event_metadata(event: ConversationEvent) -> dict[str, JsonValue]:
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
