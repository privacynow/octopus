"""Typed session state models.

Runtime logic uses these typed objects exclusively.  Serialization to/from
dicts happens only at the storage boundary (storage.py).

Design rules:
- No raw dict mutation in core orchestration paths.
- PendingApproval and PendingRetry are separate types (not one bag).
- ProjectBinding resolves once from config; downstream code never re-parses.
- Serialization uses dataclasses.asdict(); no hand-rolled field copying.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Any

from app.identity import parse_actor_key


@dataclass
class ProjectBinding:
    """Resolved project configuration from BotConfig.projects.

    Serves as both the config record (BotConfig.projects) and the
    runtime-resolved binding (ResolvedExecutionContext.project_binding).

    file_policy and model_profile are per-project inherited defaults:
    empty string means "inherit from session or global config."
    """
    name: str
    root_dir: str
    extra_dirs: tuple[str, ...] = ()
    file_policy: str = ""    # "" = inherit, "inspect" or "edit" = project default
    model_profile: str = ""  # "" = inherit, profile name = project default


@dataclass
class PendingApproval:
    """A preflight approval request waiting for /approve or /reject."""
    request_user_id: str
    prompt: str
    image_paths: list[str]
    attachment_dicts: list[dict[str, Any]]
    context_hash: str
    trust_tier: str = "trusted"
    created_at: float | str = field(default_factory=time.time)


@dataclass
class PendingRetry:
    """A denial-retry request waiting for user grant."""
    request_user_id: str
    prompt: str
    image_paths: list[str]
    context_hash: str
    denials: list[dict[str, Any]]
    trust_tier: str = "trusted"
    created_at: float | str = field(default_factory=time.time)


@dataclass
class AwaitingSkillSetup:
    """Conversational credential collection state."""
    user_id: str
    skill: str
    remaining: list[dict[str, Any]]  # [{key, prompt, help_url, validate}, ...]
    started_at: float | str = 0.0


@dataclass
class DelegatedTask:
    """One child task tracked by a parent-side delegation plan."""
    routed_task_id: str
    title: str = ""
    target_agent_id: str = ""
    instructions: str = ""
    status: str = "proposed"  # valid values: proposed, submitted, completed, failed
    summary: str = ""
    full_text: str = ""
    follow_up_questions: list[str] = field(default_factory=list)
    completed_at: str = ""


@dataclass
class PendingDelegation:
    """Parent-side delegated work waiting for child results."""
    conversation_ref: str
    title: str = ""
    resume_instruction: str = ""
    tasks: list[DelegatedTask] = field(default_factory=list)
    status: str = ""  # valid values: "", submitted, completed, partial_failed
    created_at: float | str = field(default_factory=time.time)


@dataclass
class SessionState:
    """Typed representation of a chat session.

    Constructed from the raw dict at the storage boundary (_load),
    converted back to a dict at the storage boundary (_save).
    All runtime paths operate on this object.
    """
    provider: str
    provider_state: dict[str, Any]
    approval_mode: str
    approval_mode_explicit: bool = False
    active_skills: list[str] = field(default_factory=list)
    role: str = ""
    pending_approval: PendingApproval | None = None
    pending_retry: PendingRetry | None = None
    awaiting_skill_setup: AwaitingSkillSetup | None = None
    pending_delegation: PendingDelegation | None = None
    compact_mode: bool | None = None  # None = use config default
    project_id: str = ""
    file_policy: str = ""  # "inspect", "edit", or "" (use config default)
    model_profile: str = ""  # "fast", "balanced", "best", or "" (use config default)
    created_at: str = ""
    updated_at: str = ""

    # -- Convenience accessors ------------------------------------------------

    @property
    def has_pending(self) -> bool:
        return self.pending_approval is not None or self.pending_retry is not None

    @property
    def pending_kind(self) -> str | None:
        if self.pending_approval is not None:
            return "approval"
        if self.pending_retry is not None:
            return "retry"
        return None

    def clear_pending(self) -> None:
        self.pending_approval = None
        self.pending_retry = None


# ---------------------------------------------------------------------------
# Serialization: typed ↔ dict (used only by storage.py and _load/_save)
# ---------------------------------------------------------------------------

def session_to_dict(s: SessionState) -> dict[str, Any]:
    """Convert a SessionState to a storage-ready dict via dataclasses.asdict()."""
    return dataclasses.asdict(s)


def session_from_dict(d: dict[str, Any]) -> SessionState:
    """Reconstruct a SessionState from a storage dict."""
    def _make_optional(cls, raw):
        if raw is None or not isinstance(raw, dict):
            return None
        # Filter out keys not in the dataclass to tolerate legacy extras
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in valid_keys}
        if "request_user_id" in filtered:
            filtered["request_user_id"] = parse_actor_key(filtered["request_user_id"])
        if "user_id" in filtered:
            filtered["user_id"] = parse_actor_key(filtered["user_id"])
        try:
            return cls(**filtered)
        except TypeError:
            return None

    pending_approval_raw = d.get("pending_approval")
    pending_retry_raw = d.get("pending_retry")
    pending_delegation_raw = d.get("pending_delegation")

    def _make_pending_delegation(raw):
        if raw is None or not isinstance(raw, dict):
            return None
        tasks: list[DelegatedTask] = []
        for task_raw in raw.get("tasks", []):
            if not isinstance(task_raw, dict):
                continue
            valid_keys = {f.name for f in DelegatedTask.__dataclass_fields__.values()}
            filtered = {k: v for k, v in task_raw.items() if k in valid_keys}
            try:
                tasks.append(DelegatedTask(**filtered))
            except TypeError:
                continue
        valid_keys = {f.name for f in PendingDelegation.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in valid_keys and k != "tasks"}
        filtered["tasks"] = tasks
        try:
            return PendingDelegation(**filtered)
        except TypeError:
            return None

    return SessionState(
        provider=d.get("provider", ""),
        provider_state=d.get("provider_state", {}),
        approval_mode=d.get("approval_mode", "off"),
        approval_mode_explicit=d.get("approval_mode_explicit", False),
        active_skills=d.get("active_skills", []),
        role=d.get("role", ""),
        pending_approval=_make_optional(PendingApproval, pending_approval_raw),
        pending_retry=_make_optional(PendingRetry, pending_retry_raw),
        awaiting_skill_setup=_make_optional(AwaitingSkillSetup, d.get("awaiting_skill_setup")),
        pending_delegation=_make_pending_delegation(pending_delegation_raw),
        compact_mode=d.get("compact_mode"),
        project_id=d.get("project_id", ""),
        file_policy=d.get("file_policy") or "",
        model_profile=d.get("model_profile") or "",
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )
