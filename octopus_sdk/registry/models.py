"""Registry wire models used by clients, servers, and bot runtimes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from typing import Any, Literal, NewType
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, field_validator

from octopus_sdk.realtime import ConversationProgressUpdate

AuthorityId = NewType("AuthorityId", str)
AgentId = NewType("AgentId", str)
ConversationId = NewType("ConversationId", str)
TransportConversationKey = NewType("TransportConversationKey", str)
TransportActorKey = NewType("TransportActorKey", str)
ExternalConversationRef = NewType("ExternalConversationRef", str)
DeliveryId = NewType("DeliveryId", str)
ConnectivityState = NewType("ConnectivityState", str)
RegistryJsonValue = JsonValue


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RegistryRecordModel(BaseModel):
    """Typed authority/client record with permissive parsing for current wire payloads."""

    model_config = ConfigDict(extra="forbid")

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RegistryRecordModel):
            return self.model_dump(mode="json") == other.model_dump(mode="json")
        if isinstance(other, Mapping):
            return self.model_dump(mode="json") == dict(other)
        return False


class RegistryJsonRecord(RootModel[dict[str, RegistryJsonValue]], Mapping[str, RegistryJsonValue]):
    root: dict[str, RegistryJsonValue] = Field(default_factory=dict)

    def __getitem__(self, key: str) -> RegistryJsonValue:
        return self.root[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def get(self, key: str, default: RegistryJsonValue = None) -> RegistryJsonValue:
        return self.root.get(key, default)

    def items(self):
        return self.root.items()

    def as_dict(self) -> dict[str, RegistryJsonValue]:
        return dict(self.root)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RegistryJsonRecord):
            return self.root == other.root
        if isinstance(other, Mapping):
            return self.root == dict(other)
        return False


class RuntimeHealthSummaryRecord(RegistryRecordModel):
    ok: bool | None = None
    status: str = ""
    healthy_worker_count: int = 0
    stale_worker_count: int = 0
    fresh_queued_count: int = 0
    claimed_count: int = 0
    pending_recovery_count: int = 0
    recovery_queued_count: int = 0
    oldest_claim_age_seconds: int | None = None
    warning_count: int = 0
    error_count: int = 0


class RuntimeHealthDiagnosticRecord(RegistryRecordModel):
    level: str = ""
    code: str = ""
    message: str = ""
    detail: str = ""


class RoutedTaskContextRecord(RegistryJsonRecord):
    pass


class RoutedTaskConstraintsRecord(RegistryJsonRecord):
    pass


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


class EnrollmentResult(RegistryRecordModel):
    agent_id: str = ""
    agent_token: str = ""
    slug: str = ""
    poll_cursor: str = "0"


class AgentRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_card: AgentCard
    connectivity_state: str = ""
    current_capacity: int = 0
    max_capacity: int = 1


class AgentHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connectivity_state: str = ""
    current_capacity: int = 0
    max_capacity: int = 1
    runtime_health: "RuntimeHealthPayload | None" = None


class AgentRecord(RegistryRecordModel):
    agent_id: str = ""
    bot_key: str = ""
    display_name: str = ""
    slug: str = ""
    role: str = ""
    registry_scope: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    provider: str = ""
    mode: str = ""
    connectivity_state: str = ""
    current_capacity: int = 0
    max_capacity: int = 1
    channel_capabilities: list[str] = Field(default_factory=list)
    version: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_heartbeat_at: str = ""
    runtime_health_summary: RuntimeHealthSummaryRecord = Field(default_factory=RuntimeHealthSummaryRecord)
    runtime_health_generated_at: str = ""


class CapabilityRecord(RegistryRecordModel):
    capability_name: str = ""
    declared_by_agents: list[str] = Field(default_factory=list)
    enabled: bool | None = None


class EventRecord(RegistryRecordModel):
    seq: int | None = None
    event_id: str = ""
    conversation_id: str = ""
    agent_id: str = ""
    kind: str = ""
    actor: str = ""
    content: str = ""
    metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_at: str = ""


class MessageRecord(RegistryRecordModel):
    conversation_id: str = ""
    accepted: bool = False
    event: EventRecord | None = None


class TaskRecord(RegistryRecordModel):
    routed_task_id: str = ""
    delivery_id: str = ""
    status: str = ""
    summary: str = ""
    title: str = ""
    instructions: str = ""
    parent_conversation_id: str = ""
    origin_agent_id: str = ""
    origin_display_name: str = ""
    target_agent_id: str = ""
    target_display_name: str = ""
    request: RegistryJsonRecord | None = None
    result: RegistryJsonRecord | None = None
    result_summary: str = ""
    result_text: str = ""
    duplicate: bool = False
    events_written: bool = False
    created_at: str = ""
    updated_at: str = ""
    inserted_events: list[EventRecord] = Field(default_factory=list)


class ConversationRecord(RegistryRecordModel):
    conversation_id: str = ""
    target_agent_id: str = ""
    title: str = ""
    origin_channel: str = ""
    external_conversation_ref: str = ""
    status: str = ""
    created_at: str = ""
    updated_at: str = ""
    target_display_name: str = ""
    target_name: str = ""
    event_count: int = 0
    linked_routed_tasks: list[TaskRecord] = Field(default_factory=list)


class DeliveryRecord(RegistryRecordModel):
    seq: int | None = None
    cursor: str = ""
    delivery_id: str = ""
    registry_id: str = ""
    kind: str = ""
    payload: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    state: str = ""
    created_at: str = ""


class DeliveryPollResult(RegistryRecordModel):
    deliveries: list[DeliveryRecord] = Field(default_factory=list)
    next_cursor: str = "0"


class AckResult(RegistryRecordModel):
    updated: int = 0
    classification: str = ""


class PublishEventsResult(RegistryRecordModel):
    inserted: int = 0
    skipped: int = 0
    inserted_ids: list[str] = Field(default_factory=list)
    inserted_events: list[EventRecord] = Field(default_factory=list)


class HealthSummary(RegistryRecordModel):
    agent: AgentRecord | None = None
    collections_changed: bool = False
    server_time: str = ""


class TargetResolutionPreview(RegistryRecordModel):
    status: str = ""
    error: str = ""
    authority_ref: str = ""
    target_label: str = ""


class RuntimeHealthPayload(RegistryRecordModel):
    summary: RuntimeHealthSummaryRecord = Field(default_factory=RuntimeHealthSummaryRecord)
    snapshot: RegistryJsonRecord | None = None
    diagnostics: list[RuntimeHealthDiagnosticRecord] = Field(default_factory=list)


class RuntimeWorkerRecord(RegistryRecordModel):
    worker_id: str = ""
    process_role: str = ""
    started_at: str = ""
    last_seen_at: str = ""
    current_item_id: str = ""
    current_conversation_key: str = ""
    current_kind: str = ""
    items_processed: int = 0
    stale_recoveries_seen: int = 0
    last_error: str = ""
    mirrored_at: str = ""


class RuntimeHealthDetailRecord(RegistryRecordModel):
    report: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    workers: list[RuntimeWorkerRecord] = Field(default_factory=list)
    last_mirrored_at: str = ""


class MirrorOutcome(RegistryRecordModel):
    authority_ref: str = ""
    status: str = ""
    conversation_id: str = ""
    event_ids: list[str] = Field(default_factory=list)
    retry_required: bool = False


class ConversationSearchHitRecord(RegistryRecordModel):
    conversation_id: str = ""
    snippet: str = ""


class UsageSummaryRecord(RegistryRecordModel):
    event_id: str = ""
    agent_id: str = ""
    conversation_id: str = ""
    title: str = ""
    metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_at: str = ""


class RegistrySummaryRecord(RegistryRecordModel):
    generated_at: str = ""
    agents: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    conversations: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    tasks: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    usage_24h: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ApprovalRecord(RegistryRecordModel):
    request_id: str = ""
    conversation_id: str = ""
    conversation_title: str = ""
    conversation_status: str = ""
    conversation_updated_at: str = ""
    target_agent_id: str = ""
    target_display_name: str = ""
    request_kind: str = ""
    actor_key: str = ""
    trust_tier: str = ""
    expires_at: str = ""
    actor: str = ""
    content: str = ""
    created_at: str = ""


class EventPageRecord(RegistryRecordModel):
    events: list[EventRecord] = Field(default_factory=list)
    has_more_before: bool = False
    next_before_seq: int | None = None
    next_after_seq: int | None = None


class MessagePageRecord(RegistryRecordModel):
    events: list[EventRecord] = Field(default_factory=list)
    next_cursor: int = 0


class AgentStatusRecord(AgentRecord):
    workers: list[RuntimeWorkerRecord] = Field(default_factory=list)
    active_conversations: int = 0
    recent_errors: int = 0


class RoutedTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str
    parent_conversation_id: str
    origin_agent_id: str
    target_agent_id: str
    title: str
    instructions: str
    context: RoutedTaskContextRecord = Field(default_factory=RoutedTaskContextRecord)
    constraints: RoutedTaskConstraintsRecord = Field(default_factory=RoutedTaskConstraintsRecord)
    requested_capabilities: list[str] = Field(default_factory=list)
    priority: str = "normal"
    created_at: str = Field(default_factory=utcnow_iso, min_length=1)

    @field_validator("created_at", mode="before")
    @classmethod
    def default_created_at(cls, value: Any) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)


class TargetSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent", "capability", "role"] = "agent"
    value: str = Field(..., min_length=1)
    preferred_agent_id: str = ""

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be blank")
        return text


def parse_target_selector(raw: str) -> TargetSelector | None:
    text = str(raw or "").strip()
    if not text.startswith("@"):
        return None
    body = text[1:].strip()
    if not body:
        return None
    if body.startswith("cap:"):
        value = body[4:].strip()
        return TargetSelector(kind="capability", value=value) if value else None
    if body.startswith("role:"):
        value = body[5:].strip()
        return TargetSelector(kind="role", value=value) if value else None
    return TargetSelector(kind="agent", value=body)


def extract_target_selector_message(raw: str) -> tuple[TargetSelector, str] | None:
    text = str(raw or "").strip()
    if not text.startswith("@"):
        return None
    parts = text.split(None, 1)
    selector_token = parts[0]
    selector = parse_target_selector(selector_token)
    if selector is None:
        return None
    instructions = parts[1].strip() if len(parts) > 1 else ""
    return (selector, instructions) if instructions else None


class DelegationTaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    selector: TargetSelector
    authority_ref: str = ""
    title: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=1)
    priority: str = "normal"
    requested_capabilities: list[str] = Field(default_factory=list)
    context: RoutedTaskContextRecord = Field(default_factory=RoutedTaskContextRecord)


class DelegationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    resume_instruction: str = ""
    tasks: list[DelegationTaskDraft] = Field(..., min_length=1)


class DirectAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: TargetSelector
    title: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=1)
    message_text: str = ""
    priority: str = "normal"
    requested_capabilities: list[str] = Field(default_factory=list)
    context: RoutedTaskContextRecord = Field(default_factory=RoutedTaskContextRecord)


class ApproveRejectActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1)


class RetryDecisionActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1)


class RecoveryActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    update_id: int = Field(..., gt=0)


class DirectAssignActionPayload(DirectAssignmentRequest):
    pass


class DelegateTasksActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    resume_instruction: str = ""
    tasks: list[DelegationTaskDraft] = Field(..., min_length=1)


class ApproveDelegationActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(..., min_length=1)


class CancelDelegationActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(..., min_length=1)


class CancelTaskActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str = Field(..., min_length=1)


class RetryTaskActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str = Field(..., min_length=1)


class CoordinationActionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., min_length=1)
    action: Literal[
        "approve",
        "reject",
        "cancel_conversation",
        "retry_allow",
        "retry_skip",
        "recovery_discard",
        "recovery_replay",
        "direct_assign",
        "delegate_tasks",
        "approve_delegation",
        "cancel_delegation",
        "cancel_task",
        "retry_task",
    ]
    payload: (
        ApproveRejectActionPayload
        | RetryDecisionActionPayload
        | RecoveryActionPayload
        | DirectAssignActionPayload
        | DelegateTasksActionPayload
        | ApproveDelegationActionPayload
        | CancelDelegationActionPayload
        | CancelTaskActionPayload
        | RetryTaskActionPayload
        | RegistryJsonRecord
        | None
    ) = None


class RoutedTaskRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str = Field(..., min_length=1)
    target_agent_id: str = ""
    authority_ref: str = ""
    title: str = ""
    status: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class CoordinationActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(..., min_length=1)
    action_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    accepted: bool = True
    duplicate: bool = False
    status: str = ""
    proposal_id: str = ""
    routed_tasks: list[RoutedTaskRef] = Field(default_factory=list)
    inserted_events: list[EventRecord] = Field(default_factory=list)
    event: EventRecord | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class TimelineEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1)
    conversation_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str = ""
    status: str = ""
    progress: int | None = None
    metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_at: str = Field(..., min_length=1)


class RoutedTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str
    status: str
    transition_id: str = Field(..., min_length=1)
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
    transition_id: str = Field(..., min_length=1)
    summary: str = ""
    full_text: str = ""
    artifacts: list[RegistryJsonRecord] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    provider: str = ""
    completed_at: str = Field(default_factory=utcnow_iso, min_length=1)

    @field_validator("completed_at", mode="before")
    @classmethod
    def default_completed_at(cls, value: Any) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)
