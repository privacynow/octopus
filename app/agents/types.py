"""Transport-neutral agent, conversation, and routed-work types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_wire(value: Any) -> Any:
    """Recursively convert dataclasses to JSON-safe Python structures."""
    if is_dataclass(value):
        return {k: to_wire(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): to_wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_wire(v) for v in value]
    return value


@dataclass(frozen=True)
class ConversationRef:
    conversation_id: str
    owner_agent_id: str
    origin_channel: str
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(frozen=True)
class ChannelBinding:
    channel: str
    external_id: str
    conversation_id: str


@dataclass(frozen=True)
class ChannelEvent:
    event_id: str
    channel: str
    conversation_id: str
    actor_id: str
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(frozen=True)
class AgentCard:
    agent_id: str = ""
    display_name: str = ""
    slug: str = ""
    role: str = ""
    registry_scope: str = "full"
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    description: str = ""
    provider: str = ""
    mode: str = "standalone"
    connectivity_state: str = "standalone"
    current_capacity: int = 0
    max_capacity: int = 1
    channel_capabilities: tuple[str, ...] = ("telegram",)
    version: str = "dev"


@dataclass(frozen=True)
class RegistryConnectionConfig:
    registry_id: str
    url: str
    enroll_token: str
    registry_scope: str
    poll_interval_seconds: float = 5.0


@dataclass
class RegistryConnectionState:
    registry_id: str
    registry_scope: str = "full"
    agent_id: str = ""
    agent_token: str = ""
    poll_cursor: str = "0"
    registered_slug: str = ""
    last_successful_contact_at: str = ""
    connectivity_state: str = "standalone"
    last_error: str = ""
    last_error_detail: str = ""


@dataclass(frozen=True)
class AgentDiscoveryQuery:
    role: str = ""
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    free_text: str = ""
    exclude_agent_ids: tuple[str, ...] = ()
    required_state: str = "connected"


@dataclass(frozen=True)
class DiscoveredAgentRef:
    authority_ref: str
    agent_id: str
    display_name: str = ""
    slug: str = ""
    role: str = ""
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    description: str = ""
    connectivity_state: str = ""
    current_capacity: int = 0
    max_capacity: int = 1


@dataclass(frozen=True)
class RoutedTaskRequest:
    routed_task_id: str
    parent_conversation_id: str
    origin_agent_id: str
    target_agent_id: str
    title: str
    instructions: str
    context: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    requested_capabilities: tuple[str, ...] = ()
    priority: str = "normal"
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(frozen=True)
class RoutedTaskUpdate:
    routed_task_id: str
    status: str
    summary: str = ""
    timeline_events: tuple[dict[str, Any], ...] = ()
    progress: int | None = None
    updated_at: str = field(default_factory=utcnow_iso)


@dataclass(frozen=True)
class RoutedTaskResult:
    routed_task_id: str
    status: str
    summary: str = ""
    full_text: str = ""
    artifacts: tuple[dict[str, Any], ...] = ()
    follow_up_questions: tuple[str, ...] = ()
    completed_at: str = field(default_factory=utcnow_iso)
