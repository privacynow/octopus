"""Abstract registry store contract and shared pure helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
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
from octopus_sdk.protocols import (
    ProtocolAuthoringOptionsRecord,
    ProtocolAutoDesignEventSummaryRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignSessionRecord,
    ProtocolAccessContextRecord,
    ProtocolDefinitionDocumentRecord,
    ProtocolDefinitionDiffRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolDraftCreateRecord,
    ProtocolMutationRecord,
    ProtocolIssueRecord,
    ProtocolMaintenanceResultRecord,
    ProtocolTemplateSummaryRecord,
    ProtocolTextDocumentRecord,
    ProtocolRunCreateRecord,
    ProtocolRunDetailRecord,
    ProtocolRunExportRecord,
    ProtocolRunMutationRecord,
    ProtocolRunParticipantRecord,
    ProtocolRunRecord,
    ProtocolRuntimeCapabilityExchangeResultRecord,
    ProtocolRuntimeCapabilityTokenRecord,
    ProtocolScenarioRecord,
    ProtocolArtifactRecord,
    ProtocolArtifactSnapshotRecord,
    ProtocolArtifactRuntimeEventRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolTransitionRecord,
)

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
    RoutingSkillRecord,
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
    RecoveryActionPayload,
    RetryDecisionActionPayload,
    RetryTaskActionPayload,
    RuntimeHealthDetailRecord,
    TaskRecord,
    UsageSummaryRecord,
)
from octopus_sdk.resources import ResourceAttachmentRecord, ResourceRecord
from octopus_sdk.time_utils import seconds_from_now_iso, utc_now_iso as utcnow_iso

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


class RoutingSkillDisabledError(RuntimeError):
    """Raised when routing requests a routing skill that has been globally disabled."""


class RegistryScopeError(PermissionError):
    """Raised when an agent registry scope cannot access a protected action."""

    def __init__(self, scope: str, required_scopes: set[str]) -> None:
        self.scope = scope or "full"
        self.required_scopes = tuple(sorted(required_scopes))
        super().__init__(
            f"Agent registry_scope '{self.scope}' cannot access this endpoint. "
            f"Required: {', '.join(self.required_scopes)}"
        )


def offline_before_iso() -> str:
    """Return the cutoff timestamp for agents considered offline."""
    return seconds_from_now_iso(-_OFFLINE_AFTER_SECONDS)


_DefaultT = TypeVar("_DefaultT")


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
    if envelope.action in {"approve_pending", "reject_pending"}:
        return ApproveRejectActionPayload.model_validate(payload)
    if envelope.action in {"retry_allow", "retry_skip"}:
        return RetryDecisionActionPayload.model_validate(payload)
    if envelope.action in {"recovery_discard", "recovery_replay"}:
        return RecoveryActionPayload.model_validate(payload)
    if envelope.action == "direct_assign":
        return DirectAssignActionPayload.model_validate(payload)
    if envelope.action == "delegate_tasks":
        return DelegateTasksActionPayload.model_validate(payload)
    if envelope.action == "delegation_approve":
        return ApproveDelegationActionPayload.model_validate(payload)
    if envelope.action == "delegation_cancel":
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


def runtime_health_execution_fields(value: object) -> dict[str, object]:
    summary = runtime_health_summary(value)
    return {
        "execution_state": str(summary.execution_state or "healthy"),
        "execution_provider": str(summary.execution_provider or ""),
        "execution_fault_kind": str(summary.execution_fault_kind or ""),
        "execution_fault_code": str(summary.execution_fault_code or ""),
        "execution_fault_detail": str(summary.execution_fault_detail or ""),
        "execution_faulted_at": str(summary.execution_faulted_at or ""),
        "execution_resettable": bool(summary.execution_resettable),
        "execution_last_returncode": summary.execution_last_returncode,
    }


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

    def get_routing_skill_override(self, skill_name: str) -> bool | None:
        """Return True/False for an override row, or None when no override exists."""

    def set_routing_skill_override(self, skill_name: str, enabled: bool, set_by: str = "ui") -> None:
        """Persist or update a global routing-skill override."""

    def list_routing_skills(self) -> list[RoutingSkillRecord]:
        """Return the declared routing-skill universe merged with override state."""

    def list_agents(
        self,
        *,
        for_agent_id: str | None = None,
        cursor: int = 0,
        limit: int = 25,
        q: str = "",
        connectivity_state: str = "",
        include_soft_deleted: bool = False,
    ) -> list[AgentRecord]:
        """Return registered agents in UI-ready form with offset-based pagination."""

    def update_agent_trust_tier(self, agent_id: str, trust_tier: str) -> AgentRecord:
        """Update an agent's trust tier (community|trusted|verified|restricted)."""

    def update_agent_capacity(
        self,
        agent_id: str,
        *,
        current_capacity: int | None = None,
        max_capacity: int | None = None,
    ) -> AgentRecord:
        """Admin override for an agent's capacity counters."""

    def rotate_agent_token(self, agent_id: str) -> tuple[AgentRecord, str]:
        """Issue a fresh agent token for an enrolled agent, returning (record, plaintext_token)."""

    def soft_delete_agent(self, agent_id: str) -> AgentRecord:
        """Mark an agent soft-deleted; hidden from default listings, connectivity forced to disconnected."""

    def preview_selector_resolution(
        self,
        selector,
        *,
        exclude_agent_ids: tuple[str, ...] = (),
    ) -> list[dict[str, object]]:
        """Return every candidate row a selector matches, with no ambiguity enforcement."""

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
        source_kind: str = "human",
        hidden_from_default_views: bool = False,
    ) -> ConversationRecord:
        """Create a new registry-originated conversation."""

    def list_conversations(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, q: str = "", status: str = "", conversation_type: str = "", include_generated: bool = True) -> list[ConversationRecord]:
        """Return the registry conversation index with offset-based pagination."""

    def get_conversation(self, conversation_id: str) -> ConversationRecord:
        """Return one conversation including any linked routed tasks."""

    def search_conversations(self, q: str, limit: int = 20) -> list[ConversationSearchHitRecord]:
        """Return conversation search hits with highlighted snippets."""

    def get_usage_summary(self, since_iso: str, until_iso: str = "") -> list[UsageSummaryRecord]:
        """Return reported usage timeline rows within the provided UTC ISO timestamp range."""

    def get_summary(self, *, now_iso: str) -> RegistrySummaryRecord:
        """Return global dashboard aggregates for the registry UI."""

    def cleanup_workspace_data(self) -> dict[str, object]:
        """Remove workspace work records while preserving registered agents and catalog content."""

    def save_workspace_cleanup_inventory(
        self,
        *,
        inventory_id: str,
        agent_id: str,
        workspace_ref: str = "",
        protocol_run_id: str = "",
        scan_status: str = "completed",
        file_count: int = 0,
        total_bytes: int = 0,
        retained_bytes: int = 0,
        transient_bytes: int = 0,
        unknown_bytes: int = 0,
        summary: Mapping[str, object] | None = None,
        access: ProtocolAccessContextRecord,
    ) -> dict[str, object]:
        """Persist a workspace cleanup dry-run or execution observation."""

    def get_workspace_cleanup_inventory(
        self,
        inventory_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> dict[str, object] | None:
        """Return one workspace cleanup observation."""

    def list_approvals(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25) -> list[ApprovalRecord]:
        """Return currently pending conversation approvals in UI-ready form with offset-based pagination."""

    def create_resource(self, resource: ResourceRecord) -> ResourceRecord:
        """Persist a user-provided input resource."""

    def get_resource(self, resource_id: str) -> ResourceRecord:
        """Return one active or archived resource."""

    def list_resources(
        self,
        *,
        owner_actor_ref: str = "",
        source_surface: str = "",
        source_ref: str = "",
        target_kind: str = "",
        target_ref: str = "",
        cursor: int = 0,
        limit: int = 50,
    ) -> list[ResourceRecord]:
        """List resources by owner/source or attached target."""

    def attach_resource(
        self,
        *,
        resource_id: str,
        target_kind: str,
        target_ref: str,
        relation: str = "context",
        created_by: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> ResourceAttachmentRecord:
        """Attach a resource to a product target."""

    def list_resource_attachments(
        self,
        *,
        target_kind: str,
        target_ref: str,
    ) -> list[ResourceAttachmentRecord]:
        """List live resource attachments for a product target."""

    def list_resource_targets(self, *, resource_id: str) -> list[ResourceAttachmentRecord]:
        """List live targets for one resource."""

    def get_resource_attachment(self, attachment_id: str) -> ResourceAttachmentRecord:
        """Return one resource attachment."""

    def detach_resource(
        self,
        *,
        attachment_id: str,
        detached_by: str = "",
    ) -> ResourceAttachmentRecord:
        """Detach a resource from a product target."""

    def add_conversation_message(
        self,
        conversation_id: str,
        text: str,
        *,
        resource_refs: tuple[str, ...] = (),
    ) -> MessageRecord:
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
        protocol_run_id: str = "",
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
        completed_since_iso: str = "",
        include_generated: bool = True,
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

    def list_agent_conversations(self, agent_id: str, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 50, conversation_type: str = "", include_generated: bool = True) -> list[ConversationRecord]:
        """Return paginated conversations for a specific agent."""

    def get_agent_status(self, agent_id: str) -> AgentStatusRecord | None:
        """Return agent status joining agents + workers + event-derived counts."""

    def get_usage(self, *, agent_id: str = "", conversation_id: str = "", since: str = "", until: str = "") -> list[UsageSummaryRecord]:
        """Return usage summary, filterable by agent/conversation/date range."""

    def export_conversation(self, conversation_id: str) -> str:
        """Export conversation as markdown events."""

    # ------------------------------------------------------------------
    # Protocol definitions and runs
    # ------------------------------------------------------------------

    def list_protocols(
        self,
        *,
        access: ProtocolAccessContextRecord,
        cursor: int = 0,
        limit: int = 50,
        lifecycle_state: str = "",
        slug: str = "",
        created_after: str = "",
    ) -> list[ProtocolDefinitionRecord]:
        """Return protocol definitions in UI-ready form."""

    def get_protocol_template(
        self,
        slug: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolDefinitionDocumentRecord:
        """Return one user-authored protocol template document by slug."""

    def list_protocol_templates(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolTemplateSummaryRecord]:
        """Return template metadata for protocol authoring."""

    def get_protocol_authoring_options(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAuthoringOptionsRecord:
        """Return protocol-authoring sections and option lists."""

    def get_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        """Return one protocol definition with latest validation/version metadata."""

    def get_protocol_version(
        self,
        protocol_id: str,
        version_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolDefinitionVersionRecord:
        """Return one immutable protocol definition version."""

    def save_protocol_draft(
        self,
        *,
        access: ProtocolAccessContextRecord,
        protocol_id: str,
        slug: str,
        display_name: str,
        description: str,
        definition_json: RegistryJsonRecord,
        authoring_surface: str = "",
        expected_revision: int | None = None,
    ) -> ProtocolMutationRecord:
        """Create or update one protocol draft."""

    def create_protocol_draft(
        self,
        payload: ProtocolDraftCreateRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolMutationRecord:
        """Create one persisted draft from blank, a template, or an existing protocol."""

    def delete_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        """Discard one unpublished protocol draft."""

    def validate_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        """Validate the current draft for one protocol."""

    def publish_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        """Publish the current validated draft as a new immutable version."""

    def publish_protocol_template(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        slug: str = "",
        display_name: str = "",
        description: str = "",
    ) -> ProtocolMutationRecord:
        """Publish the latest immutable version as a reusable template snapshot."""

    def archive_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        """Archive one published protocol definition."""

    def list_protocol_runs(
        self,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 25,
        cursor: int = 0,
        status: str = "",
        protocol_id: str = "",
        entry_agent_id: str = "",
        root_conversation_id: str = "",
        origin_channel: str = "",
        include_generated: bool = True,
    ) -> list[ProtocolRunRecord]:
        """Return protocol runs in UI-ready form."""

    def parse_protocol_document_text(
        self,
        *,
        access: ProtocolAccessContextRecord,
        definition_text: str,
        format: str = "json",
        validation_mode: str = "strict",
    ) -> ProtocolTextDocumentRecord:
        """Parse protocol text into a draft-safe or strict validated document."""

    def export_protocol_draft(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        format: str = "json",
    ) -> ProtocolTextDocumentRecord:
        """Export the current protocol draft document as JSON or YAML text."""

    def diff_protocol_draft(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        format: str = "json",
    ) -> ProtocolDefinitionDiffRecord:
        """Return a unified diff between the current draft and the latest published version."""

    def create_protocol_auto_design_session(
        self,
        payload: ProtocolAutoDesignRequestRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        """Create a generated or revision Auto Protocol session."""

    def get_protocol_auto_design_session(
        self,
        session_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        """Return one Auto Protocol session visible to this actor."""

    def update_protocol_auto_design_session(
        self,
        session: ProtocolAutoDesignSessionRecord,
        *,
        access: ProtocolAccessContextRecord,
        event_kind: str = "updated",
    ) -> ProtocolAutoDesignSessionRecord:
        """Persist one Auto Protocol session state update."""

    def list_protocol_auto_design_session_events(
        self,
        session_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolAutoDesignEventSummaryRecord]:
        """Return safe user-facing Auto Protocol session event summaries."""

    def list_protocol_issues(
        self,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 25,
        cursor: int = 0,
        issue_kind: str = "",
        protocol_run_id: str = "",
        protocol_id: str = "",
    ) -> list[ProtocolIssueRecord]:
        """Return protocol support/admin issues for visible runs."""

    def create_protocol_run(
        self,
        payload: ProtocolRunCreateRecord,
        *,
        access: ProtocolAccessContextRecord,
        idempotency_key: str = "",
    ) -> ProtocolRunMutationRecord:
        """Create a protocol run and dispatch its first stage."""

    def get_protocol_run(self, run_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolRunDetailRecord:
        """Return one protocol run with participants, stages, artifacts, and transitions."""

    def get_protocol_run_participants(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolRunParticipantRecord]:
        """Return participant resolution state for one run."""

    def get_protocol_run_artifacts(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolArtifactRecord]:
        """Return artifact history for one run."""

    def get_protocol_artifact_snapshot(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactSnapshotRecord | None:
        """Return the current durable snapshot for one run artifact."""

    def save_protocol_artifact_snapshot(
        self,
        snapshot: ProtocolArtifactSnapshotRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactSnapshotRecord:
        """Persist a durable artifact snapshot record."""

    def delete_protocol_artifact_snapshot(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactSnapshotRecord:
        """Mark a durable artifact snapshot deleted."""

    def get_protocol_run_timeline(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolTransitionRecord]:
        """Return transition history for one run."""

    def get_protocol_artifact_runtime(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeInstanceRecord | None:
        """Return the current runtime instance for one run artifact."""

    def save_protocol_artifact_runtime(
        self,
        runtime: ProtocolArtifactRuntimeInstanceRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeInstanceRecord:
        """Persist runtime instance state for one run artifact."""

    def append_protocol_artifact_runtime_event(
        self,
        event: ProtocolArtifactRuntimeEventRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeEventRecord:
        """Append a runtime lifecycle/audit event for one artifact."""

    def list_protocol_artifact_runtime_events(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 50,
    ) -> list[ProtocolArtifactRuntimeEventRecord]:
        """Return runtime lifecycle/audit events for one artifact."""

    def mint_runtime_capability_token(
        self,
        *,
        protocol_run_id: str,
        protocol_stage_execution_id: str,
        artifact_key: str,
        participant_key: str,
        target_agent_id: str,
        allowed_actions: list[str] | tuple[str, ...],
        expires_at: str,
        actor_ref: str,
    ) -> ProtocolRuntimeCapabilityTokenRecord:
        """Create a non-secret runtime capability reference for a protocol stage."""

    def exchange_runtime_capability_token(
        self,
        *,
        capability_ref: str,
        target_agent_id: str,
    ) -> ProtocolRuntimeCapabilityExchangeResultRecord:
        """Exchange a non-secret capability reference for a short-lived bearer."""

    def validate_runtime_capability_token(
        self,
        *,
        bearer_token: str,
        protocol_run_id: str,
        artifact_key: str,
        action: str,
    ) -> ProtocolRuntimeCapabilityTokenRecord | None:
        """Validate a scoped runtime bearer token."""

    def revoke_runtime_capability_tokens_for_stage(self, protocol_stage_execution_id: str, *, reason: str = "") -> int:
        """Revoke active scoped runtime bearers for a stage execution."""

    def export_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolRunExportRecord:
        """Return one export-safe protocol run bundle."""

    def act_on_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        action: str,
        reason: str,
        idempotency_key: str = "",
        expected_version: int | None = None,
    ) -> ProtocolRunMutationRecord:
        """Apply one idempotent operator action to a protocol run."""

    def archive_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        reason: str = "",
    ) -> ProtocolRunMutationRecord:
        """Archive one inactive protocol run while preserving audit and retained artifacts."""

    def restore_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        reason: str = "",
    ) -> ProtocolRunMutationRecord:
        """Restore one archived protocol run to its previous terminal state."""

    def delete_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        reason: str = "",
    ) -> ProtocolRunMutationRecord:
        """Soft-delete one terminal or archived protocol run."""

    def run_protocol_maintenance(self, *, now: str = "") -> ProtocolMaintenanceResultRecord:
        """Sweep protocol maintenance work such as overdue timeouts."""

    def list_protocol_scenarios(
        self,
        *,
        protocol_id: str = "",
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolScenarioRecord]:
        """Return canned rehearsal scenarios for this org, optionally filtered by protocol."""

    def create_protocol_scenario(
        self,
        *,
        payload: Mapping[str, object],
        access: ProtocolAccessContextRecord,
    ) -> ProtocolScenarioRecord:
        """Create a canned rehearsal scenario."""

    def delete_protocol_scenario(
        self,
        *,
        scenario_id: str,
        access: ProtocolAccessContextRecord,
    ) -> bool:
        """Delete a canned rehearsal scenario; returns True if a row was removed."""

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
