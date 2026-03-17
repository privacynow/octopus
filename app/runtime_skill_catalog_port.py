"""Contracts for runtime skill catalog workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.skills import SkillRequirement


@dataclass(frozen=True)
class RuntimeSkillCatalogItem:
    name: str
    display_name: str
    description: str
    source_kind: str
    providers: tuple[str, ...]
    requirement_keys: tuple[str, ...]
    has_custom_override: bool
    can_activate: bool
    can_update: bool
    can_uninstall: bool


@dataclass(frozen=True)
class RuntimeSkillDetail:
    name: str
    display_name: str
    description: str
    body: str
    source_kind: str
    providers: tuple[str, ...]
    requirement_keys: tuple[str, ...]
    has_custom_override: bool
    can_activate: bool
    can_update: bool
    can_uninstall: bool


@dataclass(frozen=True)
class RuntimeSkillDraftRecord:
    name: str
    visibility: str


class RuntimeSkillCatalogPort(Protocol):
    def list_skills(self, query: str = "") -> list[RuntimeSkillCatalogItem]: ...

    def get_skill(self, skill_name: str) -> RuntimeSkillDetail | None: ...

    def has_skill(self, skill_name: str) -> bool: ...

    def filter_resolvable(self, names: list[str]) -> list[str]: ...

    def requirements(self, skill_name: str) -> tuple[SkillRequirement, ...]: ...

    def missing_requirements(
        self,
        skill_name: str,
        credential_values: dict[str, str],
    ) -> tuple[SkillRequirement, ...]: ...

    def create_custom_draft(
        self,
        skill_name: str,
        *,
        owner_actor: str = "",
    ) -> RuntimeSkillDraftRecord: ...
