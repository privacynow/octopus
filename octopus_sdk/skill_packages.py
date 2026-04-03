"""Canonical runtime-skill package helpers and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import frontmatter
import yaml

from octopus_sdk.content_models import RuntimeSkillTrackRecord, SkillFileRecord
from octopus_sdk.providers import JsonValue, ProviderConfigRecord, coerce_provider_config
from octopus_sdk.skill_types import SkillRequirement, coerce_validation_spec

SKILL_MARKDOWN_FILE = "skill.md"
SKILL_REQUIRES_FILE = "requires.yaml"
SKILL_PROVIDER_FILES = {
    "claude": "claude.yaml",
    "codex": "codex.yaml",
}
SKILL_RESERVED_FILES = frozenset(
    {SKILL_MARKDOWN_FILE, SKILL_REQUIRES_FILE, *SKILL_PROVIDER_FILES.values()}
)
MAX_SKILL_FILE_COUNT = 16
MAX_SKILL_FILE_BYTES = 64 * 1024
MAX_SKILL_TOTAL_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class SkillValidationProblem:
    code: str
    message: str
    field_path: str = ""
    severity: str = "error"


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
        if not child.is_file() or child.name in SKILL_RESERVED_FILES:
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
            provider_file = SKILL_PROVIDER_FILES.get(provider_name)
            if provider_file:
                files[provider_file] = yaml.safe_dump(config, sort_keys=False)
    for item in track.revision.files:
        files[item.relative_path] = item.content_text
    return files


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
