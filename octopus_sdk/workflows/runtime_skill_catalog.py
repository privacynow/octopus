"""SDK-owned runtime-skill catalog workflows."""

from __future__ import annotations

from octopus_sdk.skill_packages import (
    publish_ready,
    validate_skill_package,
    skill_has_unpublished_changes,
    skill_runtime_available,
)
from octopus_sdk.skill_types import SkillRequirement
from octopus_sdk.workflows.skills import (
    RuntimeSkillCatalogItem,
    RuntimeSkillCatalogPort,
    RuntimeSkillDetail,
    RuntimeSkillDraftRecord,
    SkillCatalogServicePort,
    SkillImportServicePort,
    RuntimeSkillValidationProblem,
)


class RuntimeSkillCatalogUseCases(RuntimeSkillCatalogPort):
    """Canonical catalog read operations shared across channel entrypoints."""

    def __init__(
        self,
        *,
        catalog_service: SkillCatalogServicePort,
        import_service: SkillImportServicePort,
        default_skills: tuple[str, ...] = (),
    ) -> None:
        self._catalog = catalog_service
        self._imports = import_service
        self._default_skills = frozenset(
            str(name or "").strip()
            for name in default_skills
            if str(name or "").strip()
        )

    def _summary(self, skill_name: str) -> RuntimeSkillCatalogItem | None:
        meta = self._catalog.catalog().get(skill_name)
        if meta is None:
            return None
        track = self._catalog.resolve_track(skill_name)
        if track is None:
            return None
        runtime_track = self._catalog.resolve_runtime_track(skill_name)
        info = self._catalog.resolve_info(skill_name)
        providers = info.providers if info is not None else ()
        requirement_keys = info.requirement_keys if info is not None else ()
        source_kind = track.source_kind
        return RuntimeSkillCatalogItem(
            name=skill_name,
            display_name=str(getattr(meta, "display_name", skill_name)),
            description=str(getattr(meta, "description", "")),
            source_kind=source_kind,
            source_label=info.source_label if info is not None else source_kind,
            providers=providers,
            requirement_keys=requirement_keys,
            requires_credentials=bool(requirement_keys),
            has_custom_override=self._imports.has_custom_override(skill_name),
            can_activate=(runtime_track is not None),
            can_update=(source_kind == "imported"),
            can_uninstall=(source_kind == "imported"),
            lifecycle_status=track.revision.status,
            runtime_available=skill_runtime_available(track),
            default_for_new_conversations=(skill_name in self._default_skills),
            visibility=track.visibility,
            is_mutable=track.is_mutable,
            has_unpublished_changes=skill_has_unpublished_changes(track),
        )

    def list_skills(self, query: str = "") -> list[RuntimeSkillCatalogItem]:
        query_text = query.strip().lower()
        items: list[RuntimeSkillCatalogItem] = []
        for skill_name, meta in sorted(self._catalog.catalog().items()):
            display_name = str(getattr(meta, "display_name", ""))
            description = str(getattr(meta, "description", ""))
            if query_text and not any(
                query_text in part
                for part in (
                    skill_name.lower(),
                    display_name.lower(),
                    description.lower(),
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
        info = self._catalog.resolve_info(skill_name)
        if info is None:
            return None
        validation_problems = tuple(
            RuntimeSkillValidationProblem(
                code=item.code,
                message=item.message,
                field_path=item.field_path,
                severity=item.severity,
            )
            for item in validate_skill_package(
                skill_name=summary.name,
                display_name=summary.display_name,
                body=info.body,
                requirements=list(info.requirements),
                provider_config=info.provider_config,
                files=info.files,
            )
        )
        return RuntimeSkillDetail(
            name=summary.name,
            display_name=summary.display_name,
            description=summary.description,
            body=info.body,
            source_kind=summary.source_kind,
            source_label=summary.source_label,
            providers=summary.providers,
            requirement_keys=summary.requirement_keys,
            requires_credentials=summary.requires_credentials,
            has_custom_override=summary.has_custom_override,
            can_activate=summary.can_activate,
            can_update=summary.can_update,
            can_uninstall=summary.can_uninstall,
            lifecycle_status=summary.lifecycle_status,
            runtime_available=summary.runtime_available,
            default_for_new_conversations=summary.default_for_new_conversations,
            visibility=summary.visibility,
            is_mutable=summary.is_mutable,
            has_unpublished_changes=summary.has_unpublished_changes,
            requirements=info.requirements,
            provider_config=info.provider_config,
            files=info.files,
            validation_problems=validation_problems,
            publish_ready=publish_ready(
                skill_name=summary.name,
                display_name=summary.display_name,
                body=info.body,
                requirements=list(info.requirements),
                provider_config=info.provider_config,
                files=info.files,
            ),
        )

    def has_skill(self, skill_name: str) -> bool:
        return self._summary(skill_name) is not None

    def has_runtime_skill(self, skill_name: str) -> bool:
        return self._catalog.has_runtime_skill(skill_name)

    def resolve_runtime_track(self, skill_name: str):
        return self._catalog.resolve_runtime_track(skill_name)

    def filter_resolvable(self, names: list[str]) -> list[str]:
        return self._catalog.filter_resolvable(names)

    def requirements(self, skill_name: str) -> tuple[SkillRequirement, ...]:
        return tuple(self._catalog.requirements(skill_name))

    def missing_requirements(
        self,
        skill_name: str,
        credential_values: dict[str, str],
    ) -> tuple[SkillRequirement, ...]:
        return tuple(item for item in self.requirements(skill_name) if item.key not in credential_values)

    def create_custom_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillDraftRecord:
        record = self._catalog.create_custom_draft(skill_name, owner_actor=owner_actor)
        return RuntimeSkillDraftRecord(name=record.slug, visibility=record.visibility)
