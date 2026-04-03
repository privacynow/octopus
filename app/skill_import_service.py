"""Shared service layer for runtime skill import and update lifecycle."""

from __future__ import annotations

import difflib
import logging
import tempfile
from pathlib import Path

from app import registry as registry_client
from octopus_sdk.content_models import RuntimeSkillTrackRecord
from app.content_seed import track_from_skill_dir
from app.content_store import get_content_store
from app.skill_catalog_service import get_skill_catalog_service
from octopus_sdk.skill_packages import build_skill_virtual_files
from octopus_sdk.workflows.skills import RegistrySkillSearchRecord, SkillMutationResult, SkillUpdateStatus


log = logging.getLogger(__name__)

def _registry_source_uri(registry_url: str, skill_name: str) -> str:
    return f"{registry_url}#{skill_name}"


def _parse_registry_source_uri(source_uri: str) -> tuple[str, str] | None:
    if "#" not in source_uri:
        return None
    registry_url, skill_name = source_uri.rsplit("#", 1)
    if not registry_url or not skill_name:
        return None
    return registry_url, skill_name
def _diff_tracks(
    current: RuntimeSkillTrackRecord,
    incoming: RuntimeSkillTrackRecord,
    *,
    _label: str,
    to_label: str,
    max_chars: int,
) -> str:
    current_files = build_skill_virtual_files(current)
    incoming_files = build_skill_virtual_files(incoming)
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
                fromfile=f"{_label}/{current.slug}/{rel}",
                tofile=f"{to_label}/{incoming.slug}/{rel}",
            )
        )
    text = "".join(lines)
    if not text:
        return f"Skill '{current.slug}' has no differences ({_label} vs {to_label})."
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... (truncated at {max_chars} chars)"
    return text


def _safe_registry_failure_message(action: str) -> str:
    messages = {
        "install": "Could not reach the skill store. Try again later.",
        "update": "Could not update this skill from the store. Try again later.",
        "diff": "Could not fetch the store version for this skill. Try again later.",
    }
    return messages[action]


class SkillImportService:
    """Channel-neutral runtime skill import lifecycle service."""

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
            artifact_digest = registry_client.skill_artifact_digest(staging)
            if artifact_digest != skill.digest:
                raise ValueError(
                    f"Digest mismatch for skill '{skill_name}': "
                    f"expected {skill.digest}, got {artifact_digest}"
                )
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

    def registry_search(self, registry_url: str, query: str) -> list[RegistrySkillSearchRecord]:
        index = registry_client.fetch_index(registry_url)
        return [
            RegistrySkillSearchRecord(
                name=item.name,
                display_name=item.display_name,
                description=item.description,
                publisher=item.publisher,
                version=item.version,
            )
            for item in registry_client.search_index(index, query)
        ]

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
            log.warning(
                "Registry install failed for skill %s: %s",
                name,
                exc.__class__.__name__,
                exc_info=True,
            )
            return SkillMutationResult(
                name=name,
                ok=False,
                message=_safe_registry_failure_message("install"),
            )
        self._store().replace_skill_track(record)
        return SkillMutationResult(
            name=name,
            ok=True,
            message=f"Skill '{name}' installed on this bot from the skill store. Use /skills add {name} to activate it in a conversation.",
        )

    def uninstall(self, name: str, default_skills: tuple[str, ...] = ()) -> SkillMutationResult:
        imported = self._imported_track(name)
        if imported is None:
            return SkillMutationResult(
                name=name,
                ok=False,
                message=f"Skill '{name}' is not installed from the skill store on this bot.",
            )
        remaining_tracks = [item for item in self._catalog.list_tracks(name) if item.source_kind != "imported"]
        if name in default_skills and not remaining_tracks:
            return SkillMutationResult(
                name=name,
                ok=False,
                message=(
                    f"Skill '{name}' is listed in BOT_SKILLS. "
                    "Remove it your config before uninstalling the imported track."
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
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' is not installed from the skill store on this bot.")
        parsed = _parse_registry_source_uri(imported.source_uri)
        if parsed is None:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' does not have a valid registry source.")
        registry_url, skill_name = parsed
        try:
            incoming = self._incoming_registry_track(skill_name, registry_url)
        except Exception as exc:
            log.warning(
                "Registry update failed for skill %s: %s",
                name,
                exc.__class__.__name__,
                exc_info=True,
            )
            return SkillMutationResult(
                name=name,
                ok=False,
                message=_safe_registry_failure_message("update"),
            )
        if incoming.revision.digest == imported.revision.digest:
            return SkillMutationResult(name=name, ok=True, message=f"Skill '{name}' is already up to date.")
        self._store().replace_skill_track(incoming)
        return SkillMutationResult(name=name, ok=True, message=f"Skill '{name}' updated from the skill store.")

    def update_all(self) -> list[SkillMutationResult]:
        results: list[SkillMutationResult] = []
        for item in self.list_updates():
            if item.status == "update_available":
                results.append(self.update(item.name))
        return results

    def diff(self, name: str, *, max_chars: int = 4000) -> SkillMutationResult:
        imported = self._imported_track(name)
        if imported is None:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' is not installed from the skill store on this bot.")
        parsed = _parse_registry_source_uri(imported.source_uri)
        if parsed is None:
            return SkillMutationResult(name=name, ok=False, message=f"Skill '{name}' does not have a valid registry source.")
        registry_url, skill_name = parsed
        try:
            incoming = self._incoming_registry_track(skill_name, registry_url)
        except Exception as exc:
            log.warning(
                "Registry diff fetch failed for skill %s: %s",
                name,
                exc.__class__.__name__,
                exc_info=True,
            )
            return SkillMutationResult(
                name=name,
                ok=False,
                message=_safe_registry_failure_message("diff"),
            )
        return SkillMutationResult(
            name=name,
            ok=True,
            message=_diff_tracks(imported, incoming, _label="installed on bot", to_label="skill store", max_chars=max_chars),
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
