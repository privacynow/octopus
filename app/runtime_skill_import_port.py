"""Contracts for runtime skill import and update workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from app.runtime_skill_catalog_port import RuntimeSkillCatalogItem


@dataclass(frozen=True)
class PromptWarningContext:
    data_dir: Path
    provider_name: str
    provider_state_factory: Callable[[], dict[str, Any]]
    approval_mode: str


@dataclass(frozen=True)
class RegistryRuntimeSkillSearchHit:
    name: str
    display_name: str
    description: str
    publisher: str
    version: str
    can_import: bool


@dataclass(frozen=True)
class RuntimeSkillSearchResults:
    catalog: tuple[RuntimeSkillCatalogItem, ...]
    registry: tuple[RegistryRuntimeSkillSearchHit, ...]
    registry_error: str = ""


@dataclass(frozen=True)
class RuntimeSkillMutationOutcome:
    name: str
    ok: bool
    message: str
    prompt_size_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeSkillUpdateStatusItem:
    name: str
    status: str
    has_custom_override: bool


class RuntimeSkillImportPort(Protocol):
    def search(self, query: str, *, registry_url: str = "") -> RuntimeSkillSearchResults: ...

    def install_from_registry(
        self,
        skill_name: str,
        registry_url: str,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> RuntimeSkillMutationOutcome: ...

    def uninstall(
        self,
        skill_name: str,
        *,
        default_skills: tuple[str, ...] = (),
    ) -> RuntimeSkillMutationOutcome: ...

    def update(
        self,
        skill_name: str,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> RuntimeSkillMutationOutcome: ...

    def update_all(
        self,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> tuple[RuntimeSkillMutationOutcome, ...]: ...

    def diff(self, skill_name: str) -> RuntimeSkillMutationOutcome: ...

    def list_updates(self) -> tuple[RuntimeSkillUpdateStatusItem, ...]: ...
