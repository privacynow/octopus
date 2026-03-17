"""Shared service layer for runtime skill catalog access.

The current implementation is file-backed. Callers should depend on this
service rather than hard-coding repo or filesystem paths so the later content
store migration has a stable seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.skills import (
    SkillMeta,
    get_skill_requirements,
    load_catalog,
    scaffold_skill,
    skill_info_resolved,
)


@dataclass(frozen=True)
class SkillInfoRecord:
    meta: dict[str, str]
    body: str
    source: str
    skill_path: Path


class SkillCatalogService:
    """Surface-neutral runtime skill catalog service."""

    def catalog(self) -> dict[str, SkillMeta]:
        return load_catalog()

    def has_skill(self, skill_name: str) -> bool:
        return skill_name in self.catalog()

    def requirements(self, skill_name: str):
        return get_skill_requirements(skill_name)

    def resolve_info(self, skill_name: str) -> SkillInfoRecord | None:
        result = skill_info_resolved(skill_name)
        if not result:
            return None
        meta, body, source, skill_path = result
        return SkillInfoRecord(meta=meta, body=body, source=source, skill_path=skill_path)

    def create_custom_draft(self, skill_name: str) -> Path:
        return scaffold_skill(skill_name)


_SERVICE = SkillCatalogService()


def get_skill_catalog_service() -> SkillCatalogService:
    return _SERVICE
