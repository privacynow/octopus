"""Canonical runtime-skill package helpers and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath

import frontmatter
import yaml

from octopus_sdk.content_models import RuntimeSkillTrackRecord, SkillFileRecord
from octopus_sdk.providers import JsonValue, ProviderConfigRecord, coerce_provider_config
from octopus_sdk.runtime.skills import normalize_skill_kind
from octopus_sdk.skill_types import SkillRequirement, coerce_validation_spec

SKILL_MARKDOWN_FILE = "skill.md"
SKILL_REQUIRES_FILE = "requires.yaml"
SKILL_PROVIDER_FILES = {
    "claude": "claude.yaml",
    "codex": "codex.yaml",
}
SKILL_PROVIDER_FILE_SUFFIX = ".provider.yaml"
SKILL_RESERVED_FILES = frozenset({SKILL_MARKDOWN_FILE, SKILL_REQUIRES_FILE, *SKILL_PROVIDER_FILES.values()})
MAX_SKILL_FILE_COUNT = 16
MAX_SKILL_FILE_BYTES = 64 * 1024
MAX_SKILL_TOTAL_FILE_BYTES = 256 * 1024
MAX_SKILL_DOCUMENT_BYTES = 512 * 1024
SKILL_PACKAGE_SCHEMA_VERSION = 1
SKILL_PACKAGE_KIND = "octopus.skill"


@dataclass(frozen=True)
class SkillValidationProblem:
    code: str
    message: str
    field_path: str = ""
    severity: str = "error"


@dataclass(frozen=True)
class SkillPackageRecord:
    skill_name: str
    display_name: str
    description: str
    body: str
    skill_kind: str
    requirements: tuple[SkillRequirement, ...] = ()
    provider_config: ProviderConfigRecord = ProviderConfigRecord()
    files: tuple[SkillFileRecord, ...] = ()


def normalize_skill_document_format(value: object, *, default: str = "json") -> str:
    token = str(value or default or "json").strip().lower()
    if token in {"yml", "yaml"}:
        return "yaml"
    if token == "json":
        return "json"
    raise ValueError("Skill package format must be json or yaml.")


def _json_safe(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))


def default_skill_display_name(skill_name: str) -> str:
    return str(skill_name or "").strip().replace("-", " ").title()


def skill_requirement_keys(requirements: list[SkillRequirement]) -> tuple[str, ...]:
    return tuple(item.key for item in requirements if str(item.key or "").strip())


def coerce_skill_requirements(
    values: tuple[SkillRequirement, ...] | list[SkillRequirement] | list[Mapping[str, object]] | None,
) -> tuple[SkillRequirement, ...]:
    if not values:
        return ()
    requirements: list[SkillRequirement] = []
    for value in values:
        if isinstance(value, SkillRequirement):
            requirements.append(value)
            continue
        if not isinstance(value, Mapping):
            continue
        requirements.append(
            SkillRequirement(
                key=str(value.get("key", "") or ""),
                prompt=str(value.get("prompt", "") or ""),
                help_url=(
                    None
                    if value.get("help_url") in (None, "")
                    else str(value.get("help_url"))
                ),
                validate=coerce_validation_spec(value.get("validate")),
            )
        )
    return tuple(requirements)


def skill_provider_names(provider_config: Mapping[str, JsonValue] | ProviderConfigRecord) -> tuple[str, ...]:
    config = coerce_provider_config(provider_config)
    return tuple(
        provider
        for provider, value in sorted(config.items())
        if isinstance(value, dict) and value
    )


def skill_runtime_available(track: RuntimeSkillTrackRecord) -> bool:
    return bool(track.published_revision_id) or not track.is_mutable


def skill_has_unpublished_changes(track: RuntimeSkillTrackRecord) -> bool:
    return bool(track.published_revision_id) and track.published_revision_id != track.active_revision_id


def skill_content_type(relative_path: str | Path) -> str:
    suffix = Path(str(relative_path or "")).suffix.lower()
    if suffix == ".sh":
        return "text/x-shellscript"
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".md":
        return "text/markdown"
    return "text/plain"


def skill_provider_filename(provider_name: str) -> str:
    normalized = str(provider_name or "").strip().lower()
    if not normalized:
        return ""
    return SKILL_PROVIDER_FILES.get(normalized, f"{normalized}{SKILL_PROVIDER_FILE_SUFFIX}")


def skill_provider_name_for_path(relative_path: str | Path) -> str:
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or "/" in normalized:
        return ""
    for provider_name, filename in SKILL_PROVIDER_FILES.items():
        if filename == normalized:
            return provider_name
    if normalized.endswith(SKILL_PROVIDER_FILE_SUFFIX):
        return normalized[: -len(SKILL_PROVIDER_FILE_SUFFIX)].strip().lower()
    return ""


def is_reserved_skill_file_path(relative_path: str | Path) -> bool:
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or "/" in normalized:
        return False
    return normalized in SKILL_RESERVED_FILES or bool(skill_provider_name_for_path(normalized))


def load_skill_markdown(path: Path) -> tuple[dict[str, object], str]:
    post = frontmatter.load(str(path))
    return dict(post.metadata), post.content.strip()


def parse_skill_requirements_text(text: str) -> list[SkillRequirement]:
    if not str(text or "").strip():
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    credentials = data.get("credentials", [])
    if not isinstance(credentials, list):
        return []
    requirements: list[SkillRequirement] = []
    for item in credentials:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("key", "") or "").strip()
        prompt = str(item.get("prompt", "") or "").strip()
        if not key:
            continue
        requirements.append(
            SkillRequirement(
                key=key,
                prompt=prompt,
                help_url=(
                    None
                    if item.get("help_url") in (None, "")
                    else str(item.get("help_url"))
                ),
                validate=coerce_validation_spec(item.get("validate")),
            )
        )
    return requirements


def load_skill_requirements(path: Path) -> list[SkillRequirement]:
    if not path.is_file():
        return []
    return parse_skill_requirements_text(path.read_text(encoding="utf-8"))


def parse_provider_config_text(text: str) -> dict[str, JsonValue]:
    if not str(text or "").strip():
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def load_provider_config(path: Path) -> dict[str, JsonValue]:
    if not path.is_file():
        return {}
    return parse_provider_config_text(path.read_text(encoding="utf-8"))


def load_skill_provider_configs(path: Path) -> ProviderConfigRecord:
    configs: dict[str, JsonValue] = {}
    for provider_name, filename in sorted(SKILL_PROVIDER_FILES.items()):
        config = load_provider_config(path / filename)
        if config:
            configs[provider_name] = config
    for child in sorted(path.iterdir()):
        if not child.is_file():
            continue
        provider_name = skill_provider_name_for_path(child.name)
        if not provider_name or provider_name in configs:
            continue
        config = load_provider_config(child)
        if config:
            configs[provider_name] = config
    return coerce_provider_config(configs)


def normalize_skill_file(file_record: SkillFileRecord) -> SkillFileRecord:
    relative_path = str(file_record.relative_path or "").strip().replace("\\", "/")
    content_type = str(file_record.content_type or "").strip() or skill_content_type(relative_path)
    executable = bool(file_record.executable)
    if relative_path.endswith(".sh"):
        executable = True
    return SkillFileRecord(
        relative_path=relative_path,
        content_text=str(file_record.content_text or ""),
        content_type=content_type,
        executable=executable,
    )


def coerce_skill_files(values: tuple[SkillFileRecord, ...] | list[SkillFileRecord] | list[Mapping[str, object]] | None) -> tuple[SkillFileRecord, ...]:
    if not values:
        return ()
    files: list[SkillFileRecord] = []
    for value in values:
        if isinstance(value, SkillFileRecord):
            files.append(normalize_skill_file(value))
            continue
        if not isinstance(value, Mapping):
            continue
        files.append(
            normalize_skill_file(
                SkillFileRecord(
                    relative_path=str(value.get("relative_path", "") or ""),
                    content_text=str(value.get("content_text", "") or ""),
                    content_type=str(value.get("content_type", "") or ""),
                    executable=bool(value.get("executable")),
                )
            )
        )
    return tuple(sorted(files, key=lambda item: item.relative_path))


def load_skill_files(path: Path) -> tuple[SkillFileRecord, ...]:
    files: list[SkillFileRecord] = []
    for child in sorted(path.iterdir()):
        if not child.is_file() or is_reserved_skill_file_path(child.name):
            continue
        files.append(
            normalize_skill_file(
                SkillFileRecord(
                    relative_path=child.name,
                    content_text=child.read_text(encoding="utf-8"),
                    content_type=skill_content_type(child.name),
                    executable=child.suffix == ".sh",
                )
            )
        )
    return tuple(files)


def build_skill_virtual_files(track: RuntimeSkillTrackRecord) -> dict[str, str]:
    skill_md = (
        "---\n"
        f"name: {track.slug}\n"
        f"display_name: {track.display_name}\n"
        f"description: {track.description}\n"
        f"skill_kind: {normalize_skill_kind(track.revision.skill_kind)}\n"
        "---\n\n"
        f"{track.revision.instruction_body.rstrip()}\n"
    )
    files = {SKILL_MARKDOWN_FILE: skill_md}
    if track.revision.requirements:
        files[SKILL_REQUIRES_FILE] = yaml.safe_dump(
            {"credentials": [item.to_dict() for item in track.revision.requirements]},
            sort_keys=False,
        )
    for provider_name, config in sorted(track.revision.provider_config.items()):
        if isinstance(config, dict) and config:
            provider_file = skill_provider_filename(provider_name)
            if provider_file:
                files[provider_file] = yaml.safe_dump(config, sort_keys=False)
    for item in track.revision.files:
        files[item.relative_path] = item.content_text
    return files


def parse_skill_virtual_files(files: Mapping[str, str]) -> SkillPackageRecord:
    virtual_files = {str(path or "").strip().replace("\\", "/"): str(content or "") for path, content in files.items()}
    skill_markdown = virtual_files.get(SKILL_MARKDOWN_FILE, "")
    if not skill_markdown.strip():
        raise ValueError("Skill package must include skill.md.")
    post = frontmatter.loads(skill_markdown)
    metadata = dict(post.metadata)
    skill_name = str(metadata.get("name") or "").strip().lower()
    if not skill_name:
        raise ValueError("Skill package skill.md must declare a skill name.")
    requirements = coerce_skill_requirements(
        parse_skill_requirements_text(virtual_files.get(SKILL_REQUIRES_FILE, ""))
    )
    provider_config: dict[str, JsonValue] = {}
    for relative_path, content in sorted(virtual_files.items()):
        provider_name = skill_provider_name_for_path(relative_path)
        if not provider_name:
            continue
        config = parse_provider_config_text(content)
        if config:
            provider_config[provider_name] = config
    files_payload = coerce_skill_files(
        [
            {
                "relative_path": relative_path,
                "content_text": content,
                "content_type": skill_content_type(relative_path),
                "executable": str(relative_path).endswith(".sh"),
            }
            for relative_path, content in sorted(virtual_files.items())
            if relative_path and not is_reserved_skill_file_path(relative_path)
        ]
    )
    return SkillPackageRecord(
        skill_name=skill_name,
        display_name=str(metadata.get("display_name") or metadata.get("name") or default_skill_display_name(skill_name)).strip(),
        description=str(metadata.get("description") or ""),
        body=post.content.strip(),
        skill_kind=normalize_skill_kind(str(metadata.get("skill_kind") or metadata.get("kind") or "prompt")),
        requirements=requirements,
        provider_config=coerce_provider_config(provider_config),
        files=files_payload,
    )


def skill_package_from_track(track: RuntimeSkillTrackRecord) -> SkillPackageRecord:
    return SkillPackageRecord(
        skill_name=str(track.slug or "").strip().lower(),
        display_name=str(track.display_name or "").strip() or default_skill_display_name(track.slug),
        description=str(track.description or ""),
        body=str(track.revision.instruction_body or "").strip(),
        skill_kind=normalize_skill_kind(track.revision.skill_kind),
        requirements=coerce_skill_requirements(track.revision.requirements),
        provider_config=coerce_provider_config(track.revision.provider_config),
        files=coerce_skill_files(track.revision.files),
    )


def normalize_skill_package(package: SkillPackageRecord) -> SkillPackageRecord:
    skill_name = str(package.skill_name or "").strip().lower()
    return SkillPackageRecord(
        skill_name=skill_name,
        display_name=str(package.display_name or "").strip() or default_skill_display_name(skill_name),
        description=str(package.description or ""),
        body=str(package.body or "").strip(),
        skill_kind=normalize_skill_kind(package.skill_kind or "prompt"),
        requirements=coerce_skill_requirements(package.requirements),
        provider_config=coerce_provider_config(package.provider_config),
        files=coerce_skill_files(package.files),
    )


def skill_package_data(package: SkillPackageRecord) -> dict[str, object]:
    normalized = normalize_skill_package(package)
    return {
        "name": normalized.skill_name,
        "display_name": normalized.display_name,
        "description": normalized.description,
        "skill_kind": normalized.skill_kind,
        "body": normalized.body,
        "requirements": [item.to_dict() for item in normalized.requirements],
        "provider_config": normalized.provider_config.to_dict(),
        "files": [
            {
                "path": item.relative_path,
                "content_type": item.content_type,
                "executable": item.executable,
                "content": item.content_text,
            }
            for item in normalized.files
        ],
    }


def skill_package_hash(package: SkillPackageRecord) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(skill_package_data(package)).encode("utf-8")
    ).hexdigest()


def skill_package_document(
    package: SkillPackageRecord,
    *,
    exported_at: str = "",
    source: str = "registry",
    revision_scope: str = "draft",
    revision_id: str = "",
) -> dict[str, object]:
    normalized = normalize_skill_package(package)
    return {
        "schema_version": SKILL_PACKAGE_SCHEMA_VERSION,
        "kind": SKILL_PACKAGE_KIND,
        "skill": skill_package_data(normalized),
        "metadata": {
            "source": str(source or "registry"),
            "revision_scope": str(revision_scope or "draft"),
            "revision_id": str(revision_id or ""),
            "exported_at": str(exported_at or ""),
            "normalized_hash": skill_package_hash(normalized),
        },
    }


def skill_document_from_track(
    track: RuntimeSkillTrackRecord,
    *,
    exported_at: str = "",
    source: str = "registry",
    revision_scope: str = "draft",
    revision_id: str = "",
) -> dict[str, object]:
    return skill_package_document(
        skill_package_from_track(track),
        exported_at=exported_at,
        source=source,
        revision_scope=revision_scope,
        revision_id=revision_id,
    )


def _skill_package_from_skill_mapping(raw_skill: Mapping[str, object]) -> SkillPackageRecord:
    files: list[Mapping[str, object]] = []
    for item in raw_skill.get("files") or []:
        if not isinstance(item, Mapping):
            continue
        files.append(
            {
                "relative_path": item.get("path", item.get("relative_path", "")),
                "content_text": item.get("content", item.get("content_text", "")),
                "content_type": item.get("content_type", ""),
                "executable": item.get("executable", False),
            }
        )
    return normalize_skill_package(
        SkillPackageRecord(
            skill_name=str(raw_skill.get("name", raw_skill.get("skill_name", "")) or "").strip().lower(),
            display_name=str(raw_skill.get("display_name", "") or "").strip(),
            description=str(raw_skill.get("description", "") or ""),
            body=str(raw_skill.get("body", "") or ""),
            skill_kind=str(raw_skill.get("skill_kind", raw_skill.get("kind", "prompt")) or "prompt"),
            requirements=coerce_skill_requirements(raw_skill.get("requirements") or ()),
            provider_config=coerce_provider_config(raw_skill.get("provider_config") or {}),
            files=coerce_skill_files(files),
        )
    )


def skill_package_from_document(value: object) -> SkillPackageRecord:
    if not isinstance(value, Mapping):
        raise ValueError("Skill package document must be a JSON/YAML object.")
    schema_version = int(value.get("schema_version") or 0)
    if schema_version != SKILL_PACKAGE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported skill package schema_version {schema_version}; expected {SKILL_PACKAGE_SCHEMA_VERSION}."
        )
    kind = str(value.get("kind", "") or "").strip()
    if kind != SKILL_PACKAGE_KIND:
        raise ValueError(f"Skill package kind must be {SKILL_PACKAGE_KIND!r}.")
    raw_skill = value.get("skill")
    if not isinstance(raw_skill, Mapping):
        raise ValueError("Skill package document must include a skill object.")
    package = _skill_package_from_skill_mapping(raw_skill)
    problems = validate_skill_package(
        skill_name=package.skill_name,
        display_name=package.display_name,
        body=package.body,
        requirements=list(package.requirements),
        provider_config=package.provider_config,
        files=package.files,
    )
    if problems:
        raise ValueError(problems[0].message)
    return package


def skill_document_from_text(text: str | bytes, *, format: str = "json") -> dict[str, object]:
    if isinstance(text, bytes):
        raw_text = text.decode("utf-8")
    else:
        raw_text = str(text or "")
    if not raw_text.strip():
        raise ValueError("Skill package document is empty.")
    if len(raw_text.encode("utf-8")) > MAX_SKILL_DOCUMENT_BYTES:
        raise ValueError(f"Skill package document exceeds the {MAX_SKILL_DOCUMENT_BYTES // 1024} KB limit.")
    normalized_format = normalize_skill_document_format(format)
    try:
        if normalized_format == "json":
            data = json.loads(raw_text)
        else:
            data = yaml.safe_load(raw_text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Skill package document is not valid {normalized_format}.") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Skill package document must be a JSON/YAML object.")
    package = skill_package_from_document(data)
    return skill_package_document(
        package,
        exported_at=str((data.get("metadata") or {}).get("exported_at", "") if isinstance(data.get("metadata"), Mapping) else ""),
        source=str((data.get("metadata") or {}).get("source", "registry") if isinstance(data.get("metadata"), Mapping) else "registry"),
        revision_scope=str((data.get("metadata") or {}).get("revision_scope", "draft") if isinstance(data.get("metadata"), Mapping) else "draft"),
        revision_id=str((data.get("metadata") or {}).get("revision_id", "") if isinstance(data.get("metadata"), Mapping) else ""),
    )


def parse_skill_package_document(text: str | bytes, *, format: str = "json") -> SkillPackageRecord:
    return skill_package_from_document(skill_document_from_text(text, format=format))


def skill_document_to_text(document: Mapping[str, object], *, format: str = "json") -> str:
    package = skill_package_from_document(document)
    metadata = document.get("metadata") if isinstance(document, Mapping) else {}
    stable = skill_package_document(
        package,
        exported_at=str(metadata.get("exported_at", "") if isinstance(metadata, Mapping) else ""),
        source=str(metadata.get("source", "registry") if isinstance(metadata, Mapping) else "registry"),
        revision_scope=str(metadata.get("revision_scope", "draft") if isinstance(metadata, Mapping) else "draft"),
        revision_id=str(metadata.get("revision_id", "") if isinstance(metadata, Mapping) else ""),
    )
    normalized_format = normalize_skill_document_format(format)
    if normalized_format == "json":
        return json.dumps(stable, indent=2, sort_keys=True) + "\n"
    return yaml.safe_dump(stable, sort_keys=False, allow_unicode=False)


def skill_package_document_to_text(
    package: SkillPackageRecord,
    *,
    format: str = "json",
    exported_at: str = "",
    source: str = "registry",
    revision_scope: str = "draft",
    revision_id: str = "",
) -> str:
    return skill_document_to_text(
        skill_package_document(
            package,
            exported_at=exported_at,
            source=source,
            revision_scope=revision_scope,
            revision_id=revision_id,
        ),
        format=format,
    )


def _safe_relative_path(relative_path: str) -> bool:
    text = str(relative_path or "").strip().replace("\\", "/")
    if not text or text.startswith("/"):
        return False
    try:
        parts = PurePosixPath(text).parts
    except Exception:
        return False
    if not parts:
        return False
    return not any(part in {"", ".", ".."} for part in parts)


def validate_skill_package(
    *,
    skill_name: str,
    display_name: str,
    body: str,
    requirements: list[SkillRequirement],
    provider_config: Mapping[str, JsonValue] | ProviderConfigRecord,
    files: tuple[SkillFileRecord, ...] | list[SkillFileRecord],
) -> tuple[SkillValidationProblem, ...]:
    problems: list[SkillValidationProblem] = []
    if not str(skill_name or "").strip():
        problems.append(
            SkillValidationProblem(
                code="skill_name_required",
                field_path="name",
                message="Skill name cannot be blank.",
            )
        )
    if not str(display_name or "").strip():
        problems.append(
            SkillValidationProblem(
                code="display_name_required",
                field_path="display_name",
                message="Display name cannot be blank.",
            )
        )
    if not str(body or "").strip():
        problems.append(
            SkillValidationProblem(
                code="body_required",
                field_path="body",
                message="Draft instructions cannot be empty.",
            )
        )

    seen_requirement_keys: set[str] = set()
    for index, requirement in enumerate(requirements):
        key = str(requirement.key or "").strip()
        prompt = str(requirement.prompt or "").strip()
        if not key:
            problems.append(
                SkillValidationProblem(
                    code="requirement_key_required",
                    field_path=f"requirements[{index}].key",
                    message="Requirement keys cannot be blank.",
                )
            )
        elif key in seen_requirement_keys:
            problems.append(
                SkillValidationProblem(
                    code="requirement_key_duplicate",
                    field_path=f"requirements[{index}].key",
                    message=f"Requirement key '{key}' is duplicated.",
                )
            )
        else:
            seen_requirement_keys.add(key)
        if not prompt:
            problems.append(
                SkillValidationProblem(
                    code="requirement_prompt_required",
                    field_path=f"requirements[{index}].prompt",
                    message=f"Requirement '{key or index + 1}' needs a prompt.",
                )
            )

    config = coerce_provider_config(provider_config)
    for provider_name, value in config.items():
        normalized_name = str(provider_name or "").strip()
        if not normalized_name:
            problems.append(
                SkillValidationProblem(
                    code="provider_name_required",
                    field_path="provider_config",
                    message="Provider config names cannot be blank.",
                )
            )
            continue
        if not isinstance(value, dict):
            problems.append(
                SkillValidationProblem(
                    code="provider_config_invalid",
                    field_path=f"provider_config.{normalized_name}",
                    message=f"Provider config for '{normalized_name}' must be a JSON object.",
                )
            )

    normalized_files = coerce_skill_files(files)
    if len(normalized_files) > MAX_SKILL_FILE_COUNT:
        problems.append(
            SkillValidationProblem(
                code="too_many_files",
                field_path="files",
                message=f"Skill packages may include at most {MAX_SKILL_FILE_COUNT} files.",
            )
        )
    seen_paths: set[str] = set()
    total_bytes = 0
    for index, file_record in enumerate(normalized_files):
        relative_path = file_record.relative_path
        if not _safe_relative_path(relative_path):
            problems.append(
                SkillValidationProblem(
                    code="file_path_invalid",
                    field_path=f"files[{index}].relative_path",
                    message=f"File path '{relative_path or '<blank>'}' must be a safe relative path.",
                )
            )
        elif relative_path in SKILL_RESERVED_FILES:
            problems.append(
                SkillValidationProblem(
                    code="file_path_reserved",
                    field_path=f"files[{index}].relative_path",
                    message=f"File path '{relative_path}' is reserved by the skill package format.",
                )
            )
        elif relative_path in seen_paths:
            problems.append(
                SkillValidationProblem(
                    code="file_path_duplicate",
                    field_path=f"files[{index}].relative_path",
                    message=f"File path '{relative_path}' is duplicated.",
                )
            )
        else:
            seen_paths.add(relative_path)

        file_bytes = len(file_record.content_text.encode("utf-8"))
        total_bytes += file_bytes
        if file_bytes > MAX_SKILL_FILE_BYTES:
            problems.append(
                SkillValidationProblem(
                    code="file_too_large",
                    field_path=f"files[{index}].content_text",
                    message=f"File '{relative_path}' exceeds the {MAX_SKILL_FILE_BYTES // 1024} KB limit.",
                )
            )
        if file_record.executable and not relative_path.endswith(".sh"):
            problems.append(
                SkillValidationProblem(
                    code="file_executable_invalid",
                    field_path=f"files[{index}].executable",
                    message=f"Only shell scripts may be marked executable ('{relative_path}').",
                )
            )
    if total_bytes > MAX_SKILL_TOTAL_FILE_BYTES:
        problems.append(
            SkillValidationProblem(
                code="file_total_too_large",
                field_path="files",
                message=f"Skill package files exceed the {MAX_SKILL_TOTAL_FILE_BYTES // 1024} KB total limit.",
            )
        )
    return tuple(problems)


def publish_ready(
    *,
    skill_name: str,
    display_name: str,
    body: str,
    requirements: list[SkillRequirement],
    provider_config: Mapping[str, JsonValue] | ProviderConfigRecord,
    files: tuple[SkillFileRecord, ...] | list[SkillFileRecord],
) -> bool:
    return not validate_skill_package(
        skill_name=skill_name,
        display_name=display_name,
        body=body,
        requirements=requirements,
        provider_config=provider_config,
        files=files,
    )
