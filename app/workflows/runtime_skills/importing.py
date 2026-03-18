"""Runtime-skill import and update workflow ownership."""

from __future__ import annotations

from app.provider_guidance_service import get_provider_guidance_service
from app.workflows.runtime_skills.catalog import (
    get_runtime_skill_catalog_use_cases,
)
from app.workflows.runtime_skills.contracts import (
    PromptWarningContext,
    RegistryRuntimeSkillSearchHit,
    RuntimeSkillSearchResults,
    RuntimeSkillMutationOutcome,
    RuntimeSkillUpdateStatusItem,
    RuntimeSkillImportPort,
)
from app.skill_import_service import get_skill_import_service


class RuntimeSkillImportUseCases(RuntimeSkillImportPort):
    """Canonical import/update operations shared by Telegram and registry."""

    def _imports(self):
        return get_skill_import_service()

    def _guidance(self):
        return get_provider_guidance_service()

    def _catalog(self):
        return get_runtime_skill_catalog_use_cases()

    def _prompt_size_warnings(
        self,
        skill_name: str,
        warning_context: PromptWarningContext | None,
    ) -> tuple[str, ...]:
        if warning_context is None:
            return ()
        return tuple(
            self._guidance().check_prompt_size_cross_chat(
                warning_context.data_dir,
                skill_name,
                warning_context.provider_name,
                warning_context.provider_state_factory,
                warning_context.approval_mode,
            )
        )

    def search(self, query: str, *, registry_url: str = "") -> RuntimeSkillSearchResults:
        catalog_hits = tuple(self._catalog().list_skills(query))
        registry_hits: tuple[RegistryRuntimeSkillSearchHit, ...] = ()
        registry_error = ""
        query_text = query.strip()
        if registry_url and query_text:
            try:
                registry_hits = tuple(
                    RegistryRuntimeSkillSearchHit(
                        name=item.name,
                        display_name=item.display_name,
                        description=item.description,
                        publisher=item.publisher,
                        version=item.version,
                        can_import=True,
                    )
                    for item in self._imports().registry_search(registry_url, query_text)
                )
            except Exception as exc:
                registry_error = str(exc)[:200]
        return RuntimeSkillSearchResults(
            catalog=catalog_hits,
            registry=registry_hits,
            registry_error=registry_error,
        )

    def install_from_registry(
        self,
        skill_name: str,
        registry_url: str,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> RuntimeSkillMutationOutcome:
        result = self._imports().install_from_registry(skill_name, registry_url)
        return RuntimeSkillMutationOutcome(
            name=result.name,
            ok=result.ok,
            message=result.message,
            prompt_size_warnings=self._prompt_size_warnings(skill_name, warning_context) if result.ok else (),
        )

    def uninstall(
        self,
        skill_name: str,
        *,
        default_skills: tuple[str, ...] = (),
    ) -> RuntimeSkillMutationOutcome:
        result = self._imports().uninstall(skill_name, default_skills)
        return RuntimeSkillMutationOutcome(name=result.name, ok=result.ok, message=result.message)

    def update(
        self,
        skill_name: str,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> RuntimeSkillMutationOutcome:
        result = self._imports().update(skill_name)
        return RuntimeSkillMutationOutcome(
            name=result.name,
            ok=result.ok,
            message=result.message,
            prompt_size_warnings=self._prompt_size_warnings(skill_name, warning_context) if result.ok else (),
        )

    def update_all(
        self,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> tuple[RuntimeSkillMutationOutcome, ...]:
        return tuple(
            self.update(result.name, warning_context=warning_context)
            if result.ok else
            RuntimeSkillMutationOutcome(
                name=result.name,
                ok=result.ok,
                message=result.message,
            )
            for result in self._imports().update_all()
        )

    def diff(self, skill_name: str) -> RuntimeSkillMutationOutcome:
        result = self._imports().diff(skill_name)
        return RuntimeSkillMutationOutcome(name=result.name, ok=result.ok, message=result.message)

    def list_updates(self) -> tuple[RuntimeSkillUpdateStatusItem, ...]:
        return tuple(
            RuntimeSkillUpdateStatusItem(
                name=item.name,
                status=item.status,
                has_custom_override=item.has_custom_override,
            )
            for item in self._imports().list_updates()
        )


_USE_CASES = RuntimeSkillImportUseCases()


def get_runtime_skill_import_use_cases() -> RuntimeSkillImportUseCases:
    return _USE_CASES
