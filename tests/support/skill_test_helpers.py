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
from octopus_sdk.identity import filesystem_component_for_key, parse_actor_key

from octopus_sdk.providers import (
    CredentialEnvRecord,
    PreflightContext,
    ProviderConfigRecord,
    RunContext,
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
    """Read provider YAML for each active skill, merge, resolve placeholders.

    Claude: {mcp_servers: {...}, allowed_tools: [...], disallowed_tools: [...]}
    Codex:  {sandbox: "...", scripts: [...], config_overrides: [...]}
    """
    if provider == "claude":
        mcp_servers: dict = {}
        allowed_tools: list[str] = []
        disallowed_tools: list[str] = []
        for name in skill_names:
            raw = load_provider_yaml(name, "claude")
            if not raw:
                continue
            if "mcp_servers" in raw and isinstance(raw["mcp_servers"], dict):
                mcp_servers.update(raw["mcp_servers"])
            if "allowed_tools" in raw and isinstance(raw["allowed_tools"], list):
                allowed_tools.extend(raw["allowed_tools"])
            if "disallowed_tools" in raw and isinstance(raw["disallowed_tools"], list):
                disallowed_tools.extend(raw["disallowed_tools"])
        config: dict = {}
        if mcp_servers:
            config["mcp_servers"] = mcp_servers
        if allowed_tools:
            config["allowed_tools"] = allowed_tools
        if disallowed_tools:
            config["disallowed_tools"] = disallowed_tools
        return _resolve_placeholders(config, credential_env) if config else {}

    elif provider == "codex":
        sandbox: str = ""
        scripts: list = []
        config_overrides: list[str] = []
        for name in skill_names:
            raw = load_provider_yaml(name, "codex")
            if not raw:
                continue
            if "sandbox" in raw and not sandbox:
                sandbox = str(raw["sandbox"])
            if "scripts" in raw and isinstance(raw["scripts"], list):
                scripts.extend(raw["scripts"])
            if "config_overrides" in raw and isinstance(raw["config_overrides"], list):
                config_overrides.extend(raw["config_overrides"])
        config = {}
        if sandbox:
            config["sandbox"] = sandbox
        if scripts:
            config["scripts"] = scripts
        if config_overrides:
            config["config_overrides"] = config_overrides
        return _resolve_placeholders(config, credential_env) if config else {}

    return {}


def build_capability_summary(provider: str, skill_names: list[str]) -> str:
    """Build a human-readable summary of provider-specific capabilities for PreflightContext."""
    lines: list[str] = []
    for name in skill_names:
        raw = load_provider_yaml(name, provider)
        if not raw:
            continue
        if provider == "claude":
            if "mcp_servers" in raw:
                servers = raw["mcp_servers"]
                if isinstance(servers, dict):
                    for sname in servers:
                        lines.append(f"MCP server: {sname} ({name})")
            if "allowed_tools" in raw:
                for t in raw["allowed_tools"]:
                    lines.append(f"Allowed tool: {t}")
        elif provider == "codex":
            if "scripts" in raw:
                for s in raw["scripts"]:
                    sname = s if isinstance(s, str) else s.get("name", "?")
                    lines.append(f"Script: {sname} ({name})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt composition
# ---------------------------------------------------------------------------

def build_system_prompt(role: str, skill_names: list[str]) -> str:
    """Compose role + skill instructions into a single text block."""
    parts: list[str] = []

    if role:
        # Short noun phrases (e.g. "senior Python engineer") get wrapped.
        # Rich content (multi-line, or already a sentence/instruction) is used verbatim.
        stripped = role.strip()
        lower = stripped.lower()
        is_sentence = any(lower.startswith(p) for p in ("you are", "you're", "act as", "as a"))
        if "\n" in stripped or is_sentence:
            parts.append(stripped + "\n")
        else:
            parts.append(f"You are a {stripped}.\n")

    catalog = load_catalog()
    available = ", ".join(sorted(catalog)) or "none"
    active = ", ".join(skill_names) or "none"
    if catalog or skill_names:
        parts.append(
            "## Octopus Runtime Skill State\n\n"
            "This state is authoritative for the current bot and conversation.\n"
            f"Available on this bot: {available}.\n"
            f"Active in this conversation: {active}.\n"
        )
    for name in skill_names:
        instructions = get_skill_instructions(name)
        if not instructions:
            continue
        meta = catalog.get(name)
        display = meta.display_name if meta else name
        parts.append(f"## {display}\n\n{instructions}\n")

    if not parts:
        return ""

    return "\n".join(parts)


def build_preflight_system_prompt(role: str, skill_names: list[str]) -> str:
    """Compose a sanitized preflight prompt without raw skill instructions."""
    parts: list[str] = []

    if role:
        stripped = role.strip()
        lower = stripped.lower()
        is_sentence = any(lower.startswith(p) for p in ("you are", "you're", "act as", "as a"))
        if "\n" in stripped or is_sentence:
            parts.append(stripped + "\n")
        else:
            parts.append(f"You are a {stripped}.\n")

    catalog = load_catalog()
    labels: list[str] = []
    for name in skill_names:
        meta = catalog.get(name)
        labels.append(meta.display_name if meta else name)
    if labels:
        parts.append(f"Active runtime skills: {', '.join(labels)}.\n")

    return "\n".join(parts) if parts else ""


PROMPT_SIZE_WARNING_THRESHOLD = 8000


def _provider_semantics_note(provider_name: str) -> str:
    if provider_name != "codex":
        return ""
    return (
        "## Octopus Skill Semantics\n\n"
        "In Octopus, 'skills' means Octopus runtime skills managed through the bot catalog, "
        "default-for-new-conversations settings, and per-conversation activation. "
        "Do not answer in terms of Codex-native skills, session-local SKILL.md files, or any "
        "other non-Octopus skill system. If a user asks how skills work, describe which skills "
        "are available on this bot, which are defaults for new conversations, and which are "
        "active in this conversation. If a user asks who is answering, say the current bot in "
        "this conversation is answering; do not describe yourself as a main assistant, primary "
        "assistant, or coordinator."
    )


def _apply_provider_semantics(system_prompt: str, provider_name: str) -> str:
    note = _provider_semantics_note(provider_name)
    if not note:
        return system_prompt
    if system_prompt:
        return f"{system_prompt}\n\n{note}"
    return note


def check_prompt_size(role: str, active_skills: list[str]) -> str | None:
    """Check if composed prompt exceeds the warning threshold.

    Returns a warning message string if over threshold, None otherwise.
    """
    prompt = build_system_prompt(role, active_skills)
    if len(prompt) > PROMPT_SIZE_WARNING_THRESHOLD:
        return (
            f"Composed prompt is {len(prompt):,} chars "
            f"(threshold: {PROMPT_SIZE_WARNING_THRESHOLD:,}). "
            f"Quality may degrade. Consider removing some skills."
        )
    return None


def estimate_prompt_size(role: str, current_skills: list[str], new_skill: str) -> tuple[int, bool]:
    """Estimate prompt size if new_skill were added.

    Returns (projected_size, over_threshold).
    """
    projected = current_skills + ([new_skill] if new_skill not in current_skills else [])
    prompt = build_system_prompt(role, projected)
    return len(prompt), len(prompt) > PROMPT_SIZE_WARNING_THRESHOLD


def check_prompt_size_cross_chat(
    data_dir: Path,
    skill_name: str,
    provider_name: str,
    provider_state_factory,
    approval_mode: str,
) -> list[str]:
    """Return prompt-size warnings for chats where the named skill is active."""
    from app.storage import list_sessions, load_session

    warnings: list[str] = []
    for info in list_sessions(data_dir):
        active = filter_resolvable_skills(info.get("active_skills", []))
        if skill_name not in active:
            continue
        session_data = load_session(
            data_dir,
            info["conversation_key"],
            provider_name,
            provider_state_factory,
            approval_mode,
        )
        role = session_data.get("role", "")
        warning = check_prompt_size(role, active)
        if warning:
            warnings.append(f"  Conversation {info['conversation_key']}: {warning}")
    return warnings

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
    """Convenience builder for RunContext."""
    cred_env = CredentialEnvRecord(dict(credential_env or {}))
    provider_config = (
        ProviderConfigRecord(build_provider_config(provider_name, active_skills, cred_env.to_dict()))
        if provider_name
        else ProviderConfigRecord()
    )
    cap_summary = build_capability_summary(provider_name, active_skills) if provider_name else ""
    return RunContext(
        extra_dirs=extra_dirs,
        system_prompt=_apply_provider_semantics(build_system_prompt(role, active_skills), provider_name),
        capability_summary=cap_summary,
        provider_config=provider_config,
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
    """Convenience builder for PreflightContext."""
    cap_summary = build_capability_summary(provider_name, active_skills) if provider_name else ""
    return PreflightContext(
        extra_dirs=extra_dirs,
        system_prompt=_apply_provider_semantics(build_preflight_system_prompt(role, active_skills), provider_name),
        capability_summary=cap_summary,
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
    """Stage helper scripts codex.yaml into a conversation-scoped directory.

    Returns the scripts directory path if any scripts were staged, None otherwise.
    Syncs scripts to match active skills — removes stale, adds new.
    """
    scripts_dir = data_dir / "scripts" / filesystem_component_for_key(conversation_key)

    # Collect all scripts active skills
    all_scripts: dict[str, list[dict]] = {}  # skill_name → list of script defs
    for name in active_skills:
        raw = load_provider_yaml(name, "codex")
        if raw and "scripts" in raw and isinstance(raw["scripts"], list):
            all_scripts[name] = raw["scripts"]

    if not all_scripts:
        # No scripts needed — clean up if dir exists
        if scripts_dir.is_dir():
            shutil.rmtree(scripts_dir, ignore_errors=True)
        return None

    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale skill script dirs
    for existing in scripts_dir.iterdir():
        if existing.is_dir() and existing.name not in all_scripts:
            shutil.rmtree(existing, ignore_errors=True)

    # Stage scripts for each active skill (clean first to remove stale files)
    for skill_name, script_defs in all_scripts.items():
        skill = _skill_dir(skill_name)
        if not skill:
            continue
        skill_scripts_dir = scripts_dir / skill_name
        if skill_scripts_dir.is_dir():
            shutil.rmtree(skill_scripts_dir, ignore_errors=True)
        skill_scripts_dir.mkdir(parents=True, exist_ok=True)
        for script_def in script_defs:
            if isinstance(script_def, dict):
                source = script_def.get("source", "")
                sname = script_def.get("name", Path(source).name if source else "")
            elif isinstance(script_def, str):
                source = script_def
                sname = Path(script_def).name
            else:
                continue
            if not source or not sname:
                continue
            src_path = skill / source
            dst_path = skill_scripts_dir / sname
            if src_path.is_file():
                shutil.copy2(src_path, dst_path)

    return scripts_dir


def cleanup_codex_scripts(data_dir: Path, conversation_key: str) -> None:
    """Remove all staged scripts for a conversation (called on /new)."""
    scripts_dir = data_dir / "scripts" / filesystem_component_for_key(conversation_key)
    if scripts_dir.is_dir():
        shutil.rmtree(scripts_dir, ignore_errors=True)


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
