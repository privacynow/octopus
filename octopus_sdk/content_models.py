"""Canonical SDK content-domain models for runtime skills and provider guidance."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from octopus_sdk.providers import ProviderConfigRecord, coerce_provider_config
from octopus_sdk.skill_types import SkillRequirement, coerce_validation_spec


def _stable_json(value: object) -> str:
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
    requirements: list[SkillRequirement] = field(default_factory=list)
    provider_config: ProviderConfigRecord = field(default_factory=ProviderConfigRecord)
    files: tuple[SkillFileRecord, ...] = ()
    version_label: str = ""
    changelog: str = ""
    created_by: str = ""
    created_at: str = ""
    revision_id: str = ""
    status: str = "published"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requirements",
            [
                item
                if isinstance(item, SkillRequirement)
                else SkillRequirement(
                    key=str(item.get("key", "") or ""),
                    prompt=str(item.get("prompt", "") or ""),
                    help_url=(
                        None
                        if item.get("help_url") in (None, "")
                        else str(item.get("help_url"))
                    ),
                    validate=coerce_validation_spec(item.get("validate")),
                )
                for item in self.requirements
            ],
        )
        object.__setattr__(self, "provider_config", coerce_provider_config(self.provider_config))

    @property
    def digest(self) -> str:
        payload = "\n".join(
            (
                self.version_label,
                self.instruction_body,
                self.changelog,
                _stable_json([item.to_dict() for item in self.requirements]),
                _stable_json(self.provider_config.to_dict()),
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
    active_revision_id: str = ""
    published_revision_id: str = ""


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
    status: str = "published"
    runtime_available: bool = True
    has_unpublished_changes: bool = False


@dataclass(frozen=True)
class ProviderGuidanceRevisionRecord:
    content: str
    format: str = "markdown"
    created_by: str = ""
    created_at: str = ""
    revision_id: str = ""
    status: str = "published"

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
    active_revision_id: str = ""
    published_revision_id: str = ""


@dataclass(frozen=True)
class LifecycleApprovalRecord:
    record_id: str
    revision_id: str
    action: str
    actor: str = ""
    note: str = ""
    created_at: str = ""


def skill_precedence(source_kind: str) -> int:
    order = {
        "custom": 30,
        "imported": 20,
        "builtin": 10,
    }
    return order.get(source_kind, 0)
