"""Registry wire models used by clients, servers, and bot runtimes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import re
from typing import Literal, NewType
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, field_validator, model_validator

from octopus_sdk.realtime import ConversationProgressUpdate
from octopus_sdk.time_utils import utc_now_iso as utcnow_iso

AuthorityId = NewType("AuthorityId", str)
AgentId = NewType("AgentId", str)
ConversationId = NewType("ConversationId", str)
TransportConversationKey = NewType("TransportConversationKey", str)
TransportActorKey = NewType("TransportActorKey", str)
ExternalConversationRef = NewType("ExternalConversationRef", str)
DeliveryId = NewType("DeliveryId", str)
ConnectivityState = NewType("ConnectivityState", str)
RegistryJsonValue = JsonValue
_DIRECT_SKILL_MESSAGE_RE = re.compile(
    r"^(?:using|use)\s+([a-z0-9][a-z0-9_-]*)\s+skill\s*[,:-]\s*(.+)$",
    re.IGNORECASE,
)


class RegistryRecordModel(BaseModel):
    """Typed authority/client record with permissive parsing for current wire payloads."""

    model_config = ConfigDict(extra="forbid")

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> object:
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
    execution_state: str = "healthy"
    execution_provider: str = ""
    execution_fault_kind: str = ""
    execution_fault_code: str = ""
    execution_fault_detail: str = ""
    execution_faulted_at: str = ""
    execution_resettable: bool = False
    execution_last_returncode: int | None = None
    healthy_worker_count: int = 0
    stale_worker_count: int = 0
    fresh_queued_count: int = 0
    claimed_count: int = 0
    pending_recovery_count: int = 0
    recovery_queued_count: int = 0
    oldest_claim_age_seconds: int | None = None
    warning_count: int = 0
    error_count: int = 0


class ExecutionStateRecord(RegistryRecordModel):
    state: str = "healthy"
    provider: str = ""
    fault_kind: str = ""
    fault_code: str = ""
    detail: str = ""
    faulted_at: str = ""
    resettable: bool = False
    last_returncode: int | None = None


class RuntimeHealthDiagnosticRecord(RegistryRecordModel):
    level: str = ""
    code: str = ""
    message: str = ""
    detail: str = ""


class RoutedTaskContextRecord(RegistryJsonRecord):
    pass


class RoutedTaskConstraintsRecord(RegistryJsonRecord):
    pass


class AgentCard(RegistryRecordModel):
    """Agent identity and routing-skill declaration sent during enrollment/registration."""

    model_config = ConfigDict(extra="forbid")

    bot_key: str = ""
    display_name: str = ""
    slug: str = ""
    role: str = ""
    registry_scope: str = "full"
    routing_skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    provider: str = ""
    mode: str = "standalone"
    connectivity_state: str = "standalone"
    current_capacity: int = 0
    max_capacity: int = 1
    transport_implementations: list[str] = Field(default_factory=list)
    supported_admin_operations: list[str] = Field(default_factory=list)
    version: str = "dev"


class ConversationCreate(RegistryRecordModel):
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


class AgentDiscoveryQuery(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    role: str = ""
    skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    free_text: str = ""
    exclude_agent_ids: list[str] = Field(default_factory=list)
    required_state: str = "connected"


_DISCOVERY_ALLOWED_STATES = frozenset({"connected", "degraded", "standalone", "disconnected"})


def parse_agent_discovery_query(
    raw: tuple[str, ...] | list[str],
    *,
    exclude_agent_id: str = "",
) -> AgentDiscoveryQuery | None:
    role = ""
    skills: list[str] = []
    tags: list[str] = []
    required_state = "connected"
    free_text_parts: list[str] = []
    for token in raw:
        piece = str(token or "").strip()
        if not piece:
            continue
        key = ""
        value = ""
        if ":" in piece:
            key, value = piece.split(":", 1)
        elif "=" in piece:
            key, value = piece.split("=", 1)
        else:
            free_text_parts.append(piece)
            continue
        key = key.strip().lower()
        value = value.strip()
        if not value:
            free_text_parts.append(piece)
            continue
        if key == "role":
            role = value
        elif key in {"skill", "skills"}:
            skills.extend(part.strip() for part in value.split(",") if part.strip())
        elif key in {"tag", "tags"}:
            tags.extend(part.strip() for part in value.split(",") if part.strip())
        elif key == "state":
            required_state = value.lower()
        else:
            free_text_parts.append(piece)
    if required_state not in _DISCOVERY_ALLOWED_STATES:
        return None
    if not role and not skills and not tags and not free_text_parts:
        return None
    return AgentDiscoveryQuery(
        role=role,
        skills=skills,
        tags=tags,
        free_text=" ".join(free_text_parts).strip(),
        exclude_agent_ids=[exclude_agent_id] if exclude_agent_id else [],
        required_state=required_state,
    )


def format_target_selector(kind: Literal["agent", "skill", "role"], value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if kind == "agent":
        return normalized if normalized.startswith("@") else f"@{normalized}"
    if kind == "skill":
        return f"@skill:{normalized}"
    if kind == "role":
        return f"@role:{normalized}"
    raise ValueError(f"Unsupported target selector kind: {kind!r}")


class DiscoveredAgentRef(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    authority_ref: str
    agent_id: str
    display_name: str = ""
    slug: str = ""
    role: str = ""
    routing_skills: list[str] = Field(default_factory=list)
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
    registry_epoch: str = ""


class AgentRegisterRequest(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    agent_card: AgentCard
    connectivity_state: str = ""
    current_capacity: int | None = None
    max_capacity: int | None = None


class AgentHeartbeatRequest(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    connectivity_state: str = ""
    current_capacity: int | None = None
    max_capacity: int | None = None
    runtime_health: "RuntimeHealthPayload | None" = None


class AgentTrustTierUpdate(RegistryRecordModel):
    """Request body for PATCH /v1/agents/{agent_id}/trust-tier."""

    model_config = ConfigDict(extra="forbid")

    trust_tier: str

    @field_validator("trust_tier")
    @classmethod
    def _tier_allowed(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"community", "trusted", "verified", "restricted"}:
            raise ValueError(
                "trust_tier must be one of community|trusted|verified|restricted"
            )
        return normalized


class AgentCapacityUpdate(RegistryRecordModel):
    """Request body for PATCH /v1/agents/{agent_id}/capacity."""

    model_config = ConfigDict(extra="forbid")

    current_capacity: int | None = None
    max_capacity: int | None = None


class AgentTokenRotationResult(RegistryRecordModel):
    """Response payload for POST /v1/agents/{agent_id}/rotate-token."""

    agent_id: str = ""
    agent_token: str = ""
    slug: str = ""
    registry_epoch: str = ""


class SelectorPreviewRequest(RegistryRecordModel):
    """Request body for POST /v1/selector/preview."""

    model_config = ConfigDict(extra="forbid")

    selector: str
    authority_ref: str = ""
    exclude_agent_ids: list[str] = Field(default_factory=list)

    @field_validator("selector")
    @classmethod
    def _selector_not_blank(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("selector must not be blank")
        return str(value).strip()


class SelectorPreviewCandidate(RegistryRecordModel):
    """A single agent resolved for a selector preview."""

    agent_id: str = ""
    display_name: str = ""
    slug: str = ""
    role: str = ""
    connectivity_state: str = ""
    trust_tier: str = "community"
    current_capacity: int = 0
    max_capacity: int = 1
    routing_skills: list[str] = Field(default_factory=list)
    reason: str = ""


class SelectorPreviewResult(RegistryRecordModel):
    """Response payload for POST /v1/selector/preview."""

    selector: str = ""
    authority_ref: str = ""
    candidates: list[SelectorPreviewCandidate] = Field(default_factory=list)
    total_considered: int = 0
    rejected_reasons: list[str] = Field(default_factory=list)


class AgentRecord(RegistryRecordModel):
    agent_id: str = ""
    bot_key: str = ""
    display_name: str = ""
    slug: str = ""
    role: str = ""
    registry_scope: str = ""
    routing_skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    provider: str = ""
    mode: str = ""
    connectivity_state: str = ""
    current_capacity: int = 0
    max_capacity: int = 1
    transport_implementations: list[str] = Field(default_factory=list)
    supported_admin_operations: list[str] = Field(default_factory=list)
    version: str = ""
    trust_tier: str = "community"
    soft_deleted_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_heartbeat_at: str = ""
    execution_state: str = "healthy"
    execution_provider: str = ""
    execution_fault_kind: str = ""
    execution_fault_code: str = ""
    execution_fault_detail: str = ""
    execution_faulted_at: str = ""
    execution_resettable: bool = False
    execution_last_returncode: int | None = None
    runtime_health_summary: RuntimeHealthSummaryRecord = Field(default_factory=RuntimeHealthSummaryRecord)
    runtime_health_generated_at: str = ""


class RoutingSkillRecord(RegistryRecordModel):
    skill_name: str = ""
    advertised_by_agents: list[str] = Field(default_factory=list)
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
    source_kind: str = "delegation"
    hidden_from_default_views: bool = False
    status: str = ""
    summary: str = ""
    title: str = ""
    instructions: str = ""
    parent_conversation_id: str = ""
    parent_conversation_title: str = ""
    recipient_conversation_id: str = ""
    origin_transport_ref: str = ""
    origin_agent_id: str = ""
    origin_display_name: str = ""
    target_agent_id: str = ""
    target_display_name: str = ""
    protocol_run_id: str = ""
    protocol_stage_execution_id: str = ""
    protocol_definition_version_id: str = ""
    participant_key: str = ""
    stage_key: str = ""
    project_id_override: str = ""
    file_policy_override: str = ""
    working_dir: str = ""
    artifact_count: int = 0
    request: RegistryJsonRecord | None = None
    result: RegistryJsonRecord | None = None
    result_summary: str = ""
    result_text: str = ""
    duplicate: bool = False
    events_written: bool = False
    created_at: str = ""
    updated_at: str = ""
    inserted_events: list[EventRecord] = Field(default_factory=list)
    recipient_inserted_events: list[EventRecord] = Field(default_factory=list)


class ConversationRecord(RegistryRecordModel):
    conversation_id: str = ""
    target_agent_id: str = ""
    source_kind: str = "human"
    hidden_from_default_views: bool = False
    title: str = ""
    conversation_type: str = "conversation"
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
    registry_epoch: str = ""


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
    schema_version: int = 1
    generated_at: str = Field(default_factory=utcnow_iso, min_length=1)
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
    protocols: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
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
    recovery_id: str = ""
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
    runtime_health_detail: RuntimeHealthDetailRecord | None = None


class RoutedTaskRequest(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str
    parent_conversation_id: str
    origin_transport_ref: str = ""
    authorized_actor_key: str = ""
    external_conversation_ref: str = ""
    origin_agent_id: str
    target_agent_id: str
    title: str
    instructions: str
    context: RoutedTaskContextRecord = Field(default_factory=RoutedTaskContextRecord)
    internal_context: RoutedTaskContextRecord = Field(default_factory=RoutedTaskContextRecord)
    constraints: RoutedTaskConstraintsRecord = Field(default_factory=RoutedTaskConstraintsRecord)
    requested_skills: list[str] = Field(default_factory=list)
    session_key_override: str = ""
    project_id_override: str = ""
    file_policy_override: str = ""
    priority: str = "normal"
    created_at: str = Field(default_factory=utcnow_iso, min_length=1)

    @field_validator("created_at", mode="before")
    @classmethod
    def default_created_at(cls, value: object) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)

    @field_validator(
        "routed_task_id",
        "parent_conversation_id",
        "origin_agent_id",
        "target_agent_id",
        "title",
        "instructions",
        mode="before",
    )
    @classmethod
    def require_non_blank_fields(cls, value: object, info) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be blank")
        return text

    @model_validator(mode="after")
    def default_external_conversation_ref(self) -> "RoutedTaskRequest":
        external_ref = str(self.external_conversation_ref or "").strip()
        if not external_ref:
            external_ref = f"routed-task:{self.routed_task_id}"
        object.__setattr__(self, "external_conversation_ref", external_ref)
        return self


class TargetSelector(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent", "skill", "role"] = "agent"
    value: str = Field(..., min_length=1)
    preferred_agent_id: str = ""

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, value: object) -> str:
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
    if body.startswith("skill:"):
        value = body[6:].strip()
        return TargetSelector(kind="skill", value=value) if value else None
    if body.startswith("role:"):
        value = body[5:].strip()
        return TargetSelector(kind="role", value=value) if value else None
    return TargetSelector(kind="agent", value=body)


def normalized_requested_skills(
    requested_skills: list[str] | tuple[str, ...] | None = None,
    *,
    selector: TargetSelector | None = None,
) -> list[str]:
    names: list[str] = []
    if requested_skills:
        names.extend(str(item or "").strip() for item in requested_skills)
    if selector is not None and selector.kind == "skill":
        names.append(str(selector.value or "").strip())
    seen: set[str] = set()
    normalized: list[str] = []
    for name in names:
        if not name:
            continue
        slug = name.lower()
        if slug in seen:
            continue
        seen.add(slug)
        normalized.append(slug)
    return normalized


def extract_leading_requested_skills(raw: str) -> tuple[tuple[str, ...], str]:
    text = str(raw or "").strip()
    match = _DIRECT_SKILL_MESSAGE_RE.match(text)
    if not match:
        return (), text
    skill_name = str(match.group(1) or "").strip().lower()
    instructions = str(match.group(2) or "").strip()
    if not skill_name or not instructions:
        return (), text
    return (skill_name,), instructions


def extract_target_selector_message(raw: str) -> tuple[TargetSelector, str] | None:
    text = str(raw or "").strip()
    if text.startswith("@"):
        parts = text.split(None, 1)
        selector_token = parts[0]
        selector = parse_target_selector(selector_token)
        if selector is None:
            return None
        instructions = parts[1].strip() if len(parts) > 1 else ""
        return (selector, instructions) if instructions else None
    requested_skills, instructions = extract_leading_requested_skills(text)
    if not requested_skills:
        return None
    selector = TargetSelector(kind="skill", value=requested_skills[0])
    return (selector, instructions) if instructions else None


class DelegationTaskDraft(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    selector: TargetSelector
    authority_ref: str = ""
    title: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=1)
    priority: str = "normal"
    requested_skills: list[str] = Field(default_factory=list)
    context: RoutedTaskContextRecord = Field(default_factory=RoutedTaskContextRecord)


class DelegationIntent(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    resume_instruction: str = ""
    origin_transport_ref: str = ""
    authorized_actor_key: str = ""
    tasks: list[DelegationTaskDraft] = Field(..., min_length=1)


class DirectAssignmentRequest(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    selector: TargetSelector
    title: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=1)
    parent_event_id: str = ""
    origin_transport_ref: str = ""
    authorized_actor_key: str = ""
    message_text: str = ""
    priority: str = "normal"
    requested_skills: list[str] = Field(default_factory=list)
    context: RoutedTaskContextRecord = Field(default_factory=RoutedTaskContextRecord)


class ApproveRejectActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1)


class RetryDecisionActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1)


class RecoveryActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    recovery_id: str = Field(..., min_length=1)


class DirectAssignActionPayload(DirectAssignmentRequest):
    pass


class DelegateTasksActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    resume_instruction: str = ""
    origin_transport_ref: str = ""
    authorized_actor_key: str = ""
    tasks: list[DelegationTaskDraft] = Field(..., min_length=1)


class ApproveDelegationActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(..., min_length=1)


class CancelDelegationActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(..., min_length=1)


class CancelTaskActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str = Field(..., min_length=1)


class RetryTaskActionPayload(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str = Field(..., min_length=1)


class CoordinationActionEnvelope(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., min_length=1)
    action: Literal[
        "approve_pending",
        "reject_pending",
        "cancel_conversation",
        "retry_allow",
        "retry_skip",
        "recovery_discard",
        "recovery_replay",
        "direct_assign",
        "delegate_tasks",
        "delegation_approve",
        "delegation_cancel",
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

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> object:
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

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


class TimelineEventPayload(RegistryRecordModel):
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


class RoutedTaskUpdate(RegistryRecordModel):
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
    def default_updated_at(cls, value: object) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)

    @field_validator("routed_task_id", "status", mode="before")
    @classmethod
    def require_non_blank_update_fields(cls, value: object, info) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be blank")
        return text


class RoutedTaskResult(RegistryRecordModel):
    model_config = ConfigDict(extra="forbid")

    routed_task_id: str
    status: str
    transition_id: str = Field(..., min_length=1)
    summary: str = ""
    full_text: str = ""
    artifacts: list[RegistryJsonRecord] = Field(default_factory=list)
    artifact_contents: list[RegistryJsonRecord] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cached_prompt_tokens: int | None = Field(default=None, ge=0)
    cached_completion_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    provider: str = ""
    working_dir: str = ""
    completed_at: str = Field(default_factory=utcnow_iso, min_length=1)

    @field_validator("completed_at", mode="before")
    @classmethod
    def default_completed_at(cls, value: object) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)

    @field_validator("routed_task_id", "status", mode="before")
    @classmethod
    def require_non_blank_result_fields(cls, value: object, info) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be blank")
        return text
