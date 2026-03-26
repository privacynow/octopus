"""Shared service layer for runtime skill catalog access."""

from __future__ import annotations

from dataclasses import dataclass

from octopus_sdk.content_models import RuntimeSkillTrackRecord, SkillRevisionRecord
from app.content_seed import builtin_skill_tracks
from app.content_store import get_content_store
from octopus_sdk.skill_types import SkillMeta, SkillRequirement


def _requirements_from_track(record: RuntimeSkillTrackRecord) -> list[SkillRequirement]:
    requirements: list[SkillRequirement] = []
    for item in record.revision.requirements:
        key = str(item.get("key", "") or "")
        if not key:
            continue
        prompt = str(item.get("prompt", "") or "")
        help_url = item.get("help_url")
        validate = item.get("validate")
        requirements.append(
            SkillRequirement(
                key=key,
                prompt=prompt,
                help_url=str(help_url) if help_url else None,
                validate=validate if isinstance(validate, dict) else None,
            )
        )
    return requirements


@dataclass(frozen=True)
class SkillInfoRecord:
    meta: dict[str, str]
    body: str
    source: str
    providers: tuple[str, ...]
    requirement_keys: tuple[str, ...]


class SkillCatalogService:
    """Channel-neutral runtime skill catalog service."""

    _SOURCE_LABELS = {
        "builtin": "builtin",
        "imported": "imported",
        "custom": "custom",
    }

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
        return _requirements_from_track(record)

    def runtime_requirements(self, skill_name: str) -> list[SkillRequirement]:
        record = self.resolve_runtime_track(skill_name)
        if record is None:
            return []
        return _requirements_from_track(record)

    def resolve_info(self, skill_name: str) -> SkillInfoRecord | None:
        record = self.resolve_track(skill_name)
        if record is None:
            return None
        provider_names = tuple(
            provider
            for provider in ("claude", "codex")
            if isinstance(record.revision.provider_config.get(provider), dict)
        )
        return SkillInfoRecord(
            meta={
                "display_name": record.display_name,
                "description": record.description,
            },
            body=record.revision.instruction_body,
            source=self._SOURCE_LABELS.get(record.source_kind, record.source_kind),
            providers=provider_names,
            requirement_keys=tuple(item.key for item in _requirements_from_track(record)),
        )

    def create_custom_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillTrackRecord:
        if not skill_name or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in skill_name):
            raise ValueError(f"Skill name must be lowercase letters, digits, and hyphens: {skill_name}")
        if not skill_name[0].isalpha():
            raise ValueError(f"Skill name must be lowercase letters, digits, and hyphens: {skill_name}")
        if self.has_skill(skill_name):
            raise ValueError(f"Skill '{skill_name}' already exists")
        display_name = skill_name.replace("-", " ").title()
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
