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
    origin_surface: str
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(frozen=True)
class SurfaceBinding:
    surface: str
    external_id: str
    conversation_id: str


@dataclass(frozen=True)
class SurfaceEvent:
    event_id: str
    surface: str
    conversation_id: str
    actor_id: str
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str
    conversation_id: str
    kind: str
    title: str
    body: str = ""
    status: str = ""
    progress: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(frozen=True)
class AgentCard:
    agent_id: str = ""
    display_name: str = ""
    slug: str = ""
    role: str = ""
    skills: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    description: str = ""
    provider: str = ""
    mode: str = "standalone"
    connectivity_state: str = "standalone"
    current_capacity: int = 0
    max_capacity: int = 1
    surface_capabilities: tuple[str, ...] = ("telegram",)
    version: str = "dev"


@dataclass(frozen=True)
class AgentDiscoveryQuery:
    role: str = ""
    skills: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    free_text: str = ""
    exclude_agent_ids: tuple[str, ...] = ()
    required_state: str = "connected"


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
    timeline_events: tuple[TimelineEvent, ...] = ()
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
