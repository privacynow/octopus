"""SDK content-store service contracts used by workflow implementations."""

from __future__ import annotations

from typing import Protocol

from octopus_sdk.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillTrackRecord,
    SkillRevisionRecord,
)


class ContentStorePort(Protocol):
    def get_provider_guidance(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None: ...

    def resolve_provider_guidance(
        self,
        provider_name: str,
        *,
        instance_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None: ...

    def list_provider_guidance_revisions(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[ProviderGuidanceRevisionRecord]: ...

    def list_provider_guidance_approvals(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[LifecycleApprovalRecord]: ...

    def get_latest_provider_guidance_approval_action(
        self,
        provider_name: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> str: ...

    def apply_provider_guidance_lifecycle_transition(
        self,
        provider_name: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: str = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None: ...

    def upsert_provider_guidance_draft(self, record: ProviderGuidanceTrackRecord) -> None: ...

    def list_skill_revisions(self, skill_name: str) -> list[SkillRevisionRecord]: ...

    def list_skill_approvals(self, skill_name: str) -> list[LifecycleApprovalRecord]: ...

    def get_latest_skill_approval_action(self, skill_name: str, revision_id: str) -> str: ...

    def apply_skill_lifecycle_transition(
        self,
        skill_name: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: str = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
    ) -> None: ...

    def upsert_skill_draft(self, record: RuntimeSkillTrackRecord) -> None: ...
