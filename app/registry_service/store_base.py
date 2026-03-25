"""Abstract registry store contract and shared pure helpers."""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

from app.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
    SkillRevisionRecord,
)

from app.runtime_health import report_from_dict, report_to_dict
from octopus_sdk.registry.models import (
    ApproveDelegationActionPayload,
    ApproveRejectActionPayload,
    CancelDelegationActionPayload,
    CancelTaskActionPayload,
    CoordinationActionEnvelope,
    DelegateTasksActionPayload,
    DirectAssignActionPayload,
    RecoveryActionPayload,
    RetryDecisionActionPayload,
    RetryTaskActionPayload,
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


def ensure_json(value: Any) -> str:
    """Serialize dataclasses and JSON-encodable values to a JSON string."""
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value)


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise ValueError(f"{field_name} requires non-empty text")
    return text.strip()


def _optional_text_field(payload: dict[str, Any], field_name: str) -> str | object:
    if field_name not in payload:
        return _MISSING
    return str(payload.get(field_name) or "")


def _optional_int_field(
    payload: dict[str, Any],
    field_name: str,
    *,
    minimum: int,
) -> int | object:
    if field_name not in payload:
        return _MISSING
    value = payload.get(field_name)
    if value in (None, ""):
        raise ValueError(f"{field_name} requires an integer value")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} requires an integer value") from exc
    if parsed < minimum:
        comparator = "positive" if minimum == 1 else "non-negative"
        raise ValueError(f"{field_name} requires a {comparator} integer value")
    return parsed


def _optional_dict_field(payload: dict[str, Any], field_name: str) -> dict[str, Any] | object:
    if field_name not in payload:
        return _MISSING
    value = payload.get(field_name)
    if value is None:
        raise ValueError(f"{field_name} must be an object")
    return _require_mapping(value, field_name)


def _optional_string_list_field(payload: dict[str, Any], field_name: str) -> list[str] | object:
    if field_name not in payload:
        return _MISSING
    value = payload.get(field_name)
    if isinstance(value, str) or not isinstance(value, (list, tuple, set)):
        raise ValueError(f"{field_name} must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _reject_unknown_fields(
    payload: dict[str, Any],
    *,
    allowed_fields: set[str],
    field_name: str,
) -> None:
    unknown = sorted(set(payload) - allowed_fields)
    if unknown:
        raise ValueError(f"{field_name} contains unsupported fields: {', '.join(unknown)}")


def validated_registry_scope(value: Any) -> str:
    scope = str(value or "").strip().lower()
    if not scope:
        raise ValueError("registry_scope requires non-empty text")
    if scope not in VALID_REGISTRY_SCOPES:
        raise ValueError(
            f"registry_scope must be one of: {', '.join(VALID_REGISTRY_SCOPES)}"
        )
    return scope


def validated_agent_card_payload(
    value: Any,
    *,
    require_registry_scope: bool,
) -> dict[str, Any]:
    card = _require_mapping(value, "agent_card")
    _reject_unknown_fields(
        card,
        allowed_fields={
            "bot_key",
            "display_name",
            "slug",
            "role",
            "registry_scope",
            "capabilities",
            "tags",
            "description",
            "provider",
            "mode",
            "connectivity_state",
            "current_capacity",
            "max_capacity",
            "channel_capabilities",
            "version",
        },
        field_name="agent_card",
    )
    normalized: dict[str, Any] = {}
    for field_name in (
        "display_name",
        "slug",
        "role",
        "description",
        "provider",
        "mode",
        "connectivity_state",
        "version",
    ):
        field_value = _optional_text_field(card, field_name)
        if field_value is not _MISSING:
            normalized[field_name] = field_value
    capabilities = _optional_string_list_field(card, "capabilities")
    if capabilities is not _MISSING:
        normalized["capabilities"] = capabilities
    tags = _optional_string_list_field(card, "tags")
    if tags is not _MISSING:
        normalized["tags"] = tags
    channel_capabilities = _optional_string_list_field(card, "channel_capabilities")
    if channel_capabilities is not _MISSING:
        normalized["channel_capabilities"] = channel_capabilities
    current_capacity = _optional_int_field(card, "current_capacity", minimum=0)
    if current_capacity is not _MISSING:
        normalized["current_capacity"] = current_capacity
    max_capacity = _optional_int_field(card, "max_capacity", minimum=1)
    if max_capacity is not _MISSING:
        normalized["max_capacity"] = max_capacity
    if require_registry_scope or "registry_scope" in card:
        normalized["registry_scope"] = validated_registry_scope(card.get("registry_scope"))
    bot_key = _optional_text_field(card, "bot_key")
    if bot_key is not _MISSING:
        normalized["bot_key"] = bot_key
    return normalized


def validated_register_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = _require_mapping(payload, "register payload")
    _reject_unknown_fields(
        data,
        allowed_fields={"agent_card", "connectivity_state", "current_capacity", "max_capacity"},
        field_name="register payload",
    )
    normalized: dict[str, Any] = {
        "agent_card": validated_agent_card_payload(
            data.get("agent_card"),
            require_registry_scope=False,
        )
    }
    connectivity_state = _optional_text_field(data, "connectivity_state")
    if connectivity_state is not _MISSING:
        normalized["connectivity_state"] = connectivity_state
    current_capacity = _optional_int_field(data, "current_capacity", minimum=0)
    if current_capacity is not _MISSING:
        normalized["current_capacity"] = current_capacity
    max_capacity = _optional_int_field(data, "max_capacity", minimum=1)
    if max_capacity is not _MISSING:
        normalized["max_capacity"] = max_capacity
    return normalized


def validated_heartbeat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = _require_mapping(payload, "heartbeat payload")
    _reject_unknown_fields(
        data,
        allowed_fields={"connectivity_state", "current_capacity", "max_capacity", "runtime_health"},
        field_name="heartbeat payload",
    )
    normalized: dict[str, Any] = {}
    connectivity_state = _optional_text_field(data, "connectivity_state")
    if connectivity_state is not _MISSING:
        normalized["connectivity_state"] = connectivity_state
    current_capacity = _optional_int_field(data, "current_capacity", minimum=0)
    if current_capacity is not _MISSING:
        normalized["current_capacity"] = current_capacity
    max_capacity = _optional_int_field(data, "max_capacity", minimum=1)
    if max_capacity is not _MISSING:
        normalized["max_capacity"] = max_capacity
    runtime_health = _optional_dict_field(data, "runtime_health")
    if runtime_health is not _MISSING:
        normalized["runtime_health"] = runtime_health
    return normalized


def validated_timeline_events(value: Any, *, field_name: str = "events") -> list[dict[str, Any]]:
    if isinstance(value, str) or not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    events: list[dict[str, Any]] = []
    for index, raw_event in enumerate(value):
        if not isinstance(raw_event, dict):
            raise ValueError(f"{field_name}[{index}] must be an object")
        metadata = raw_event.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError(f"{field_name}[{index}].metadata must be an object")
        progress = raw_event.get("progress")
        if progress is not None:
            try:
                progress = int(progress)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field_name}[{index}].progress requires an integer value") from exc
        events.append(
            {
                "event_id": _required_text(raw_event.get("event_id"), f"{field_name}[{index}].event_id"),
                "conversation_id": _required_text(
                    raw_event.get("conversation_id"),
                    f"{field_name}[{index}].conversation_id",
                ),
                "kind": _required_text(raw_event.get("kind"), f"{field_name}[{index}].kind"),
                "title": _required_text(raw_event.get("title"), f"{field_name}[{index}].title"),
                "body": str(raw_event.get("body", "") or ""),
                "status": str(raw_event.get("status", "") or ""),
                "progress": progress,
                "metadata": metadata,
                "created_at": _required_text(
                    raw_event.get("created_at"),
                    f"{field_name}[{index}].created_at",
                ),
            }
        )
    return events


def validated_search_query(query: dict[str, Any]) -> dict[str, Any]:
    data = _require_mapping(query, "search_agents query")
    _reject_unknown_fields(
        data,
        allowed_fields={"role", "required_state", "free_text", "capabilities", "tags", "exclude_agent_ids"},
        field_name="search_agents query",
    )
    normalized: dict[str, Any] = {}
    for field_name in ("role", "required_state", "free_text"):
        field_value = _optional_text_field(data, field_name)
        if field_value is not _MISSING:
            normalized[field_name] = field_value
    capabilities = _optional_string_list_field(data, "capabilities")
    if capabilities is not _MISSING:
        normalized["capabilities"] = capabilities
    tags = _optional_string_list_field(data, "tags")
    if tags is not _MISSING:
        normalized["tags"] = tags
    exclude = _optional_string_list_field(data, "exclude_agent_ids")
    if exclude is not _MISSING:
        normalized["exclude_agent_ids"] = exclude
    return normalized


def validated_routed_task_request(request: dict[str, Any]) -> dict[str, Any]:
    data = _require_mapping(request, "create_routed_task payload")
    _reject_unknown_fields(
        data,
        allowed_fields={
            "routed_task_id",
            "parent_conversation_id",
            "origin_agent_id",
            "target_agent_id",
            "title",
            "instructions",
            "context",
            "constraints",
            "requested_capabilities",
            "priority",
            "created_at",
        },
        field_name="create_routed_task payload",
    )
    normalized: dict[str, Any] = {}
    for field_name in (
        "routed_task_id",
        "parent_conversation_id",
        "origin_agent_id",
        "target_agent_id",
        "title",
        "instructions",
        "created_at",
    ):
        normalized[field_name] = _required_text(data.get(field_name), field_name)
    for field_name in ("priority",):
        field_value = _optional_text_field(data, field_name)
        if field_value is not _MISSING:
            normalized[field_name] = field_value
    requested_capabilities = _optional_string_list_field(data, "requested_capabilities")
    if requested_capabilities is not _MISSING:
        normalized["requested_capabilities"] = requested_capabilities
    for field_name in ("context", "constraints"):
        field_value = _optional_dict_field(data, field_name)
        if field_value is not _MISSING:
            normalized[field_name] = field_value
    return normalized


def validated_ack_request(*, delivery_ids: Any, classification: Any) -> tuple[list[str], str]:
    if isinstance(delivery_ids, str) or not isinstance(delivery_ids, list):
        raise ValueError("delivery_ids must be a list")
    ids = [_required_text(item, "delivery_ids[]") for item in delivery_ids]
    normalized_classification = _required_text(classification, "classification").lower()
    if normalized_classification not in VALID_ACK_CLASSIFICATIONS:
        raise ValueError(
            f"classification must be one of: {', '.join(VALID_ACK_CLASSIFICATIONS)}"
        )
    return ids, normalized_classification


def validated_routed_task_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = _require_mapping(payload, "routed_task_status payload")
    _reject_unknown_fields(
        data,
        allowed_fields={"status", "transition_id", "summary", "timeline_events", "progress", "updated_at"},
        field_name="routed_task_status payload",
    )
    normalized = {
        "status": _required_text(data.get("status"), "status"),
        "transition_id": _required_text(data.get("transition_id"), "transition_id"),
        "summary": str(data.get("summary", "") or ""),
        "timeline_events": [],
    }
    progress = data.get("progress")
    if progress not in (None, ""):
        try:
            normalized["progress"] = int(progress)
        except (TypeError, ValueError) as exc:
            raise ValueError("progress requires an integer value") from exc
    updated_at = _optional_text_field(data, "updated_at")
    if updated_at is not _MISSING:
        normalized["updated_at"] = updated_at
    if "timeline_events" in data:
        normalized["timeline_events"] = validated_timeline_events(
            data.get("timeline_events"),
            field_name="timeline_events",
        )
    return normalized


def validated_routed_task_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = _require_mapping(payload, "routed_task_result payload")
    _reject_unknown_fields(
        data,
        allowed_fields={
            "status",
            "transition_id",
            "summary",
            "full_text",
            "artifacts",
            "follow_up_questions",
            "completed_at",
        },
        field_name="routed_task_result payload",
    )
    normalized = {
        "status": _required_text(data.get("status"), "status"),
        "transition_id": _required_text(data.get("transition_id"), "transition_id"),
        "summary": str(data.get("summary", "") or ""),
        "full_text": str(data.get("full_text", "") or ""),
    }
    artifacts = data.get("artifacts", [])
    if artifacts in (None, ""):
        artifacts = []
    if isinstance(artifacts, str) or not isinstance(artifacts, (list, tuple)):
        raise ValueError("artifacts must be a list")
    normalized["artifacts"] = list(artifacts)
    follow_up_questions = data.get("follow_up_questions", [])
    if follow_up_questions in (None, ""):
        follow_up_questions = []
    if isinstance(follow_up_questions, str) or not isinstance(follow_up_questions, (list, tuple)):
        raise ValueError("follow_up_questions must be a list")
    normalized["follow_up_questions"] = [
        str(item)
        for item in follow_up_questions
    ]
    completed_at = _optional_text_field(data, "completed_at")
    if completed_at is not _MISSING:
        normalized["completed_at"] = completed_at
    return normalized


def validated_conversation_message_text(text: Any) -> str:
    value = str(text or "")
    if not value.strip():
        raise ValueError("message text requires non-empty text")
    return value


def validated_conversation_action(payload: Any) -> CoordinationActionEnvelope:
    try:
        envelope = CoordinationActionEnvelope.model_validate(payload)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return envelope


def validated_action_payload(envelope: CoordinationActionEnvelope) -> Any:
    payload = dict(envelope.payload)
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


def decode_json_field(value: Any, default: Any) -> Any:
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


def effective_connectivity_state(connectivity_state: str, last_heartbeat_at: str) -> str:
    """Return offline when the last heartbeat is older than the offline threshold."""
    effective_state = connectivity_state
    if not last_heartbeat_at:
        return effective_state
    try:
        heartbeat_dt = datetime.fromisoformat(last_heartbeat_at)
        if heartbeat_dt.tzinfo is None:
            heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - heartbeat_dt > timedelta(seconds=_OFFLINE_AFTER_SECONDS):
            return "offline"
    except ValueError:
        pass
    return effective_state


def registry_scope_for_agent_row(agent_row: Any) -> str:
    """Return the stored registry scope for an authenticated agent row."""
    try:
        scope = agent_row["registry_scope"]
    except Exception as exc:
        raise PermissionError("Authenticated agent row missing registry_scope") from exc
    try:
        return validated_registry_scope(scope)
    except ValueError as exc:
        raise PermissionError("Authenticated agent row has invalid registry_scope") from exc


def require_registry_scope(agent_row: Any, required_scopes: set[str]) -> str:
    """Validate an agent row against the required registry scopes."""
    scope = registry_scope_for_agent_row(agent_row)
    if scope not in required_scopes:
        raise RegistryScopeError(scope, required_scopes)
    return scope


def delivery_kinds_for_registry_scope(registry_scope: str) -> tuple[str, ...] | None:
    """Return the delivery kinds visible to the provided registry scope."""
    scope = validated_registry_scope(registry_scope)
    if scope == "channel":
        return ("channel_input", "channel_action")
    if scope == "coordination":
        return ("routed_task", "routed_result")
    return None


def runtime_health_summary(value: Any) -> dict[str, Any]:
    """Return the canonical mirrored health summary, or an empty dict."""
    report = report_from_dict(decode_json_field(value, {}))
    if report is None:
        return {}
    return asdict(report.summary)


def runtime_health_generated_at(value: Any) -> str:
    """Return the mirrored health timestamp, or empty string when absent."""
    report = report_from_dict(decode_json_field(value, {}))
    if report is None:
        return ""
    return report.generated_at


def runtime_health_detail(value: Any, workers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a UI-ready mirrored health detail payload."""
    report = report_from_dict(decode_json_field(value, {}))
    if report is None:
        return None
    return {
        "report": report_to_dict(report),
        "workers": workers,
        "last_mirrored_at": report.generated_at,
    }


def routed_task_created_event(request: dict[str, Any]) -> dict[str, Any]:
    created_at = str(request.get("created_at") or utcnow_iso())
    routed_task_id = str(request["routed_task_id"])
    title = str(request.get("title") or routed_task_id)
    return {
        "event_id": f"routed-task:{routed_task_id}:queued:{created_at}",
        "conversation_id": str(request["parent_conversation_id"]),
        "kind": "task.status",
        "content": title,
        "metadata": {"routed_task_id": routed_task_id, "status": "queued"},
        "created_at": created_at,
    }


def routed_task_progress_event(
    *,
    routed_task_id: str,
    parent_conversation_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    created_at = str(payload.get("updated_at") or utcnow_iso())
    metadata: dict[str, Any] = {
        "routed_task_id": routed_task_id,
        "status": str(payload["status"]),
        "transition_id": str(payload.get("transition_id", "")),
    }
    if payload.get("progress") is not None:
        metadata["progress"] = payload["progress"]
    return {
        "event_id": (
            f"routed-task:{routed_task_id}:{payload['status']}:"
            f"{created_at}"
        ),
        "conversation_id": parent_conversation_id,
        "kind": "task.status",
        "content": str(payload.get("summary") or payload["status"]),
        "metadata": metadata,
        "created_at": created_at,
    }


def routed_task_result_event(
    *,
    routed_task_id: str,
    parent_conversation_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    created_at = str(payload.get("completed_at") or utcnow_iso())
    content = str(payload.get("summary") or payload.get("full_text") or payload["status"])
    return {
        "event_id": f"routed-task:{routed_task_id}:result:{created_at}",
        "conversation_id": parent_conversation_id,
        "kind": "task.status",
        "content": content,
        "metadata": {
            "routed_task_id": routed_task_id,
            "status": str(payload["status"]),
            "transition_id": str(payload.get("transition_id", "")),
        },
        "created_at": created_at,
    }


def delegation_event(
    *,
    kind: Literal["delegation.proposed", "delegation.submitted", "delegation.completed"],
    proposal_id: str,
    conversation_id: str,
    tasks: list[dict[str, Any]],
    created_at: str,
    content: str = "",
) -> dict[str, Any]:
    return {
        "event_id": f"{kind}:{proposal_id}",
        "conversation_id": conversation_id,
        "kind": kind,
        "content": content,
        "metadata": {
            "proposal_id": proposal_id,
            "tasks": tasks,
        },
        "created_at": created_at,
    }


class AbstractRegistryStore(Protocol):
    """Backend-neutral contract for the registry service persistence layer."""

    def enroll(self, requested_card: dict[str, Any]) -> dict[str, Any]:
        """Persist a new agent card, issue an agent token, and return enrollment metadata."""

    def register(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Refresh an enrolled agent's card and runtime state, returning the stored agent view."""

    def heartbeat(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Update heartbeat state for a known agent and return the refreshed runtime view."""

    def search_agents(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Return agents matching the requested discovery constraints."""

    def resolve_agent_for_token(self, agent_token: str) -> dict[str, Any] | None:
        """Return the agent row for this token, or None if unknown. Used for auth context resolution."""

    def assert_agent_scope(self, agent_token: str, required_scopes: set[str]) -> None:
        """Validate that the authenticated agent token has one of the required scopes."""

    def create_delivery(self, *, target_agent_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue a delivery for an agent and return its durable identifiers."""

    def create_routed_task(self, request: dict[str, Any]) -> dict[str, Any]:
        """Persist a routed task and queue the corresponding agent delivery."""

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> dict[str, Any]:
        """Lease queued deliveries for an authenticated agent after the requested cursor."""

    def ack(self, agent_token: str, *, delivery_ids: list[str], classification: str) -> dict[str, Any]:
        """Acknowledge previously polled deliveries for an authenticated agent."""

    def update_routed_task_status(
        self, agent_token: str, routed_task_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Update routed-task status and any timeline mirrors published by the worker."""

    def update_routed_task_result(
        self, agent_token: str, routed_task_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist a routed-task terminal result and queue the routed_result delivery upstream."""

    def deregister(self, agent_token: str) -> dict[str, Any]:
        """Mark an agent offline while preserving its durable registry identity."""

    def get_capability_override(self, capability_name: str) -> bool | None:
        """Return True/False for an override row, or None when no override exists."""

    def set_capability_override(self, capability_name: str, enabled: bool, set_by: str = "ui") -> None:
        """Persist or update a global capability override."""

    def list_capabilities(self) -> list[dict[str, Any]]:
        """Return the declared capability universe merged with override state."""

    def list_agents(
        self,
        *,
        for_agent_id: str | None = None,
        cursor: int = 0,
        limit: int = 25,
        q: str = "",
        connectivity_state: str = "",
    ) -> list[dict[str, Any]]:
        """Return registered agents in UI-ready form with offset-based pagination."""

    def get_agent_runtime_health(self, agent_id: str) -> dict[str, Any] | None:
        """Return mirrored runtime-health detail for a registered agent."""

    def agent_exists(self, agent_id: str) -> bool:
        """Return True when the agent_id is enrolled."""

    def create_conversation(self, *, target_agent_id: str, title: str, origin_channel: str = "registry", external_conversation_ref: str = "") -> dict[str, Any]:
        """Create a new registry-originated conversation."""

    def list_conversations(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, q: str = "", status: str = "") -> list[dict[str, Any]]:
        """Return the registry conversation index with offset-based pagination."""

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Return one conversation including any linked routed tasks."""

    def search_conversations(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return conversation search hits with highlighted snippets."""

    def get_usage_summary(self, since_iso: str, until_iso: str = "") -> list[dict[str, Any]]:
        """Return reported usage timeline rows within the provided UTC ISO timestamp range."""

    def get_summary(self, *, now_iso: str) -> dict[str, Any]:
        """Return global dashboard aggregates for the registry UI."""

    def list_approvals(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25) -> list[dict[str, Any]]:
        """Return currently pending conversation approvals in UI-ready form with offset-based pagination."""

    def add_conversation_message(self, conversation_id: str, text: str) -> dict[str, Any]:
        """Queue a follow-up channel_input for an existing conversation."""

    def add_conversation_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope | dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a typed coordination action for an existing conversation."""

    def list_tasks(
        self,
        *,
        for_agent_id: str | None = None,
        parent_conversation_id: str = "",
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
    ) -> list[dict[str, Any]]:
        """Return routed tasks in UI-ready form with offset-based pagination."""

    def get_task(self, routed_task_id: str) -> dict[str, Any]:
        """Return one routed task in UI-ready form."""

    def publish_events(self, agent_token: str, conversation_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist events for a conversation. Idempotent on event_id (ON CONFLICT DO NOTHING)."""

    def list_events(
        self,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return paginated events for a conversation using latest/before/after windows."""

    def list_messages(self, conversation_id: str, *, cursor: int = 0, limit: int = 50) -> dict[str, Any]:
        """Return paginated message events (message.user, message.bot) for a conversation."""

    def list_agent_conversations(self, agent_id: str, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        """Return paginated conversations for a specific agent."""

    def get_agent_status(self, agent_id: str) -> dict[str, Any] | None:
        """Return agent status joining agents + workers + event-derived counts."""

    def get_usage(self, *, agent_id: str = "", conversation_id: str = "", since: str = "", until: str = "") -> list[dict[str, Any]]:
        """Return usage summary, filterable by agent/conversation/date range."""

    def export_conversation(self, conversation_id: str) -> str:
        """Export conversation as markdown from events."""

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
