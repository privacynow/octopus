"""SDK workflow contracts for provider-guidance preview and lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from octopus_sdk.providers import CredentialEnvRecord, PreflightContext, ProviderConfigRecord, RunContext
from octopus_sdk.registry.models import DiscoveredAgentRef


class ProviderGuidanceServicePort(Protocol):
    def system_prompt(
        self,
        role: str,
        active_skills: list[str],
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> str: ...

    def effective_guidance_preview(self, provider_name: str, *, instance_key: str = "") -> str: ...

    def provider_config(
        self,
        provider_name: str,
        active_skills: list[str],
        credential_env: CredentialEnvRecord | None = None,
    ) -> ProviderConfigRecord: ...

    def capability_summary(self, provider_name: str, active_skills: list[str]) -> str: ...

    def prompt_weight(
        self,
        role: str,
        active_skills: list[str],
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> int: ...

    def estimate_prompt_size(
        self,
        role: str,
        current_skills: list[str],
        new_skill: str,
    ) -> tuple[int, bool]: ...

    def check_prompt_size_cross_chat(
        self,
        data_dir: Path,
        skill_name: str,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
    ) -> list[str]: ...

    def build_run_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str,
        credential_env: CredentialEnvRecord | None = None,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> RunContext: ...

    def build_preflight_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
    ) -> PreflightContext: ...

    def apply_compact_mode(self, system_prompt: str, compact: bool) -> str: ...

    def stage_codex_scripts(
        self,
        data_dir: Path,
        conversation_key: str,
        active_skills: list[str],
    ) -> Path | None: ...


@dataclass(frozen=True)
class ProviderGuidancePreview:
    provider: str
    effective_guidance: str
    system_prompt: str
    capability_summary: str
    provider_config: ProviderConfigRecord
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
