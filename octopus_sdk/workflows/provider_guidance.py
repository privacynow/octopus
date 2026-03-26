"""SDK workflow contracts for provider-guidance preview and lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderGuidancePreview:
    provider: str
    effective_guidance: str
    system_prompt: str
    capability_summary: str
    provider_config: dict[str, Any]
    prompt_weight: int


class ProviderGuidancePort(Protocol):
    def preview(
        self,
        provider_name: str,
        *,
        role: str,
        active_skills: list[str],
        compact_mode: bool,
    ) -> ProviderGuidancePreview: ...


@dataclass(frozen=True)
class ProviderGuidanceLifecycleRevision:
    revision_id: str
    status: str
    created_by: str
    created_at: str
    is_published: bool


@dataclass(frozen=True)
class ProviderGuidanceLifecycleApproval:
    revision_id: str
    action: str
    actor: str
    note: str
    created_at: str


@dataclass(frozen=True)
class ProviderGuidanceLifecycleDetail:
    provider: str
    scope_kind: str
    scope_key: str
    body: str
    lifecycle_status: str
    active_revision_id: str
    published_revision_id: str
    runtime_available: bool
    revisions: tuple[ProviderGuidanceLifecycleRevision, ...]
    approvals: tuple[ProviderGuidanceLifecycleApproval, ...]


@dataclass(frozen=True)
class ProviderGuidanceLifecycleMutation:
    status: str
    ok: bool
    message: str
    detail: ProviderGuidanceLifecycleDetail | None = None


class ProviderGuidanceManagementPort(Protocol):
    def detail(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleDetail | None: ...

    def edit_draft(
        self,
        provider_name: str,
        *,
        actor_key: str,
        body: str,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation: ...

    def submit(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation: ...

    def approve(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation: ...

    def reject(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation: ...

    def publish(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation: ...

    def archive(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation: ...
