"""Seed helpers for migrating built-in runtime content into the content store."""

from __future__ import annotations

from pathlib import Path
import hashlib

import frontmatter
import yaml

from app.content_models import (
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillTrackRecord,
    SkillFileRecord,
    SkillRevisionRecord,
)
from app.content_store_base import AbstractContentStore
from app.skills import CATALOG_DIR, get_skill_requirements, load_provider_yaml

_SKILL_RESERVED_FILES = {"skill.md", "requires.yaml", "claude.yaml", "codex.yaml"}
_DEFAULT_PROVIDER_GUIDANCE = {
    "claude": (
        "# Claude Runtime Guidance\n\n"
        "The runtime composes the final Claude system prompt from the session role, "
        "active runtime skills, and provider-specific capability settings."
    ),
    "codex": (
        "# Codex Runtime Guidance\n\n"
        "The runtime composes the final Codex prompt and helper-script staging plan "
        "from the session role, active runtime skills, and provider-specific capability settings."
    ),
}


def _load_frontmatter(path: Path) -> tuple[dict, str]:
    post = frontmatter.load(str(path))
    return dict(post.metadata), post.content.strip()


def _content_type_for(path: Path) -> str:
    if path.suffix == ".sh":
        return "text/x-shellscript"
    if path.suffix == ".json":
        return "application/json"
    if path.suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if path.suffix == ".md":
        return "text/markdown"
    return "text/plain"


def _builtin_skill_track(path: Path) -> RuntimeSkillTrackRecord:
    meta, body = _load_frontmatter(path / "skill.md")
    slug = path.name
    files: list[SkillFileRecord] = []
    for child in sorted(path.iterdir()):
        if not child.is_file() or child.name in _SKILL_RESERVED_FILES:
            continue
        files.append(
            SkillFileRecord(
                relative_path=child.name,
                content_text=child.read_text(encoding="utf-8"),
                content_type=_content_type_for(child),
                executable=child.suffix == ".sh",
            )
        )
    revision = SkillRevisionRecord(
        instruction_body=body,
        requirements=[item.__dict__ for item in get_skill_requirements(slug)],
        provider_config={
            provider: config
            for provider in ("claude", "codex")
            if (config := load_provider_yaml(slug, provider))
        },
        files=tuple(files),
        version_label="builtin",
        created_by="seed",
    )
    return RuntimeSkillTrackRecord(
        slug=slug,
        display_name=str(meta.get("display_name") or meta.get("name") or slug),
        description=str(meta.get("description") or ""),
        source_kind="builtin",
        source_uri=f"catalog/{slug}",
        visibility="shared",
        is_mutable=False,
        revision=revision,
    )


def builtin_skill_tracks() -> list[RuntimeSkillTrackRecord]:
    out: list[RuntimeSkillTrackRecord] = []
    if not CATALOG_DIR.is_dir():
        return out
    for child in sorted(CATALOG_DIR.iterdir()):
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
