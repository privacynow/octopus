"""Abstract registry store contract and shared pure helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol, TypeVar

from octopus_sdk.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
    SkillRevisionRecord,
)
from octopus_sdk.registry.management import ManagementRequest, ManagementResult

from .runtime_health import report_from_dict, report_to_dict
from octopus_sdk.registry.models import (
    AckResult,
    AgentCard,
    AgentDiscoveryQuery,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    AgentRecord,
    AgentStatusRecord,
    ApprovalRecord,
    ApproveDelegationActionPayload,
    ApproveRejectActionPayload,
    CancelDelegationActionPayload,
    CancelTaskActionPayload,
    CapabilityRecord,
    ConversationRecord,
    ConversationSearchHitRecord,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    DeliveryPollResult,
    DeliveryRecord,
    DelegateTasksActionPayload,
    DirectAssignActionPayload,
    EnrollmentResult,
    EventRecord,
    EventPageRecord,
    HealthSummary,
    MessageRecord,
    MessagePageRecord,
    PublishEventsResult,
    RegistryRecordModel,
    RegistryJsonRecord,
    RegistrySummaryRecord,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    RuntimeHealthPayload,
    RuntimeHealthSummaryRecord,
    RuntimeWorkerRecord,
    TimelineEventPayload,
    RecoveryActionPayload,
    RetryDecisionActionPayload,
    RetryTaskActionPayload,
    RuntimeHealthDetailRecord,
    TaskRecord,
    UsageSummaryRecord,
)

_OFFLINE_AFTER_SECONDS = 60
_MISSING = object()
PROTECTED_ROUTED_TASK_STATUSES = (
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)
VALID_ACK_CLASSIFICATIONS = ("accepted", "rejected", "retry_later")
VALID_REGISTRY_SCOPES = ("full", "channel", "coordination")


def hash_agent_token(token: str) -> str:
    """Return the stable server-side digest used for agent bearer-token lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def stable_routed_task_id(conversation_id: str, action_id: str, index: int) -> str:
    raw = f"{conversation_id}:{action_id}:{index}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def routed_task_external_conversation_ref(routed_task_id: str) -> str:
    return f"routed-task:{str(routed_task_id or '').strip()}"


def direct_assignment_message_text(payload: DirectAssignActionPayload) -> str:
    raw = str(payload.message_text or "").strip()
    if raw:
        return raw
    if payload.selector.kind == "agent":
        selector = f"@{payload.selector.value}"
    elif payload.selector.kind == "capability":
        selector = f"@cap:{payload.selector.value}"
    else:
        selector = f"@role:{payload.selector.value}"
    return f"{selector} {payload.instructions}".strip()


class CapabilityDisabledError(RuntimeError):
    """Raised when routing requests a capability that has been globally disabled."""


class RegistryScopeError(PermissionError):
    """Raised when an agent registry scope cannot access a protected action."""

    def __init__(self, scope: str, required_scopes: set[str]) -> None:
        self.scope = scope or "full"
        self.required_scopes = tuple(sorted(required_scopes))
        super().__init__(
            f"Agent registry_scope '{self.scope}' cannot access this endpoint. "
            f"Required: {', '.join(self.required_scopes)}"
        )


def utcnow_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


_DefaultT = TypeVar("_DefaultT")


def ensure_json(value: object) -> str:
    """Serialize dataclasses and JSON-encodable values to a JSON string."""
    if is_dataclass(value):
        value = asdict(value)
    elif isinstance(value, RegistryJsonRecord):
        value = value.as_dict()
    elif isinstance(value, RegistryRecordModel):
        value = value.model_dump(mode="json")
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value)


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise ValueError(f"{field_name} requires non-empty text")
    return text.strip()


def validated_registry_scope(value: object) -> str:
    scope = str(value or "").strip().lower()
    if not scope:
        raise ValueError("registry_scope requires non-empty text")
    if scope not in VALID_REGISTRY_SCOPES:
        raise ValueError(
            f"registry_scope must be one of: {', '.join(VALID_REGISTRY_SCOPES)}"
        )
    return scope


def validated_agent_card_payload(
    value: object,
    *,
    require_registry_scope: bool,
) -> AgentCard:
    if require_registry_scope and isinstance(value, Mapping) and "registry_scope" not in value:
        raise ValueError("registry_scope is required")
    del require_registry_scope
    try:
        card = AgentCard.model_validate(value)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return card.model_copy(
        update={"registry_scope": validated_registry_scope(card.registry_scope)}
    )


def validated_register_payload(payload: object) -> AgentRegisterRequest:
    try:
        request = AgentRegisterRequest.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return request.model_copy(
        update={
            "agent_card": validated_agent_card_payload(
                request.agent_card.model_dump(mode="json"),
                require_registry_scope=False,
            )
        }
    )


def validated_heartbeat_payload(payload: object) -> AgentHeartbeatRequest:
    try:
        return AgentHeartbeatRequest.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
def validated_timeline_events(
    value: object,
    *,
    field_name: str = "events",
) -> list[TimelineEventPayload]:
    if isinstance(value, str) or not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    events: list[TimelineEventPayload] = []
    for index, raw_event in enumerate(value):
        try:
            events.append(TimelineEventPayload.model_validate(raw_event))
        except Exception as exc:
            raise ValueError(f"{field_name}[{index}] {exc}") from exc
    return events


def validated_search_query(query: object) -> AgentDiscoveryQuery:
    try:
        return AgentDiscoveryQuery.model_validate(query)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
def validated_routed_task_request(request: object) -> RoutedTaskRequest:
    try:
        return RoutedTaskRequest.model_validate(request)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
def validated_ack_request(*, delivery_ids: object, classification: object) -> tuple[list[str], str]:
    if isinstance(delivery_ids, str) or not isinstance(delivery_ids, list):
        raise ValueError("delivery_ids must be a list")
    ids = [_required_text(item, "delivery_ids[]") for item in delivery_ids]
    normalized_classification = _required_text(classification, "classification").lower()
    if normalized_classification not in VALID_ACK_CLASSIFICATIONS:
        raise ValueError(
            f"classification must be one of: {', '.join(VALID_ACK_CLASSIFICATIONS)}"
        )
    return ids, normalized_classification


def validated_routed_task_status_payload(payload: object) -> RoutedTaskUpdate:
    try:
        return RoutedTaskUpdate.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
def validated_routed_task_result_payload(payload: object) -> RoutedTaskResult:
    try:
        return RoutedTaskResult.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def validated_management_request(payload: object) -> ManagementRequest:
    try:
        return ManagementRequest.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def validated_management_result(payload: object) -> ManagementResult:
    try:
        return ManagementResult.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def validated_conversation_message_text(text: object) -> str:
    value = str(text or "")
    if not value.strip():
        raise ValueError("message text requires non-empty text")
    return value


def validated_conversation_action(payload: object) -> CoordinationActionEnvelope:
    try:
        envelope = CoordinationActionEnvelope.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return envelope


def validated_action_payload(
    envelope: CoordinationActionEnvelope,
) -> (
    ApproveRejectActionPayload
    | RetryDecisionActionPayload
    | RecoveryActionPayload
    | DirectAssignActionPayload
    | DelegateTasksActionPayload
    | ApproveDelegationActionPayload
    | CancelDelegationActionPayload
    | CancelTaskActionPayload
    | RetryTaskActionPayload
    | None
):
    raw_payload = envelope.payload
    if raw_payload is None:
        payload: object = {}
    elif hasattr(raw_payload, "model_dump"):
        payload = raw_payload.model_dump(mode="json")
    elif isinstance(raw_payload, RegistryJsonRecord):
        payload = raw_payload.as_dict()
    else:
        payload = raw_payload
    if envelope.action in {"approve", "reject"}:
        return ApproveRejectActionPayload.model_validate(payload)
    if envelope.action in {"retry_allow", "retry_skip"}:
        return RetryDecisionActionPayload.model_validate(payload)
    if envelope.action in {"recovery_discard", "recovery_replay"}:
        return RecoveryActionPayload.model_validate(payload)
    if envelope.action == "direct_assign":
        return DirectAssignActionPayload.model_validate(payload)
    if envelope.action == "delegate_tasks":
        return DelegateTasksActionPayload.model_validate(payload)
    if envelope.action == "approve_delegation":
        return ApproveDelegationActionPayload.model_validate(payload)
    if envelope.action == "cancel_delegation":
        return CancelDelegationActionPayload.model_validate(payload)
    if envelope.action == "cancel_task":
        return CancelTaskActionPayload.model_validate(payload)
    if envelope.action == "retry_task":
        return RetryTaskActionPayload.model_validate(payload)
    if envelope.action == "cancel_conversation":
        if payload:
            raise ValueError("cancel_conversation does not accept a payload")
        return None
    raise ValueError(f"Unsupported action: {envelope.action}")


def decode_json_field(value: object, default: _DefaultT) -> _DefaultT | object:
    """Decode JSON text fields while tolerating already-decoded backend values."""
    if value in (None, ""):
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def conversation_status_for_event(kind: str, current_status: str = "") -> str:
    """Map an event kind to the conversation status it implies.

    Uses SDK kind names (message.user, message.bot, task.status, error, etc.).
    """
    if kind in {"message.user", "message.bot"}:
        if current_status == "cancelling":
            return "cancelling"
        return "running"
    if kind == "task.status":
        return "running"
    if kind == "error":
        return "failed"
    return current_status or "open"


def canonical_registry_connectivity_state(connectivity_state: str) -> str:
    """Return the canonical operator-facing registry connectivity state."""
    value = str(connectivity_state or "").strip()
    if value == "offline":
        return "disconnected"
    return value


def effective_connectivity_state(connectivity_state: str, last_heartbeat_at: str) -> str:
    """Return disconnected when the last heartbeat is older than the registry threshold."""
    effective_state = canonical_registry_connectivity_state(connectivity_state)
    if not last_heartbeat_at:
        return effective_state
    try:
        heartbeat_dt = datetime.fromisoformat(last_heartbeat_at)
        if heartbeat_dt.tzinfo is None:
            heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - heartbeat_dt > timedelta(seconds=_OFFLINE_AFTER_SECONDS):
            return "disconnected"
    except ValueError:
        pass
    return effective_state


def registry_scope_for_agent_row(agent_row: Mapping[str, object]) -> str:
    """Return the stored registry scope for an authenticated agent row."""
    try:
        scope = agent_row["registry_scope"]
    except Exception as exc:
        raise PermissionError("Authenticated agent row missing registry_scope") from exc
    try:
        return validated_registry_scope(scope)
    except ValueError as exc:
        raise PermissionError("Authenticated agent row has invalid registry_scope") from exc
def require_registry_scope(agent_row: Mapping[str, object], required_scopes: set[str]) -> str:
    """Validate an agent row against the required registry scopes."""
    scope = registry_scope_for_agent_row(agent_row)
    if scope not in required_scopes:
        raise RegistryScopeError(scope, required_scopes)
    return scope


def delivery_kinds_for_registry_scope(registry_scope: str) -> tuple[str, ...] | None:
    """Return the delivery kinds visible to the provided registry scope."""
    scope = validated_registry_scope(registry_scope)
    if scope == "channel":
        return ("channel_input", "channel_action", "management_request")
    if scope == "coordination":
        return ("routed_task", "routed_result")
    return None


def runtime_health_summary(value: object) -> RuntimeHealthSummaryRecord:
    """Return the canonical mirrored health summary, or an empty dict."""
    report = report_from_dict(decode_json_field(value, {}))
    if report is None:
        return RuntimeHealthSummaryRecord()
    return RuntimeHealthSummaryRecord.model_validate(asdict(report.summary))


def runtime_health_generated_at(value: object) -> str:
    """Return the mirrored health timestamp, or empty string when absent."""
    report = report_from_dict(decode_json_field(value, {}))
    if report is None:
        return ""
    return report.generated_at


def runtime_health_detail(
    value: object,
    workers: list[RuntimeWorkerRecord],
) -> RuntimeHealthDetailRecord | None:
    """Return a UI-ready mirrored health detail payload."""
    report = report_from_dict(decode_json_field(value, {}))
    if report is None:
        return None
    return RuntimeHealthDetailRecord(
        report=RegistryJsonRecord.model_validate(report_to_dict(report)),
        workers=workers,
        last_mirrored_at=report.generated_at,
    )


def routed_task_created_event(request: RoutedTaskRequest) -> EventRecord:
    created_at = str(request.created_at or utcnow_iso())
    routed_task_id = str(request.routed_task_id)
    title = str(request.title or routed_task_id)
    return EventRecord(
        event_id=f"routed-task:{routed_task_id}:queued:{created_at}",
        conversation_id=str(request.parent_conversation_id),
        kind="task.status",
        content=title,
        metadata=RegistryJsonRecord(
            {"routed_task_id": routed_task_id, "status": "queued"}
        ),
        created_at=created_at,
    )


def routed_task_progress_event(
    *,
    routed_task_id: str,
    parent_conversation_id: str,
    payload: RoutedTaskUpdate,
) -> EventRecord:
    created_at = str(payload.updated_at or utcnow_iso())
    metadata: dict[str, object] = {
        "routed_task_id": routed_task_id,
        "status": str(payload.status),
        "transition_id": str(payload.transition_id),
    }
    if payload.progress is not None:
        metadata["progress"] = payload.progress
    return EventRecord(
        event_id=f"routed-task:{routed_task_id}:{payload.status}:{created_at}",
        conversation_id=parent_conversation_id,
        kind="task.status",
        content=str(payload.summary or payload.status),
        metadata=RegistryJsonRecord.model_validate(metadata),
        created_at=created_at,
    )


def routed_task_result_event(
    *,
    routed_task_id: str,
    parent_conversation_id: str,
    payload: RoutedTaskResult,
) -> EventRecord:
    created_at = str(payload.completed_at or utcnow_iso())
    content = str(payload.summary or payload.full_text or payload.status)
    return EventRecord(
        event_id=f"routed-task:{routed_task_id}:result:{created_at}",
        conversation_id=parent_conversation_id,
        kind="task.status",
        content=content,
        metadata=RegistryJsonRecord(
            {
                "routed_task_id": routed_task_id,
                "status": str(payload.status),
                "transition_id": str(payload.transition_id),
            }
        ),
        created_at=created_at,
    )


def delegation_event(
    *,
    kind: Literal["delegation.proposed", "delegation.submitted", "delegation.completed"],
    proposal_id: str,
    conversation_id: str,
    tasks: list[Mapping[str, object] | RegistryJsonRecord],
    created_at: str,
    content: str = "",
    origin_transport_ref: str = "",
    authorized_actor_key: str = "",
) -> EventRecord:
    normalized_tasks = [
        task.as_dict() if isinstance(task, RegistryJsonRecord) else dict(task)
        for task in tasks
    ]
    metadata: dict[str, object] = {
        "proposal_id": proposal_id,
        "tasks": normalized_tasks,
    }
    if origin_transport_ref:
        metadata["origin_transport_ref"] = origin_transport_ref
    if authorized_actor_key:
        metadata["authorized_actor_key"] = authorized_actor_key
    return EventRecord(
        event_id=f"{kind}:{proposal_id}",
        conversation_id=conversation_id,
        kind=kind,
        content=content,
        metadata=RegistryJsonRecord(metadata),
        created_at=created_at,
    )


class AbstractRegistryStore(Protocol):
    """Backend-neutral contract for the registry service persistence layer."""

    def enroll(self, requested_card: AgentCard) -> EnrollmentResult:
        """Persist a new agent card, issue an agent token, and return enrollment metadata."""

    def register(self, agent_token: str, payload: AgentRegisterRequest) -> AgentRecord:
        """Refresh an enrolled agent's card and runtime state, returning the stored agent view."""

    def heartbeat(self, agent_token: str, payload: AgentHeartbeatRequest) -> HealthSummary:
        """Update heartbeat state for a known agent and return the refreshed runtime view."""

    def search_agents(self, query: AgentDiscoveryQuery) -> list[AgentRecord]:
        """Return agents matching the requested discovery constraints."""

    def resolve_agent_for_token(self, agent_token: str) -> AgentRecord | None:
        """Return the agent row for this token, or None if unknown. Used for auth context resolution."""

    def assert_agent_scope(self, agent_token: str, required_scopes: set[str]) -> None:
        """Validate that the authenticated agent token has one of the required scopes."""

    def create_delivery(
        self,
        *,
        target_agent_id: str,
        kind: str,
        payload: RegistryRecordModel,
    ) -> DeliveryRecord:
        """Queue a delivery for an agent and return its durable identifiers."""

    def create_routed_task(self, request: RegistryRecordModel) -> TaskRecord:
        """Persist a routed task and queue the corresponding agent delivery."""

    def create_management_request(self, request: ManagementRequest) -> ManagementRequest:
        """Persist a management request and queue the corresponding agent delivery."""

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> DeliveryPollResult:
        """Lease queued deliveries for an authenticated agent after the requested cursor."""

    def ack(self, agent_token: str, *, delivery_ids: list[str], classification: str) -> AckResult:
        """Acknowledge previously polled deliveries for an authenticated agent."""

    def update_routed_task_status(
        self, agent_token: str, routed_task_id: str, payload: RegistryRecordModel
    ) -> TaskRecord:
        """Update routed-task status and any timeline mirrors published by the worker."""

    def update_routed_task_result(
        self, agent_token: str, routed_task_id: str, payload: RegistryRecordModel
    ) -> TaskRecord:
        """Persist a routed-task terminal result and queue the routed_result delivery upstream."""

    def report_management_result(
        self,
        agent_token: str,
        request_id: str,
        payload: ManagementResult,
    ) -> ManagementResult:
        """Persist a management-result terminal payload for a previously queued request."""

    def get_management_result(self, request_id: str) -> ManagementResult | None:
        """Return the current result for a management request once reported."""

    def deregister(self, agent_token: str) -> AgentRecord:
        """Mark an agent disconnected while preserving its durable registry identity."""

    def get_capability_override(self, capability_name: str) -> bool | None:
        """Return True/False for an override row, or None when no override exists."""

    def set_capability_override(self, capability_name: str, enabled: bool, set_by: str = "ui") -> None:
        """Persist or update a global capability override."""

    def list_capabilities(self) -> list[CapabilityRecord]:
        """Return the declared capability universe merged with override state."""

    def list_agents(
        self,
        *,
        for_agent_id: str | None = None,
        cursor: int = 0,
        limit: int = 25,
        q: str = "",
        connectivity_state: str = "",
    ) -> list[AgentRecord]:
        """Return registered agents in UI-ready form with offset-based pagination."""

    def get_agent_runtime_health(self, agent_id: str) -> RuntimeHealthDetailRecord | None:
        """Return mirrored runtime-health detail for a registered agent."""

    def agent_exists(self, agent_id: str) -> bool:
        """Return True when the agent_id is enrolled."""

    def create_conversation(
        self,
        *,
        target_agent_id: str,
        title: str,
        origin_channel: str = "registry",
        external_conversation_ref: str = "",
    ) -> ConversationRecord:
        """Create a new registry-originated conversation."""

    def list_conversations(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, q: str = "", status: str = "", conversation_type: str = "") -> list[ConversationRecord]:
        """Return the registry conversation index with offset-based pagination."""

    def get_conversation(self, conversation_id: str) -> ConversationRecord:
        """Return one conversation including any linked routed tasks."""

    def search_conversations(self, q: str, limit: int = 20) -> list[ConversationSearchHitRecord]:
        """Return conversation search hits with highlighted snippets."""

    def get_usage_summary(self, since_iso: str, until_iso: str = "") -> list[UsageSummaryRecord]:
        """Return reported usage timeline rows within the provided UTC ISO timestamp range."""

    def get_summary(self, *, now_iso: str) -> RegistrySummaryRecord:
        """Return global dashboard aggregates for the registry UI."""

    def list_approvals(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25) -> list[ApprovalRecord]:
        """Return currently pending conversation approvals in UI-ready form with offset-based pagination."""

    def add_conversation_message(self, conversation_id: str, text: str) -> MessageRecord:
        """Queue a follow-up channel_input for an existing conversation."""

    def add_conversation_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        """Submit a typed coordination action for an existing conversation."""

    def list_tasks(
        self,
        *,
        for_agent_id: str | None = None,
        parent_conversation_id: str = "",
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
    ) -> list[TaskRecord]:
        """Return routed tasks in UI-ready form with offset-based pagination."""

    def get_task(self, routed_task_id: str) -> TaskRecord:
        """Return one routed task in UI-ready form."""

    def publish_events(
        self,
        agent_token: str,
        conversation_id: str,
        events: list[RegistryRecordModel],
    ) -> PublishEventsResult:
        """Persist events for a conversation. Idempotent on event_id (ON CONFLICT DO NOTHING)."""

    def list_events(
        self,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> EventPageRecord:
        """Return paginated events for a conversation using latest/before/after windows."""

    def list_messages(self, conversation_id: str, *, cursor: int = 0, limit: int = 50) -> MessagePageRecord:
        """Return paginated message events (message.user, message.bot) for a conversation."""

    def list_agent_conversations(self, agent_id: str, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 50, conversation_type: str = "") -> list[ConversationRecord]:
        """Return paginated conversations for a specific agent."""

    def get_agent_status(self, agent_id: str) -> AgentStatusRecord | None:
        """Return agent status joining agents + workers + event-derived counts."""

    def get_usage(self, *, agent_id: str = "", conversation_id: str = "", since: str = "", until: str = "") -> list[UsageSummaryRecord]:
        """Return usage summary, filterable by agent/conversation/date range."""

    def export_conversation(self, conversation_id: str) -> str:
        """Export conversation as markdown events."""

    def purge_old_events(self, older_than_days: int = 30) -> int:
        """Delete events older than the given number of days. Return count deleted."""

    # ------------------------------------------------------------------
    # Skill / guidance persistence (registry-owned content store)
    # ------------------------------------------------------------------

    def replace_skill_track(self, record: RuntimeSkillTrackRecord) -> None:
        """Upsert one skill track and set its active revision."""

    def delete_skill_track(self, slug: str, *, source_kind: str, source_uri: str = "", owner_actor: str = "") -> bool:
        """Delete one exact skill track. Returns True when a row was removed."""

    def list_skill_summaries(self) -> list[RuntimeSkillSummary]:
        """Return effective runtime skill summaries after precedence resolution."""

    def resolve_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        """Return the effective runtime skill track for a slug."""

    def list_skill_tracks(self, slug: str) -> list[RuntimeSkillTrackRecord]:
        """Return all tracks for a slug, ordered by precedence."""

    def list_runtime_skill_summaries(self) -> list[RuntimeSkillSummary]:
        """Return runtime-eligible skill summaries after precedence resolution."""

    def resolve_runtime_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        """Return the runtime-eligible track for a slug using published revisions only."""

    def upsert_skill_draft(self, record: RuntimeSkillTrackRecord) -> None:
        """Upsert one skill track and set its active revision without publishing it."""

    def list_skill_revisions(self, slug: str) -> list[SkillRevisionRecord]:
        """Return lifecycle revisions for the mutable custom skill track, newest first."""

    def list_skill_approvals(self, slug: str) -> list[LifecycleApprovalRecord]:
        """Return approval records for the mutable custom skill track, newest first."""

    def get_latest_skill_approval_action(self, slug: str, revision_id: str) -> str:
        """Return the newest approval action for one skill revision, or an empty string."""

    def append_skill_approval(
        self, slug: str, revision_id: str, *, action: str, actor: str, note: str = "",
    ) -> LifecycleApprovalRecord:
        """Append one approval-history event for the mutable custom skill track."""

    def set_skill_revision_status(self, slug: str, revision_id: str, status: str) -> None:
        """Update lifecycle status for one revision on the mutable custom skill track."""

    def set_published_skill_revision(self, slug: str, revision_id: str) -> None:
        """Point the mutable custom skill track at one published revision for runtime use."""

    def clear_published_skill_revision(self, slug: str) -> None:
        """Remove the runtime published pointer for the mutable custom skill track."""

    def apply_skill_lifecycle_transition(
        self,
        slug: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
    ) -> LifecycleApprovalRecord | None:
        """Atomically apply one validated lifecycle transition for a mutable custom skill."""

    def replace_provider_guidance(self, record: ProviderGuidanceTrackRecord) -> None:
        """Upsert one provider-guidance track and set its active revision."""

    def get_provider_guidance(
        self, provider: str, *, scope_kind: str = "system", scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        """Return one provider-guidance track for the requested scope."""

    def resolve_provider_guidance(
        self, provider: str, *, instance_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        """Resolve the runtime published guidance, instance override first then system default."""

    def upsert_provider_guidance_draft(self, record: ProviderGuidanceTrackRecord) -> None:
        """Upsert one provider-guidance track and set its active revision without publishing it."""

    def list_provider_guidance_revisions(
        self, provider: str, *, scope_kind: str = "system", scope_key: str = "",
    ) -> list[ProviderGuidanceRevisionRecord]:
        """Return lifecycle revisions for one provider-guidance track, newest first."""

    def list_provider_guidance_approvals(
        self, provider: str, *, scope_kind: str = "system", scope_key: str = "",
    ) -> list[LifecycleApprovalRecord]:
        """Return approval records for one provider-guidance track, newest first."""

    def get_latest_provider_guidance_approval_action(
        self, provider: str, revision_id: str, *, scope_kind: str = "system", scope_key: str = "",
    ) -> str:
        """Return the newest approval action for one provider-guidance revision, or an empty string."""

    def append_provider_guidance_approval(
        self,
        provider: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> LifecycleApprovalRecord:
        """Append one approval-history event for one provider-guidance track."""

    def set_provider_guidance_revision_status(
        self, provider: str, revision_id: str, status: str, *, scope_kind: str = "system", scope_key: str = "",
    ) -> None:
        """Update lifecycle status for one provider-guidance revision."""

    def set_published_provider_guidance_revision(
        self, provider: str, revision_id: str, *, scope_kind: str = "system", scope_key: str = "",
    ) -> None:
        """Point one provider-guidance track at a published revision for runtime use."""

    def clear_published_provider_guidance_revision(
        self, provider: str, *, scope_kind: str = "system", scope_key: str = "",
    ) -> None:
        """Remove the runtime published pointer for one provider-guidance track."""

    def apply_provider_guidance_lifecycle_transition(
        self,
        provider: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> LifecycleApprovalRecord | None:
        """Atomically apply one validated lifecycle transition for one provider-guidance track."""
