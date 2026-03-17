"""Shared service layer for managed skill import/store lifecycle.

The current implementation remains filesystem-backed, but callers should rely
on this service so install/update/search/diff behavior can move to the future
content store without surface rewrites.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import registry as registry_client
from app import store


@dataclass(frozen=True)
class SkillMutationResult:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class SkillUpdateStatus:
    name: str
    status: str
    has_custom_override: bool


class SkillImportService:
    """Surface-neutral managed skill lifecycle service."""

    def bundled_search(self, query: str):
        return store.search(query)

    def bundled_exists(self, name: str) -> bool:
        store_path = store.STORE_DIR / name
        return store_path.is_dir() and (store_path / "skill.md").is_file()

    def registry_search(self, registry_url: str, query: str):
        index = registry_client.fetch_index(registry_url)
        return registry_client.search_index(index, query)

    def install_bundled(self, name: str) -> SkillMutationResult:
        ok, message = store.install(name)
        return SkillMutationResult(name=name, ok=ok, message=message)

    def install_from_registry(self, name: str, registry_url: str) -> SkillMutationResult:
        index = registry_client.fetch_index(registry_url)
        if name not in index:
            return SkillMutationResult(
                name=name,
                ok=False,
                message=f"Skill '{name}' not found in store or registry.",
            )
        ok, message = store.install_from_registry(name, index[name])
        return SkillMutationResult(name=name, ok=ok, message=message)

    def uninstall(self, name: str, default_skills: tuple[str, ...] = ()) -> SkillMutationResult:
        ok, message = store.uninstall(name, default_skills)
        return SkillMutationResult(name=name, ok=ok, message=message)

    def list_updates(self) -> list[SkillUpdateStatus]:
        return [
            SkillUpdateStatus(
                name=name,
                status=status,
                has_custom_override=store.has_custom_override(name),
            )
            for name, status in store.check_updates()
        ]

    def update(self, name: str) -> SkillMutationResult:
        ok, message = store.update_skill(name)
        return SkillMutationResult(name=name, ok=ok, message=message)

    def update_all(self) -> list[SkillMutationResult]:
        return [
            SkillMutationResult(name=name, ok=ok, message=message)
            for name, ok, message in store.update_all()
        ]

    def diff(self, name: str, *, max_chars: int = 4000) -> SkillMutationResult:
        ok, message = store.diff_skill(name, max_chars=max_chars)
        return SkillMutationResult(name=name, ok=ok, message=message)

    def is_installed(self, name: str) -> bool:
        return store.is_store_installed(name)

    def has_custom_override(self, name: str) -> bool:
        return store.has_custom_override(name)

    def requirement_keys(self, name: str) -> list[str]:
        return store.get_store_skill_requirements(name)


_SERVICE = SkillImportService()


def get_skill_import_service() -> SkillImportService:
    return _SERVICE
