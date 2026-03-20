"""Abstract registry store contract and shared pure helpers."""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.runtime_health import report_from_dict, report_to_dict

_OFFLINE_AFTER_SECONDS = 60


def hash_agent_token(token: str) -> str:
    """Return the stable server-side digest used for agent bearer-token lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
    """Map a timeline event kind to the conversation status it implies."""
    if kind in {"started", "progress"}:
        if current_status == "cancelling":
            return "cancelling"
        return "running"
    if kind == "completed":
        return "completed"
    if kind == "failed":
        return "failed"
    if kind == "control":
        return "cancelling"
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
    except Exception:
        scope = "full"
    return str(scope or "full")


def require_registry_scope(agent_row: Any, required_scopes: set[str]) -> str:
    """Validate an agent row against the required registry scopes."""
    scope = registry_scope_for_agent_row(agent_row)
    if scope not in required_scopes:
        raise RegistryScopeError(scope, required_scopes)
    return scope


def delivery_kinds_for_registry_scope(registry_scope: str) -> tuple[str, ...] | None:
    """Return the delivery kinds visible to the provided registry scope."""
    scope = (registry_scope or "full").strip().lower() or "full"
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


class AbstractRegistryStore(Protocol):
    """Backend-neutral contract for the registry service persistence layer."""

    def enroll(self, requested_card: dict[str, Any]) -> dict[str, Any]:
        """Persist a new agent card, issue an agent token, and return enrollment metadata."""

    def register(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Refresh an enrolled agent's card and runtime state, returning the stored agent view."""

    def heartbeat(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Update heartbeat state for a known agent and return the refreshed runtime view."""

    def publish_timeline(self, agent_token: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist timeline events owned by the authenticated agent and update conversation state."""

    def bind_conversation(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Bind or refresh a conversation record for the authenticated agent."""

    def search_agents(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Return agents matching the requested discovery constraints."""

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

    def list_agents(self) -> list[dict[str, Any]]:
        """Return all registered agents in UI-ready form."""

    def ui_bootstrap(self) -> dict[str, Any]:
        """Return the aggregated UI bootstrap payload."""

    def get_agent_runtime_health(self, agent_id: str) -> dict[str, Any] | None:
        """Return mirrored runtime-health detail for a registered agent."""

    def create_conversation(self, *, target_agent_id: str, title: str, message_text: str) -> dict[str, Any]:
        """Create a new registry-originated conversation and queue the first channel_input."""

    def list_conversations(self) -> list[dict[str, Any]]:
        """Return the registry conversation index."""

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Return one conversation including any linked routed tasks."""

    def get_conversation_timeline(self, conversation_id: str) -> list[dict[str, Any]]:
        """Return timeline events for a conversation in chronological order."""

    def search_conversations(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return conversation search hits with highlighted snippets."""

    def get_usage_summary(self, since_iso: str) -> list[dict[str, Any]]:
        """Return reported usage timeline rows since the provided UTC ISO timestamp."""

    def add_conversation_message(self, conversation_id: str, text: str) -> dict[str, Any]:
        """Queue a follow-up channel_input for an existing conversation."""

    def add_conversation_action(
        self, conversation_id: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Queue a channel_action for an existing conversation."""

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return routed tasks in UI-ready form."""
