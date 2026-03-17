"""Canonical content-domain models for runtime skills and provider guidance."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SkillFileRecord:
    relative_path: str
    content_text: str
    content_type: str = "text/plain"
    executable: bool = False

    @property
    def digest(self) -> str:
        payload = "\n".join(
            (
                self.relative_path,
                self.content_type,
                "1" if self.executable else "0",
                self.content_text,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SkillRevisionRecord:
    instruction_body: str
    requirements: list[dict[str, Any]] = field(default_factory=list)
    provider_config: dict[str, Any] = field(default_factory=dict)
    files: tuple[SkillFileRecord, ...] = ()
    version_label: str = ""
    changelog: str = ""
    created_by: str = ""
    created_at: str = ""

    @property
    def digest(self) -> str:
        payload = "\n".join(
            (
                self.version_label,
                self.instruction_body,
                self.changelog,
                _stable_json(self.requirements),
                _stable_json(self.provider_config),
                _stable_json(
                    [
                        {
                            "relative_path": item.relative_path,
                            "content_type": item.content_type,
                            "executable": item.executable,
                            "digest": item.digest,
                        }
                        for item in self.files
                    ]
                ),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeSkillTrackRecord:
    slug: str
    display_name: str
    description: str
    source_kind: str
    revision: SkillRevisionRecord
    source_uri: str = ""
    owner_actor: str = ""
    visibility: str = "shared"
    is_mutable: bool = False
    archived: bool = False


@dataclass(frozen=True)
class RuntimeSkillSummary:
    slug: str
    display_name: str
    description: str
    source_kind: str
    source_uri: str
    visibility: str
    is_mutable: bool
    digest: str


@dataclass(frozen=True)
class ProviderGuidanceRevisionRecord:
    content: str
    format: str = "markdown"
    created_by: str = ""
    created_at: str = ""

    @property
    def digest(self) -> str:
        payload = "\n".join((self.format, self.content))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderGuidanceTrackRecord:
    provider: str
    revision: ProviderGuidanceRevisionRecord
    scope_kind: str = "system"
    scope_key: str = ""
    is_mutable: bool = False


def skill_precedence(source_kind: str) -> int:
    order = {
        "custom": 30,
        "imported": 20,
        "builtin": 10,
    }
    return order.get(source_kind, 0)
