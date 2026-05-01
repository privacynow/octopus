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

from collections.abc import Callable, Iterator, Mapping, Sequence
import dataclasses
import time
from dataclasses import dataclass, field

from octopus_sdk.providers import (
    DenialRecord,
    JsonValue,
    ProviderStateRecord,
    coerce_denial_records,
    coerce_provider_state,
)
from octopus_sdk.runtime.skills import SkillFollowUpSubject
from octopus_sdk.skill_types import SkillRequirement
from octopus_sdk.time_utils import utc_now_iso


@dataclass(frozen=True)
class PendingApprovalAttachmentRecord(Mapping[str, object]):
    path: str
    original_name: str
    is_image: bool
    mime_type: str | None = None

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def get(self, key: str, default: object = None) -> object:
        return self.to_dict().get(key, default)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "original_name": self.original_name,
            "is_image": self.is_image,
            "mime_type": self.mime_type,
        }


def coerce_pending_approval_attachments(
    values: list[PendingApprovalAttachmentRecord] | list[Mapping[str, object]] | None,
) -> list[PendingApprovalAttachmentRecord]:
    if not values:
        return []
    records: list[PendingApprovalAttachmentRecord] = []
    for value in values:
        if isinstance(value, PendingApprovalAttachmentRecord):
            records.append(value)
            continue
        records.append(
            PendingApprovalAttachmentRecord(
                path=str(value.get("path", "") or ""),
                original_name=str(value.get("original_name", "") or ""),
                is_image=bool(value.get("is_image", False)),
                mime_type=(
                    None
                    if value.get("mime_type") in (None, "")
                    else str(value.get("mime_type"))
                ),
            )
        )
    return records


def _coerce_skill_requirement(value: SkillRequirement | Mapping[str, object]) -> SkillRequirement:
    if isinstance(value, SkillRequirement):
        return value
    return SkillRequirement(
        key=str(value.get("key", "") or ""),
        prompt=str(value.get("prompt", "") or ""),
        help_url=(
            None
            if value.get("help_url") in (None, "")
            else str(value.get("help_url"))
        ),
        validate=(
            None
            if value.get("validate") is None
            else value.get("validate")
        ),
    )


def coerce_skill_requirements(
    values: list[SkillRequirement] | list[Mapping[str, object]] | None,
) -> list[SkillRequirement]:
    if not values:
        return []
    return [_coerce_skill_requirement(value) for value in values]

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
    actor_key: str
    prompt: str
    image_paths: list[str]
    attachment_dicts: list[PendingApprovalAttachmentRecord]
    context_hash: str
    callback_token: str = ""
    trust_tier: str = "trusted"
    created_at: float | str = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.attachment_dicts = coerce_pending_approval_attachments(self.attachment_dicts)


@dataclass
class PendingRetry:
    """A denial-retry request waiting for user grant."""
    actor_key: str
    prompt: str
    image_paths: list[str]
    context_hash: str
    denials: list[DenialRecord]
    callback_token: str = ""
    trust_tier: str = "trusted"
    created_at: float | str = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.denials = coerce_denial_records(self.denials)


@dataclass
class AwaitingSkillSetup:
    """Conversational credential collection state."""
    actor_key: str
    skill: str
    remaining: list[SkillRequirement]
    started_at: float | str = 0.0

    def __post_init__(self) -> None:
        self.remaining = coerce_skill_requirements(self.remaining)


@dataclass
class DelegatedTask:
    """One child task tracked by a parent-side delegation plan."""
    routed_task_id: str
    authority_ref: str = ""
    title: str = ""
    target_agent_id: str = ""
    instructions: str = ""
    status: str = "proposed"  # valid values: proposed, queued, leased, running, submitted, completed, failed
    summary: str = ""
    full_text: str = ""
    follow_up_questions: list[str] = field(default_factory=list)
    completed_at: str = ""
    submitted_at: float | str = 0.0


@dataclass
class PendingDelegation:
    """Parent-side delegated work waiting for child results."""
    conversation_ref: str
    origin_conversation_key: str = ""
    actor_key: str = ""
    proposal_id: str = ""
    title: str = ""
    resume_instruction: str = ""
    tasks: list[DelegatedTask] = field(default_factory=list)
    status: str = ""  # valid values: "", proposed, submitted, completed, partial_failed, cancelled
    created_at: float | str = field(default_factory=time.time)


@dataclass
class ProtocolRunWatch:
    """Durable transport-facing subscription for protocol run updates."""

    run_id: str
    protocol_id: str = ""
    protocol_slug: str = ""
    last_notified_version: int = 0
    last_notified_status: str = ""
    last_notified_stage_key: str = ""
    last_notified_at: str = ""
    registry_url: str = ""


def coerce_protocol_run_watches(
    values: list[ProtocolRunWatch] | list[Mapping[str, object]] | None,
) -> list[ProtocolRunWatch]:
    if not values:
        return []
    watches: list[ProtocolRunWatch] = []
    for value in values:
        if isinstance(value, ProtocolRunWatch):
            watches.append(value)
            continue
        watches.append(
            ProtocolRunWatch(
                run_id=str(value.get("run_id", "") or ""),
                protocol_id=str(value.get("protocol_id", "") or ""),
                protocol_slug=str(value.get("protocol_slug", "") or ""),
                last_notified_version=int(value.get("last_notified_version", 0) or 0),
                last_notified_status=str(value.get("last_notified_status", "") or ""),
                last_notified_stage_key=str(value.get("last_notified_stage_key", "") or ""),
                last_notified_at=str(value.get("last_notified_at", "") or ""),
                registry_url=str(value.get("registry_url", "") or ""),
            )
        )
    return [item for item in watches if item.run_id]


@dataclass
class SessionState:
    """Typed representation of a chat session.

    Constructed from the raw dict at the storage boundary (_load),
    converted back to a dict at the storage boundary (_save).
    All runtime paths operate on this object.
    """
    provider: str
    provider_state: ProviderStateRecord
    approval_mode: str
    approval_mode_explicit: bool = False
    active_skills: list[str] = field(default_factory=list)
    role: str = ""
    pending_approval: PendingApproval | None = None
    pending_retry: PendingRetry | None = None
    awaiting_skill_setup: AwaitingSkillSetup | None = None
    pending_delegation: PendingDelegation | None = None
    protocol_run_watches: list[ProtocolRunWatch] = field(default_factory=list)
    last_auto_protocol_session_id: str = ""
    compact_mode: bool | None = None  # None = use config default
    project_id: str = ""
    file_policy: str = ""  # "inspect", "edit", or "" (use config default)
    model_profile: str = ""  # "fast", "balanced", "best", or "" (use config default)
    created_at: str = ""
    updated_at: str = ""
    last_skill_subject: SkillFollowUpSubject | None = None

    def __post_init__(self) -> None:
        self.provider_state = coerce_provider_state(self.provider_state)
        self.protocol_run_watches = coerce_protocol_run_watches(self.protocol_run_watches)

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

def session_to_dict(s: SessionState) -> dict[str, object]:
    """Convert a SessionState to a storage-ready dict via dataclasses.asdict()."""
    data = dataclasses.asdict(s)
    provider_state = data.get("provider_state")
    if isinstance(provider_state, dict) and "values" in provider_state:
        data["provider_state"] = provider_state.get("values", {})
    pending_retry = data.get("pending_retry")
    if isinstance(pending_retry, dict):
        denials = pending_retry.get("denials")
        if isinstance(denials, list):
            pending_retry["denials"] = [
                item.get("values", item)
                if isinstance(item, dict)
                else item
                for item in denials
            ]
    return data


def session_from_dict(d: Mapping[str, object]) -> SessionState:
    """Reconstruct a SessionState from a storage dict."""
    def _make_optional(cls, raw):
        if raw is None or not isinstance(raw, dict):
            return None
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in valid_keys}
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
        provider_state=coerce_provider_state(d.get("provider_state", {})),
        approval_mode=d.get("approval_mode", "off"),
        approval_mode_explicit=d.get("approval_mode_explicit", False),
        active_skills=d.get("active_skills", []),
        role=d.get("role", ""),
        pending_approval=_make_optional(PendingApproval, pending_approval_raw),
        pending_retry=_make_optional(PendingRetry, pending_retry_raw),
        awaiting_skill_setup=_make_optional(AwaitingSkillSetup, d.get("awaiting_skill_setup")),
        pending_delegation=_make_pending_delegation(pending_delegation_raw),
        protocol_run_watches=coerce_protocol_run_watches(d.get("protocol_run_watches")),
        last_auto_protocol_session_id=str(d.get("last_auto_protocol_session_id", "") or ""),
        compact_mode=d.get("compact_mode"),
        project_id=d.get("project_id", ""),
        file_policy=d.get("file_policy") or "",
        model_profile=d.get("model_profile") or "",
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        last_skill_subject=_make_optional(SkillFollowUpSubject, d.get("last_skill_subject")),
    )


ProviderStateInput = ProviderStateRecord | Mapping[str, JsonValue]
ProviderStateFactory = Callable[[str], ProviderStateInput]


def trusted_conversation_bypasses_approvals(
    session: SessionState,
    *,
    trust_tier: str,
) -> bool:
    return trust_tier != "public" and session.approval_mode != "on"


def single_project_binding(projects: Sequence[ProjectBinding]) -> ProjectBinding | None:
    if len(projects) != 1:
        return None
    project = projects[0]
    if not project.name:
        return None
    return project


def normalize_single_project_session(
    session: SessionState,
    *,
    projects: Sequence[ProjectBinding],
    provider_state_factory: ProviderStateFactory | None = None,
    conversation_key: str = "",
) -> bool:
    project = single_project_binding(projects)
    if project is None or session.project_id == project.name:
        return False
    session.project_id = project.name
    session.clear_pending()
    if provider_state_factory is not None:
        session.provider_state = coerce_provider_state(provider_state_factory(conversation_key))
    return True


def default_session(
    provider_name: str,
    provider_state: ProviderStateInput | ProviderStateFactory,
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, object]:
    from datetime import datetime, timezone

    if callable(provider_state):
        provider_state = provider_state("")
    state = coerce_provider_state(provider_state)
    now = utc_now_iso()
    return {
        "provider": provider_name,
        "provider_state": state.to_dict(),
        "approval_mode": approval_mode,
        "active_skills": list(default_skills),
        "role": role,
        "pending_approval": None,
        "pending_retry": None,
        "awaiting_skill_setup": None,
        "pending_delegation": None,
        "protocol_run_watches": [],
        "last_auto_protocol_session_id": "",
        "created_at": now,
        "updated_at": now,
        "last_skill_subject": None,
    }
