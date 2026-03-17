"""Shared service layer for runtime skill import and update lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import shutil
import tempfile
from pathlib import Path

import yaml

from app import registry as registry_client
from app.content_models import RuntimeSkillTrackRecord
from app.content_seed import track_from_skill_dir
from app.content_store import get_content_store
from app.skill_catalog_service import get_skill_catalog_service


@dataclass(frozen=True)
class CatalogSearchResult:
    name: str
    display_name: str
    description: str


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


def _registry_source_uri(registry_url: str, skill_name: str) -> str:
    return f"{registry_url}#{skill_name}"


def _parse_registry_source_uri(source_uri: str) -> tuple[str, str] | None:
    if "#" not in source_uri:
        return None
    registry_url, skill_name = source_uri.rsplit("#", 1)
    if not registry_url or not skill_name:
        return None
    return registry_url, skill_name


def _track_to_virtual_files(record: RuntimeSkillTrackRecord) -> dict[str, str]:
    skill_md = (
        "---\n"
        f"name: {record.slug}\n"
        f"display_name: {record.display_name}\n"
        f"description: {record.description}\n"
        "---\n\n"
        f"{record.revision.instruction_body.rstrip()}\n"
    )
    files = {"skill.md": skill_md}
    if record.revision.requirements:
        files["requires.yaml"] = yaml.safe_dump(
            {"credentials": record.revision.requirements},
            sort_keys=False,
        )
    for provider_name, config in sorted(record.revision.provider_config.items()):
        if isinstance(config, dict) and config:
            files[f"{provider_name}.yaml"] = yaml.safe_dump(config, sort_keys=False)
    for item in record.revision.files:
        files[item.relative_path] = item.content_text
    return files


def _diff_tracks(
    current: RuntimeSkillTrackRecord,
    incoming: RuntimeSkillTrackRecord,
    *,
    from_label: str,
    to_label: str,
    max_chars: int,
) -> str:
    current_files = _track_to_virtual_files(current)
    incoming_files = _track_to_virtual_files(incoming)
    paths = sorted(set(current_files) | set(incoming_files))
    lines: list[str] = []
    for rel in paths:
        before = current_files.get(rel, "").splitlines(keepends=True)
        after = incoming_files.get(rel, "").splitlines(keepends=True)
        if before == after:
            continue
        lines.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"{from_label}/{current.slug}/{rel}",
                tofile=f"{to_label}/{incoming.slug}/{rel}",
            )
        )
    text = "".join(lines)
    if not text:
        return f"Skill '{current.slug}' has no differences ({from_label} vs {to_label})."
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... (truncated at {max_chars} chars)"
    return text


class SkillImportService:
    """Surface-neutral runtime skill import lifecycle service."""

    def __init__(self) -> None:
        self._catalog = get_skill_catalog_service()

    def _store(self):
        return get_content_store()

    def _imported_track(self, name: str) -> RuntimeSkillTrackRecord | None:
        for record in self._catalog.list_tracks(name):
            if record.source_kind == "imported":
                return record
        return None

    def _incoming_registry_track(
        self,
        skill_name: str,
        registry_url: str,
    ) -> RuntimeSkillTrackRecord:
        index = registry_client.fetch_index(registry_url)
        if skill_name not in index:
            raise ValueError(f"Skill '{skill_name}' not found in registry.")
        skill = index[skill_name]
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / skill_name
            registry_client.download_artifact(skill.artifact_url, staging)
            return track_from_skill_dir(
                staging,
                source_kind="imported",
                source_uri=_registry_source_uri(registry_url, skill_name),
                visibility="shared",
                is_mutable=False,
                version_label=skill.version,
                created_by=skill.publisher or "registry",
                display_name_override=skill.display_name,
                description_override=skill.description,
            )

    def bundled_search(self, query: str):
        query = query.strip().lower()
        hits: list[CatalogSearchResult] = []
        for item in self._store().list_skill_summaries():
            haystacks = (item.slug.lower(), item.display_name.lower(), item.description.lower())
            if query and not any(query in part for part in haystacks):
                continue
            hits.append(
                CatalogSearchResult(
                    name=item.slug,
                    display_name=item.display_name,
                    description=item.description,
                )
            )
        return hits

    def bundled_exists(self, name: str) -> bool:
        return False

    def registry_search(self, registry_url: str, query: str):
        index = registry_client.fetch_index(registry_url)
        return registry_client.search_index(index, query)

    def install_bundled(self, name: str) -> SkillMutationResult:
        return SkillMutationResult(
            name=name,
            ok=False,
            message="Bundled store support was removed. Use the registry import flow instead.",
        )

    def install_from_registry(self, name: str, registry_url: str) -> SkillMutationResult:
        try:
            record = self._incoming_registry_track(name, registry_url)
        except Exception as exc:
            return SkillMutationResult(name=name, ok=False, message=str(exc))
        self._store().replace_skill_track(record)
        return SkillMutationResult(
            name=name,
            ok=True,
            message=f"Skill '{name}' installed from registry. Use /skills add {name} to activate.",
        )

    def uninstall(self, name: str, default_skills: tuple[str, ...] = ()) -> SkillMutationResult:
        imported = self._imported_track(name)
        if imported is None:
            return SkillMutationResult(
                name=name,
                ok=False,
                message=f"Skill '{name}' is not installed as an imported skill.",
            )
        remaining_tracks = [item for item in self._catalog.list_tracks(name) if item.source_kind != "imported"]
        if name in default_skills and not remaining_tracks:
            return SkillMutationResult(
                name=name,
                ok=False,
                message=(
                    f"Skill '{name}' is listed in BOT_SKILLS. "
                    "Remove it from your config before uninstalling the imported track."
                ),
            )
        deleted = self._store().delete_skill_track(
            name,
            source_kind="imported",
            source_uri=imported.source_uri,
            owner_actor=imported.owner_actor,
        )
        if not deleted:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' could not be removed.")
        return SkillMutationResult(name=name, ok=True, message=f"Skill '{name}' uninstalled.")

    def list_updates(self) -> list[SkillUpdateStatus]:
        out: list[SkillUpdateStatus] = []
        for summary in self._store().list_skill_summaries():
            imported = self._imported_track(summary.slug)
            if imported is None:
                continue
            parsed = _parse_registry_source_uri(imported.source_uri)
            if parsed is None:
                out.append(
                    SkillUpdateStatus(
                        name=summary.slug,
                        status="unknown_source",
                        has_custom_override=self.has_custom_override(summary.slug),
                    )
                )
                continue
            registry_url, skill_name = parsed
            try:
                incoming = self._incoming_registry_track(skill_name, registry_url)
            except Exception:
                out.append(
                    SkillUpdateStatus(
                        name=summary.slug,
                        status="update_check_failed",
                        has_custom_override=self.has_custom_override(summary.slug),
                    )
                )
                continue
            status = "up_to_date" if incoming.revision.digest == imported.revision.digest else "update_available"
            out.append(
                SkillUpdateStatus(
                    name=summary.slug,
                    status=status,
                    has_custom_override=self.has_custom_override(summary.slug),
                )
            )
        return out

    def update(self, name: str) -> SkillMutationResult:
        imported = self._imported_track(name)
        if imported is None:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' is not installed as an imported skill.")
        parsed = _parse_registry_source_uri(imported.source_uri)
        if parsed is None:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' does not have a valid registry source.")
        registry_url, skill_name = parsed
        try:
            incoming = self._incoming_registry_track(skill_name, registry_url)
        except Exception as exc:
            return SkillMutationResult(name=name, ok=False, message=str(exc))
        if incoming.revision.digest == imported.revision.digest:
            return SkillMutationResult(name=name, ok=True, message=f"Skill '{name}' is already up to date.")
        self._store().replace_skill_track(incoming)
        return SkillMutationResult(name=name, ok=True, message=f"Skill '{name}' updated from registry.")

    def update_all(self) -> list[SkillMutationResult]:
        results: list[SkillMutationResult] = []
        for item in self.list_updates():
            if item.status == "update_available":
                results.append(self.update(item.name))
        return results

    def diff(self, name: str, *, max_chars: int = 4000) -> SkillMutationResult:
        imported = self._imported_track(name)
        if imported is None:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' is not installed as an imported skill.")
        parsed = _parse_registry_source_uri(imported.source_uri)
        if parsed is None:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' does not have a valid registry source.")
        registry_url, skill_name = parsed
        try:
            incoming = self._incoming_registry_track(skill_name, registry_url)
        except Exception as exc:
            return SkillMutationResult(name=name, ok=False, message=str(exc))
        return SkillMutationResult(
            name=name,
            ok=True,
            message=_diff_tracks(imported, incoming, from_label="installed", to_label="registry", max_chars=max_chars),
        )

    def is_installed(self, name: str) -> bool:
        return self._imported_track(name) is not None

    def has_custom_override(self, name: str) -> bool:
        tracks = self._catalog.list_tracks(name)
        has_custom = any(item.source_kind == "custom" for item in tracks)
        has_lower = any(item.source_kind in {"builtin", "imported"} for item in tracks)
        return has_custom and has_lower

    def requirement_keys(self, name: str) -> list[str]:
        return [item.key for item in self._catalog.requirements(name)]


_SERVICE = SkillImportService()


def get_skill_import_service() -> SkillImportService:
    return _SERVICE
