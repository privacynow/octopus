"""Helpers for registry-backed runtime skill tests."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path

import yaml

from app.registry import RegistrySkill, skill_artifact_digest


def write_skill_bundle(
    root: Path,
    name: str,
    *,
    body: str,
    display_name: str | None = None,
    description: str = "test fixture",
    requires: list[dict[str, str]] | None = None,
    claude_config: dict | None = None,
    codex_config: dict | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    skill_dir = root / name
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"display_name: {display_name or name.title()}\n"
            f"description: {description}\n"
            "---\n\n"
            f"{body.rstrip()}\n"
        ),
        encoding="utf-8",
    )
    if requires:
        (skill_dir / "requires.yaml").write_text(
            yaml.safe_dump({"credentials": requires}, sort_keys=False),
            encoding="utf-8",
        )
    if claude_config:
        (skill_dir / "claude.yaml").write_text(
            yaml.safe_dump(claude_config, sort_keys=False),
            encoding="utf-8",
        )
    if codex_config:
        (skill_dir / "codex.yaml").write_text(
            yaml.safe_dump(codex_config, sort_keys=False),
            encoding="utf-8",
        )
    for relative_path, content in sorted((extra_files or {}).items()):
        target = skill_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if target.suffix == ".sh":
            target.chmod(0o755)
    return skill_dir


@dataclass
class _RegistryEntry:
    path: Path
    version: str
    publisher: str
    display_name: str
    description: str
    digest: str


class FakeRuntimeSkillRegistry:
    def __init__(self, root: Path, *, registry_url: str = "https://registry.example.test/index.json") -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_url = registry_url
        self._entries: dict[str, _RegistryEntry] = {}

    def add_skill(
        self,
        name: str,
        *,
        body: str,
        version: str = "1.0.0",
        publisher: str = "tests",
        display_name: str | None = None,
        description: str = "test fixture",
        requires: list[dict[str, str]] | None = None,
        claude_config: dict | None = None,
        codex_config: dict | None = None,
        extra_files: dict[str, str] | None = None,
        digest: str | None = None,
    ) -> Path:
        path = write_skill_bundle(
            self.root,
            name,
            body=body,
            display_name=display_name,
            description=description,
            requires=requires,
            claude_config=claude_config,
            codex_config=codex_config,
            extra_files=extra_files,
        )
        self._entries[name] = _RegistryEntry(
            path=path,
            version=version,
            publisher=publisher,
            display_name=display_name or name.title(),
            description=description,
            digest=digest or skill_artifact_digest(path),
        )
        return path

    def patch(self, monkeypatch) -> None:
        import app.skill_import_service as import_service

        monkeypatch.setattr(import_service.registry_client, "fetch_index", self.fetch_index)
        monkeypatch.setattr(import_service.registry_client, "download_artifact", self.download_artifact)

    def fetch_index(self, registry_url: str) -> dict[str, RegistrySkill]:
        if registry_url != self.registry_url:
            raise ValueError(f"Unexpected registry URL: {registry_url}")
        return {
            name: RegistrySkill(
                name=name,
                display_name=entry.display_name,
                description=entry.description,
                version=entry.version,
                publisher=entry.publisher,
                digest=entry.digest,
                artifact_url=f"artifact://{name}",
            )
            for name, entry in sorted(self._entries.items())
        }

    def download_artifact(self, artifact_url: str, dest_dir: Path) -> Path:
        skill_name = artifact_url.rsplit("://", 1)[-1]
        entry = self._entries.get(skill_name)
        if entry is None:
            raise ValueError(f"Unknown artifact: {artifact_url}")
        shutil.copytree(entry.path, dest_dir, dirs_exist_ok=True)
        return dest_dir
