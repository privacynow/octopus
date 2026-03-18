"""Backend-neutral content-store contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
    SkillRevisionRecord,
)


class AbstractContentStore(ABC):
    @abstractmethod
    def replace_skill_track(self, record: RuntimeSkillTrackRecord) -> None:
        """Upsert one skill track and set its active revision."""

    @abstractmethod
    def delete_skill_track(
        self,
        slug: str,
        *,
        source_kind: str,
        source_uri: str = "",
        owner_actor: str = "",
    ) -> bool:
        """Delete one exact skill track. Returns True when a row was removed."""

    @abstractmethod
    def list_skill_summaries(self) -> list[RuntimeSkillSummary]:
        """Return effective runtime skill summaries after precedence resolution."""

    @abstractmethod
    def resolve_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        """Return the effective runtime skill track for a slug."""

    @abstractmethod
    def list_skill_tracks(self, slug: str) -> list[RuntimeSkillTrackRecord]:
        """Return all tracks for a slug, ordered by precedence."""

    @abstractmethod
    def list_runtime_skill_summaries(self) -> list[RuntimeSkillSummary]:
        """Return runtime-eligible skill summaries after precedence resolution."""

    @abstractmethod
    def resolve_runtime_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        """Return the runtime-eligible track for a slug using published revisions only."""

    @abstractmethod
    def upsert_skill_draft(self, record: RuntimeSkillTrackRecord) -> None:
        """Upsert one skill track and set its active revision without publishing it."""

    @abstractmethod
    def list_skill_revisions(self, slug: str) -> list[SkillRevisionRecord]:
        """Return lifecycle revisions for the mutable custom skill track, newest first."""

    @abstractmethod
    def list_skill_approvals(self, slug: str) -> list[LifecycleApprovalRecord]:
        """Return approval records for the mutable custom skill track, newest first."""

    @abstractmethod
    def append_skill_approval(
        self,
        slug: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
    ) -> LifecycleApprovalRecord:
        """Append one approval-history event for the mutable custom skill track."""

    @abstractmethod
    def set_skill_revision_status(self, slug: str, revision_id: str, status: str) -> None:
        """Update lifecycle status for one revision on the mutable custom skill track."""

    @abstractmethod
    def set_published_skill_revision(self, slug: str, revision_id: str) -> None:
        """Point the mutable custom skill track at one published revision for runtime use."""

    @abstractmethod
    def clear_published_skill_revision(self, slug: str) -> None:
        """Remove the runtime published pointer for the mutable custom skill track."""

    @abstractmethod
    def replace_provider_guidance(self, record: ProviderGuidanceTrackRecord) -> None:
        """Upsert one provider-guidance track and set its active revision."""

    @abstractmethod
    def get_provider_guidance(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        """Return one provider-guidance track for the requested scope."""

    @abstractmethod
    def resolve_provider_guidance(
        self,
        provider: str,
        *,
        instance_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        """Resolve the runtime published guidance, instance override first then system default."""

    @abstractmethod
    def upsert_provider_guidance_draft(self, record: ProviderGuidanceTrackRecord) -> None:
        """Upsert one provider-guidance track and set its active revision without publishing it."""

    @abstractmethod
    def list_provider_guidance_revisions(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[ProviderGuidanceRevisionRecord]:
        """Return lifecycle revisions for one provider-guidance track, newest first."""

    @abstractmethod
    def list_provider_guidance_approvals(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[LifecycleApprovalRecord]:
        """Return approval records for one provider-guidance track, newest first."""

    @abstractmethod
    def append_provider_guidance_approval(
        self,
        provider: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> LifecycleApprovalRecord:
        """Append one approval-history event for one provider-guidance track."""

    @abstractmethod
    def set_provider_guidance_revision_status(
        self,
        provider: str,
        revision_id: str,
        status: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        """Update lifecycle status for one provider-guidance revision."""

    @abstractmethod
    def set_published_provider_guidance_revision(
        self,
        provider: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        """Point one provider-guidance track at a published revision for runtime use."""

    @abstractmethod
    def clear_published_provider_guidance_revision(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        """Remove the runtime published pointer for one provider-guidance track."""
