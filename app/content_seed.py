"""Seed helpers for migrating built-in runtime content into the content store."""

from __future__ import annotations

from pathlib import Path

from octopus_sdk.content_models import (
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    SkillRevisionRecord,
    RuntimeSkillTrackRecord,
)
from app.content_store_base import AbstractContentStore
from app.runtime_skill_paths import BUILTIN_SKILL_CATALOG_DIR
from octopus_sdk.skill_packages import (
    SKILL_PROVIDER_FILES,
    default_skill_display_name,
    load_provider_config,
    load_skill_files,
    load_skill_markdown,
    load_skill_requirements,
)

_DEFAULT_PROVIDER_GUIDANCE = {
    "claude": (
        "# Claude Runtime Guidance\n\n"
        "The runtime composes the final Claude system prompt the session role, "
        "active runtime skills, and provider-specific capability settings."
    ),
    "codex": (
        "# Codex Runtime Guidance\n\n"
        "The runtime composes the final Codex prompt and helper-script staging plan "
        "the session role, active runtime skills, and provider-specific capability settings."
    ),
}
def track_from_skill_dir(
    path: Path,
    *,
    source_kind: str,
    source_uri: str,
    owner_actor: str = "",
    visibility: str = "shared",
    is_mutable: bool = False,
    version_label: str = "",
    created_by: str = "",
    display_name_override: str = "",
    description_override: str = "",
) -> RuntimeSkillTrackRecord:
    meta, body = load_skill_markdown(path / "skill.md")
    slug = path.name
    revision = SkillRevisionRecord(
        instruction_body=body,
        requirements=load_skill_requirements(path / "requires.yaml"),
        provider_config={
            provider: config
            for provider, filename in SKILL_PROVIDER_FILES.items()
            if (config := load_provider_config(path / filename))
        },
        files=load_skill_files(path),
        version_label=version_label,
        created_by=created_by,
    )
    return RuntimeSkillTrackRecord(
        slug=slug,
        display_name=display_name_override or str(meta.get("display_name") or meta.get("name") or default_skill_display_name(slug)),
        description=description_override or str(meta.get("description") or ""),
        source_kind=source_kind,
        source_uri=source_uri,
        owner_actor=owner_actor,
        visibility=visibility,
        is_mutable=is_mutable,
        revision=revision,
    )


def _builtin_skill_track(path: Path) -> RuntimeSkillTrackRecord:
    return track_from_skill_dir(
        path,
        source_kind="builtin",
        source_uri=f"catalog/{path.name}",
        visibility="shared",
        is_mutable=False,
        version_label="builtin",
        created_by="seed",
    )


def builtin_skill_tracks() -> list[RuntimeSkillTrackRecord]:
    out: list[RuntimeSkillTrackRecord] = []
    if not BUILTIN_SKILL_CATALOG_DIR.is_dir():
        return out
    for child in sorted(BUILTIN_SKILL_CATALOG_DIR.iterdir()):
        if not child.is_dir() or not (child / "skill.md").is_file():
            continue
        out.append(_builtin_skill_track(child))
    return out


def default_provider_guidance_tracks() -> list[ProviderGuidanceTrackRecord]:
    return [
        ProviderGuidanceTrackRecord(
            provider=provider,
            scope_kind="system",
            scope_key="",
            is_mutable=False,
            revision=ProviderGuidanceRevisionRecord(
                content=content,
                format="markdown",
                created_by="seed",
            ),
        )
        for provider, content in sorted(_DEFAULT_PROVIDER_GUIDANCE.items())
    ]


def seed_builtin_content(store: AbstractContentStore) -> None:
    for record in builtin_skill_tracks():
        store.replace_skill_track(record)
    for record in default_provider_guidance_tracks():
        store.replace_provider_guidance(record)
