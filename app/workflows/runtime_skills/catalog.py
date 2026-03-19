"""Runtime-skill catalog workflow ownership."""

from __future__ import annotations

from app.workflows.runtime_skills.contracts import (
    RuntimeSkillCatalogItem,
    RuntimeSkillDetail,
    RuntimeSkillDraftRecord,
    RuntimeSkillCatalogPort,
)
from app.skill_catalog_service import get_skill_catalog_service
from app.skill_import_service import get_skill_import_service
from app.skill_types import SkillRequirement


class RuntimeSkillCatalogUseCases(RuntimeSkillCatalogPort):
    """Canonical catalog read operations shared by Telegram and registry."""

    def _catalog(self):
        return get_skill_catalog_service()

    def _imports(self):
        return get_skill_import_service()

    def _summary(self, skill_name: str) -> RuntimeSkillCatalogItem | None:
        meta = self._catalog().catalog().get(skill_name)
        if meta is None:
            return None
        track = self._catalog().resolve_track(skill_name)
        if track is None:
            return None
        runtime_track = self._catalog().resolve_runtime_track(skill_name)
        info = self._catalog().resolve_info(skill_name)
        providers = info.providers if info is not None else ()
        requirement_keys = info.requirement_keys if info is not None else ()
        source_kind = track.source_kind
        return RuntimeSkillCatalogItem(
            name=skill_name,
            display_name=meta.display_name,
            description=meta.description,
            source_kind=source_kind,
            providers=providers,
            requirement_keys=requirement_keys,
            has_custom_override=self._imports().has_custom_override(skill_name),
            can_activate=(runtime_track is not None),
            can_update=(source_kind == "imported"),
            can_uninstall=(source_kind == "imported"),
            lifecycle_status=track.revision.status,
        )

    def list_skills(self, query: str = "") -> list[RuntimeSkillCatalogItem]:
        query_text = query.strip().lower()
        items: list[RuntimeSkillCatalogItem] = []
        for skill_name, meta in sorted(self._catalog().catalog().items()):
            if query_text and not any(
                query_text in part
                for part in (
                    skill_name.lower(),
                    meta.display_name.lower(),
                    meta.description.lower(),
                )
            ):
                continue
            summary = self._summary(skill_name)
            if summary is not None:
                items.append(summary)
        return items

    def get_skill(self, skill_name: str) -> RuntimeSkillDetail | None:
        summary = self._summary(skill_name)
        if summary is None:
            return None
        info = self._catalog().resolve_info(skill_name)
        if info is None:
            return None
        return RuntimeSkillDetail(
            name=summary.name,
            display_name=summary.display_name,
            description=summary.description,
            body=info.body,
            source_kind=summary.source_kind,
            providers=summary.providers,
            requirement_keys=summary.requirement_keys,
            has_custom_override=summary.has_custom_override,
            can_activate=summary.can_activate,
            can_update=summary.can_update,
            can_uninstall=summary.can_uninstall,
            lifecycle_status=summary.lifecycle_status,
        )

    def has_skill(self, skill_name: str) -> bool:
        return self._summary(skill_name) is not None

    def filter_resolvable(self, names: list[str]) -> list[str]:
        return self._catalog().filter_resolvable(names)

    def requirements(self, skill_name: str) -> tuple[SkillRequirement, ...]:
        return tuple(self._catalog().requirements(skill_name))

    def missing_requirements(
        self,
        skill_name: str,
        credential_values: dict[str, str],
    ) -> tuple[SkillRequirement, ...]:
        return tuple(
            item
            for item in self.requirements(skill_name)
            if item.key not in credential_values
        )

    def create_custom_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillDraftRecord:
        record = self._catalog().create_custom_draft(skill_name, owner_actor=owner_actor)
        return RuntimeSkillDraftRecord(name=record.slug, visibility=record.visibility)


_USE_CASES = RuntimeSkillCatalogUseCases()


def get_runtime_skill_catalog_use_cases() -> RuntimeSkillCatalogUseCases:
    return _USE_CASES
