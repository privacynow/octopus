"""Abstract registry store contract and shared pure helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

_OFFLINE_AFTER_SECONDS = 60


class SkillDisabledError(RuntimeError):
    """Raised when routing requests a skill that has been globally disabled."""


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

    def get_skill_override(self, skill_name: str) -> bool | None:
        """Return True/False for an override row, or None when no override exists."""

    def set_skill_override(self, skill_name: str, enabled: bool, set_by: str = "ui") -> None:
        """Persist or update a global skill override."""

    def list_skills(self) -> list[dict[str, Any]]:
        """Return the declared skill universe merged with override state."""

    def list_agents(self) -> list[dict[str, Any]]:
        """Return all registered agents in UI-ready form."""

    def ui_bootstrap(self) -> dict[str, Any]:
        """Return the aggregated UI bootstrap payload."""

    def create_conversation(self, *, target_agent_id: str, title: str, message_text: str) -> dict[str, Any]:
        """Create a new registry-originated conversation and queue the first surface_input."""

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
        """Queue a follow-up surface_input for an existing conversation."""

    def add_conversation_action(
        self, conversation_id: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Queue a surface_action for an existing conversation."""

    def cancel_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Queue a cancel control delivery and mirror it to the registry timeline."""

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return routed tasks in UI-ready form."""
