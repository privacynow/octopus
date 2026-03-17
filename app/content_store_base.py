"""Backend-neutral content-store contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.content_models import (
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
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
        """Resolve instance override first, then system default."""
