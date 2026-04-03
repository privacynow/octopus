"""Shared service layer for runtime skill catalog access."""

from __future__ import annotations

from octopus_sdk.content_models import RuntimeSkillTrackRecord, SkillRevisionRecord
from app.content_seed import builtin_skill_tracks
from app.content_store import get_content_store
from octopus_sdk.skill_types import SkillMeta, SkillRequirement, skill_source_label
from octopus_sdk.workflows.skills import RuntimeSkillInfoRecord
from octopus_sdk.skill_packages import (
    default_skill_display_name,
    skill_has_unpublished_changes,
    skill_provider_names,
    skill_requirement_keys,
    skill_runtime_available,
)


def _requirements__track(record: RuntimeSkillTrackRecord) -> list[SkillRequirement]:
    return list(record.revision.requirements)


class SkillCatalogService:
    """Channel-neutral runtime skill catalog service."""

    def _store(self):
        return get_content_store()

    def catalog(self) -> dict[str, SkillMeta]:
        catalog: dict[str, SkillMeta] = {}
        for item in self._store().list_skill_summaries():
            catalog[item.slug] = SkillMeta(
                name=item.slug,
                display_name=item.display_name,
                description=item.description,
                is_custom=(item.source_kind == "custom"),
            )
        return catalog

    def list_tracks(self, skill_name: str) -> list[RuntimeSkillTrackRecord]:
        return self._store().list_skill_tracks(skill_name)

    def resolve_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None:
        return self._store().resolve_skill(skill_name)

    def resolve_runtime_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None:
        return self._store().resolve_runtime_skill(skill_name)

    def has_skill(self, skill_name: str) -> bool:
        return self.resolve_track(skill_name) is not None

    def has_runtime_skill(self, skill_name: str) -> bool:
        return self.resolve_runtime_track(skill_name) is not None

    def requirements(self, skill_name: str) -> list[SkillRequirement]:
        record = self.resolve_track(skill_name)
        if record is None:
            return []
        return _requirements__track(record)

    def runtime_requirements(self, skill_name: str) -> list[SkillRequirement]:
        record = self.resolve_runtime_track(skill_name)
        if record is None:
            return []
        return _requirements__track(record)

    def resolve_info(self, skill_name: str) -> RuntimeSkillInfoRecord | None:
        record = self.resolve_track(skill_name)
        if record is None:
            return None
        return RuntimeSkillInfoRecord(
            display_name=record.display_name,
            description=record.description,
            body=record.revision.instruction_body,
            source_kind=record.source_kind,
            source_label=skill_source_label(record.source_kind),
            providers=skill_provider_names(record.revision.provider_config),
            requirement_keys=skill_requirement_keys(_requirements__track(record)),
            requires_credentials=bool(record.revision.requirements),
            runtime_available=skill_runtime_available(record),
            visibility=record.visibility,
            is_mutable=record.is_mutable,
            has_unpublished_changes=skill_has_unpublished_changes(record),
            requirements=tuple(_requirements__track(record)),
            provider_config=record.revision.provider_config,
            files=record.revision.files,
        )

    def create_custom_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillTrackRecord:
        if not skill_name or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in skill_name):
            raise ValueError(f"Skill name must be lowercase letters, digits, and hyphens: {skill_name}")
        if not skill_name[0].isalpha():
            raise ValueError(f"Skill name must be lowercase letters, digits, and hyphens: {skill_name}")
        if self.has_skill(skill_name):
            raise ValueError(f"Skill '{skill_name}' already exists")
        display_name = default_skill_display_name(skill_name)
        record = RuntimeSkillTrackRecord(
            slug=skill_name,
            display_name=display_name,
            description="Custom skill",
            source_kind="custom",
            source_uri=f"custom/{skill_name}",
            owner_actor=owner_actor,
            visibility="private",
            is_mutable=True,
            revision=SkillRevisionRecord(
                instruction_body="Add your instructions here.",
                version_label="draft",
                created_by=owner_actor or "draft",
                status="draft",
            ),
        )
        self._store().upsert_skill_draft(record)
        resolved = self.resolve_track(skill_name)
        if resolved is None:
            raise RuntimeError(f"Failed to create draft skill '{skill_name}'")
        return resolved

    def filter_resolvable(self, names: list[str]) -> list[str]:
        return [name for name in names if self.has_runtime_skill(name)]

    def validate_active(self, skill_names: list[str]) -> list[str]:
        errors: list[str] = []
        for name in skill_names:
            if not self.has_skill(name):
                errors.append(f"Active skill '{name}' not found in catalog")
        return errors

    def builtin_seed_tracks(self) -> list[RuntimeSkillTrackRecord]:
        return builtin_skill_tracks()


_SERVICE = SkillCatalogService()


def get_skill_catalog_service() -> SkillCatalogService:
    return _SERVICE
