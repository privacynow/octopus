"""Legacy skill compatibility helpers.

This module is not authoritative application architecture. Runtime code must
use the content store, skill catalog service, provider guidance service, and
credential subsystem directly.

The remaining helpers here exist only for compatibility tests and isolated
filesystem parsing of built-in/custom skill fixtures.
"""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from app.credential_service import get_credential_service
from app.credential_store import derive_credential_encryption_key
from app.credential_store_postgres import PostgresCredentialStore
from app.credential_validation import validate_credential
from octopus_sdk.content_models import RuntimeSkillTrackRecord, SkillFileRecord, SkillRevisionRecord
from octopus_sdk.identity import filesystem_component_for_key, parse_actor_key

from octopus_sdk.providers import (
    CredentialEnvRecord,
    PreflightContext,
    ProviderConfigRecord,
    RunContext,
)
from octopus_sdk.provider_guidance_service import (
    PROMPT_SIZE_WARNING_THRESHOLD,
    ProviderGuidanceService as SdkProviderGuidanceService,
)
from app.runtime_skill_paths import BUILTIN_SKILL_CATALOG_DIR
from octopus_sdk.skill_packages import (
    load_skill_markdown as _runtime_load_skill_markdown,
    parse_provider_config_text,
    parse_skill_requirements_text,
)
from octopus_sdk.skill_types import SkillMeta, SkillRequirement


CATALOG_DIR = BUILTIN_SKILL_CATALOG_DIR
CUSTOM_DIR = Path.home() / ".config" / "octopus-agent" / "skills" / "custom"


# ---------------------------------------------------------------------------
# Filesystem compatibility resolution: custom > built-in catalog
# ---------------------------------------------------------------------------

def _resolve_skill(name: str) -> tuple[Path, str] | None:
    """Resolve a compatibility skill directory custom or built-in assets."""

    # 1. Custom compatibility override
    custom = CUSTOM_DIR / name
    if custom.is_dir() and (custom / "skill.md").is_file():
        try:
            _load_skill_md(custom / "skill.md")
            return custom, "custom"
        except ValueError:
            pass

    # 2. Built-in catalog
    catalog = CATALOG_DIR / name
    if catalog.is_dir() and (catalog / "skill.md").is_file():
        try:
            _load_skill_md(catalog / "skill.md")
            return catalog, "catalog"
        except ValueError:
            pass

    return None


def _skill_dir(name: str) -> Path | None:
    """Resolve skill directory (path only). See _resolve_skill for tier info."""
    result = _resolve_skill(name)
    return result[0] if result else None


# ---------------------------------------------------------------------------
# Frontmatter parsing (using python-frontmatter)
# ---------------------------------------------------------------------------

def _load_skill_md(path: Path) -> tuple[dict, str]:
    """Parse a skill.md file. Returns (metadata_dict, body).

    Raises ValueError on malformed content so callers can skip gracefully.
    """
    try:
        return _runtime_load_skill_markdown(path)
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}") from e


# ---------------------------------------------------------------------------
# requires.yaml parsing (using PyYAML)
# ---------------------------------------------------------------------------

def _parse_requires_yaml(text: str) -> list[SkillRequirement]:
    """Parse a requires.yaml file and return SkillRequirements.

    Returns empty list on malformed YAML instead of crashing.
    """
    try:
        return list(parse_skill_requirements_text(text))
    except Exception:
        return []


def get_skill_requirements(name: str) -> list[SkillRequirement]:
    """Load credential requirements the compatibility filesystem view."""
    skill = _skill_dir(name)
    if not skill:
        return []
    requires_file = skill / "requires.yaml"
    if not requires_file.is_file():
        return []
    return _parse_requires_yaml(requires_file.read_text(encoding="utf-8"))


def check_credentials(name: str, user_credentials: dict[str, dict[str, str]]) -> list[SkillRequirement]:
    """Return unsatisfied credential requirements for *name* given stored credentials."""
    requirements = get_skill_requirements(name)
    skill_creds = user_credentials.get(name, {})
    return get_credential_service().missing_requirements(requirements, skill_creds)


# ---------------------------------------------------------------------------
# Per-user credential storage (using cryptography.fernet)
# ---------------------------------------------------------------------------

def derive_fernet_key(telegram_token: str) -> bytes:
    """Derive a Fernet-compatible key the bot token using HKDF."""
    return derive_credential_encryption_key(telegram_token)


# Keep old name as alias for backward compatibility in tests/handlers
derive_encryption_key = derive_fernet_key


def _encrypt(value: str, key: bytes) -> str:
    """Encrypt a string using Fernet (authenticated symmetric encryption)."""
    f = Fernet(key)
    return f.encrypt(value.encode()).decode()


def _decrypt(encoded: str, key: bytes) -> str:
    """Decrypt a Fernet token back to a string. Raises on tampered data."""
    f = Fernet(key)
    return f.decrypt(encoded.encode()).decode()


def _credential_store(key: bytes) -> PostgresCredentialStore:
    database_url = os.environ.get("OCTOPUS_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("OCTOPUS_DATABASE_URL must be set for credential compatibility helpers")
    return PostgresCredentialStore(database_url, encryption_key=key)

def load_user_credentials(data_dir: Path, actor_key: str, key: bytes) -> dict[str, dict[str, str]]:
    """Load and decrypt per-user credentials.

    Returns ``{skill_name: {cred_key: value, ...}, ...}``.
    """
    del data_dir
    return _credential_store(key).load(parse_actor_key(actor_key))


def save_user_credential(
    data_dir: Path,
    actor_key: str,
    skill_name: str,
    cred_key: str,
    value: str,
    key: bytes,
) -> None:
    """Encrypt and save a single credential for a user."""
    del data_dir
    _credential_store(key).save(
        parse_actor_key(actor_key),
        skill_name,
        cred_key,
        value,
    )


def delete_user_credentials(
    data_dir: Path,
    actor_key: str,
    key: bytes,
    skill_name: str | None = None,
) -> list[str]:
    """Delete stored credentials for a user.

    If skill_name is given, delete only that skill's credentials.
    Otherwise delete all credentials.
    Returns list of skill names whose credentials were removed.
    """
    del data_dir
    return _credential_store(key).delete(
        parse_actor_key(actor_key),
        skill_name,
    )


def build_credential_env(
    active_skills: list[str],
    user_credentials: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Flatten per-skill credentials into a single env-var dict for active skills."""
    return get_credential_service().build_env(active_skills, user_credentials)


# ---------------------------------------------------------------------------
# Catalog discovery
# ---------------------------------------------------------------------------

def load_catalog() -> dict[str, SkillMeta]:
    """Discover built-in and custom compatibility skills."""

    catalog: dict[str, SkillMeta] = {}

    import logging
    _log = logging.getLogger(__name__)

    # 1. Built-in catalog (lowest priority)
    if CATALOG_DIR.is_dir():
        for skill_dir in sorted(CATALOG_DIR.iterdir()):
            skill_file = skill_dir / "skill.md"
            if not skill_file.is_file():
                continue
            try:
                meta, _ = _load_skill_md(skill_file)
            except ValueError as e:
                _log.warning("Skipping malformed skill %s: %s", skill_dir.name, e)
                continue
            name = skill_dir.name
            catalog[name] = SkillMeta(
                name=name,
                display_name=meta.get("display_name", name),
                description=meta.get("description", ""),
                is_custom=False,
            )

    # 2. Custom skills (highest priority)
    if CUSTOM_DIR.is_dir():
        for skill_dir in sorted(CUSTOM_DIR.iterdir()):
            skill_file = skill_dir / "skill.md"
            if not skill_file.is_file():
                continue
            try:
                meta, _ = _load_skill_md(skill_file)
            except ValueError as e:
                _log.warning("Skipping malformed custom skill %s: %s", skill_dir.name, e)
                continue
            name = skill_dir.name
            catalog[name] = SkillMeta(
                name=name,
                display_name=meta.get("display_name", name),
                description=meta.get("description", ""),
                is_custom=True,
            )

    return catalog


def get_skill_instructions(name: str) -> str:
    """Read the markdown body (minus YAML frontmatter) a skill's skill.md."""
    skill = _skill_dir(name)
    if not skill:
        return ""
    try:
        _, body = _load_skill_md(skill / "skill.md")
    except ValueError:
        return ""
    return body


def get_provider_config_digest(skill_names: list[str], provider_name: str = "") -> str:
    """Return a SHA-256 digest of compatibility provider config for the given skills."""
    providers = (provider_name,) if provider_name else ("claude", "codex")
    parts: list[str] = []
    for name in sorted(skill_names):
        if _skill_dir(name) is None:
            continue
        for provider in providers:
            config = load_provider_yaml(name, provider)
            if config:
                parts.append(f"{name}/{provider}:{json.dumps(config, sort_keys=True, separators=(',', ':'))}")
    if not parts:
        return ""
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def get_skill_digests(skill_names: list[str]) -> dict[str, str]:
    """Return {name: filesystem_digest} for each compatibility-resolved skill."""
    digests: dict[str, str] = {}
    for name in skill_names:
        if (skill := _skill_dir(name)) is not None:
            payload = hashlib.sha256()
            for child in sorted(skill.rglob("*")):
                if not child.is_file():
                    continue
                payload.update(child.relative_to(skill).as_posix().encode())
                payload.update(b"\0")
                payload.update(child.read_bytes())
            digests[name] = payload.hexdigest()
    return digests


# ---------------------------------------------------------------------------
# Provider YAML parsing (using PyYAML)
# ---------------------------------------------------------------------------

def _resolve_placeholders(obj, env: dict[str, str]):
    """Recursively replace ${VAR} placeholders in strings with values env."""
    if isinstance(obj, str):
        def replacer(m):
            return env.get(m.group(1), m.group(0))
        return re.sub(r'\$\{(\w+)\}', replacer, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_placeholders(v, env) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_placeholders(item, env) for item in obj]
    return obj


def load_provider_yaml(name: str, provider: str) -> dict:
    """Load and parse claude.yaml or codex.yaml for a skill.

    Returns empty dict on malformed YAML instead of crashing.
    """
    skill = _skill_dir(name)
    if not skill:
        return {}
    yaml_file = skill / f"{provider}.yaml"
    if not yaml_file.is_file():
        return {}
    try:
        return parse_provider_config_text(yaml_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_provider_config(
    provider: str,
    skill_names: list[str],
    credential_env: dict[str, str],
) -> dict:
    return _compat_guidance_service().provider_config(
        provider,
        skill_names,
        CredentialEnvRecord(dict(credential_env or {})),
    ).to_dict()


def build_capability_summary(provider: str, skill_names: list[str]) -> str:
    """Build a human-readable summary of provider-specific capabilities for PreflightContext."""
    return _compat_guidance_service().capability_summary(provider, skill_names)


def _compat_track_files(skill_dir: Path) -> tuple[SkillFileRecord, ...]:
    files: list[SkillFileRecord] = []
    for child in sorted(skill_dir.rglob("*")):
        if not child.is_file():
            continue
        relative_path = child.relative_to(skill_dir).as_posix()
        if relative_path in {"skill.md", "requires.yaml", "claude.yaml", "codex.yaml"}:
            continue
        content_type = "text/x-shellscript" if child.suffix == ".sh" else "text/plain"
        files.append(
            SkillFileRecord(
                relative_path=relative_path,
                content_text=child.read_text(encoding="utf-8"),
                content_type=content_type,
                executable=os.access(child, os.X_OK),
            )
        )
    return tuple(files)


def _compat_runtime_track(name: str) -> RuntimeSkillTrackRecord | None:
    resolved = _resolve_skill(name)
    if resolved is None:
        return None
    skill_dir, source = resolved
    try:
        meta, body = _load_skill_md(skill_dir / "skill.md")
    except ValueError:
        return None
    provider_config = {}
    for provider in ("claude", "codex"):
        config = load_provider_yaml(name, provider)
        if config:
            provider_config[provider] = config
    return RuntimeSkillTrackRecord(
        slug=name,
        display_name=str(meta.get("display_name", name) or name),
        description=str(meta.get("description", "") or ""),
        source_kind="custom" if source == "custom" else "builtin",
        source_uri=str(skill_dir),
        revision=SkillRevisionRecord(
            instruction_body=body,
            skill_kind=str(meta.get("skill_kind", "prompt") or "prompt"),
            requirements=get_skill_requirements(name),
            provider_config=provider_config,
            files=_compat_track_files(skill_dir),
        ),
        visibility="private" if source == "custom" else "shared",
        is_mutable=(source == "custom"),
    )


class _CompatCatalogService:
    def catalog(self) -> dict[str, SkillMeta]:
        return load_catalog()

    def resolve_runtime_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None:
        return _compat_runtime_track(skill_name)

    def filter_resolvable(self, names: list[str]) -> list[str]:
        return [name for name in names if self.resolve_runtime_track(name) is not None]


class _CompatContentStore:
    def get_provider_guidance(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ):
        del provider_name, scope_kind, scope_key
        return None

    def resolve_provider_guidance(
        self,
        provider_name: str,
        *,
        instance_key: str = "",
    ):
        del provider_name, instance_key
        return None


def _compat_guidance_service() -> SdkProviderGuidanceService:
    from app.storage import list_sessions, load_session

    return SdkProviderGuidanceService(
        catalog_service=_CompatCatalogService(),
        content_store=_CompatContentStore(),
        list_sessions=list_sessions,
        load_session=load_session,
    )


def build_system_prompt(role: str, skill_names: list[str]) -> str:
    return _compat_guidance_service().system_prompt(role, skill_names)


def build_preflight_system_prompt(role: str, skill_names: list[str]) -> str:
    return _compat_guidance_service().preflight_prompt(role, skill_names)


def check_prompt_size(role: str, active_skills: list[str]) -> str | None:
    return _compat_guidance_service().prompt_size_warning(role, active_skills)


def estimate_prompt_size(role: str, current_skills: list[str], new_skill: str) -> tuple[int, bool]:
    return _compat_guidance_service().estimate_prompt_size(role, current_skills, new_skill)


def check_prompt_size_cross_chat(
    data_dir: Path,
    skill_name: str,
    provider_name: str,
    provider_state_factory,
    approval_mode: str,
) -> list[str]:
    return _compat_guidance_service().check_prompt_size_cross_chat(
        data_dir,
        skill_name,
        provider_name,
        provider_state_factory,
        approval_mode,
    )

# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def build_run_context(
    role: str,
    active_skills: list[str],
    extra_dirs: list[str],
    provider_name: str = "",
    credential_env: CredentialEnvRecord | dict[str, str] | None = None,
    working_dir: str = "",
    file_policy: str = "",
    effective_model: str = "",
) -> RunContext:
    cred_env = CredentialEnvRecord(dict(credential_env or {}))
    return _compat_guidance_service().build_run_context(
        role,
        active_skills,
        extra_dirs,
        provider_name=provider_name,
        credential_env=cred_env,
        working_dir=working_dir,
        file_policy=file_policy,
        effective_model=effective_model,
    )


def build_preflight_context(
    role: str,
    active_skills: list[str],
    extra_dirs: list[str],
    provider_name: str = "",
    working_dir: str = "",
    file_policy: str = "",
    effective_model: str = "",
) -> PreflightContext:
    return _compat_guidance_service().build_preflight_context(
        role,
        active_skills,
        extra_dirs,
        provider_name=provider_name,
        working_dir=working_dir,
        file_policy=file_policy,
        effective_model=effective_model,
    )


# ---------------------------------------------------------------------------
# Codex script staging
# ---------------------------------------------------------------------------

def stage_codex_scripts(
    data_dir: Path,
    conversation_key: str,
    active_skills: list[str],
) -> Path | None:
    return _compat_guidance_service().stage_codex_scripts(
        data_dir,
        str(conversation_key),
        active_skills,
    )


def cleanup_codex_scripts(data_dir: Path, conversation_key: str) -> None:
    _compat_guidance_service().cleanup_codex_scripts(data_dir, str(conversation_key))


# ---------------------------------------------------------------------------
# Scaffold and validation
# ---------------------------------------------------------------------------

def scaffold_skill(name: str) -> Path:
    """Create a new custom skill directory with a template skill.md.

    Returns the path to the created directory.
    Raises ValueError if a skill with that name already exists.
    """
    if not re.match(r'^[a-z][a-z0-9-]*$', name):
        raise ValueError(f"Skill name must be lowercase letters, digits, and hyphens: {name}")

    catalog = load_catalog()
    if name in catalog:
        raise ValueError(f"Skill '{name}' already exists")

    skill_dir = CUSTOM_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    display_name = name.replace("-", " ").title()
    (skill_dir / "skill.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"display_name: {display_name}\n"
        f"description: Custom skill\n"
        f"---\n\n"
        f"Add your instructions here.\n",
        encoding="utf-8",
    )

    return skill_dir


def filter_resolvable_skills(names: list[str]) -> list[str]:
    """Return only skills that currently resolve to a valid directory."""
    return [n for n in names if _skill_dir(n) is not None]


def validate_active_skills(
    skill_names: list[str],
    user_id: str = "",
    data_dir: Path | None = None,
    encryption_key: bytes | None = None,
) -> list[str]:
    """Validate active skills: catalog presence + credential satisfaction.

    Returns list of error strings.  Pure/read-only — does not mutate state.
    """
    catalog = load_catalog()
    errors: list[str] = []
    for name in skill_names:
        if name not in catalog:
            errors.append(f"Active skill '{name}' not found in catalog")

    # Check credential satisfaction if we have user context
    if user_id and data_dir and encryption_key:
        user_creds = load_user_credentials(data_dir, user_id, encryption_key)
        for name in skill_names:
            if name not in catalog:
                continue
            missing = check_credentials(name, user_creds)
            if missing:
                keys = ", ".join(r.key for r in missing)
                errors.append(f"Skill '{name}' missing credentials: {keys}")

    return errors
