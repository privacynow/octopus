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


@dataclass
class ProjectBinding:
    """Resolved project configuration from BotConfig.projects."""
    name: str
    root_dir: str
    extra_dirs: tuple[str, ...] = ()


@dataclass
class PendingApproval:
    """A preflight approval request waiting for /approve or /reject."""
    request_user_id: int
    prompt: str
    image_paths: list[str]
    attachment_dicts: list[dict[str, Any]]
    context_hash: str
    created_at: float = field(default_factory=time.time)


@dataclass
class PendingRetry:
    """A denial-retry request waiting for user grant."""
    request_user_id: int
    prompt: str
    image_paths: list[str]
    context_hash: str
    denials: list[dict[str, Any]]
    created_at: float = field(default_factory=time.time)


@dataclass
class AwaitingSkillSetup:
    """Conversational credential collection state."""
    user_id: int
    skill: str
    remaining: list[dict[str, Any]]  # [{key, prompt, help_url, validate}, ...]
    started_at: float = 0.0


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
    compact_mode: bool | None = None  # None = use config default
    project_id: str = ""
    file_policy: str = ""  # "inspect", "edit", or "" (use config default)
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
        try:
            return cls(**filtered)
        except TypeError:
            return None

    pending_approval_raw = d.get("pending_approval")
    pending_retry_raw = d.get("pending_retry")

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
        compact_mode=d.get("compact_mode"),
        project_id=d.get("project_id", ""),
        file_policy=d.get("file_policy") or "",
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )
