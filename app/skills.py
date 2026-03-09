"""Skill catalog: discovery, loading, and context building."""

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import frontmatter
import yaml
from cryptography.fernet import Fernet, InvalidToken

from app.providers.base import PreflightContext, RunContext


CATALOG_DIR = Path(__file__).resolve().parent.parent / "skills" / "catalog"
CUSTOM_DIR = Path.home() / ".config" / "telegram-agent-bot" / "skills"


@dataclass(frozen=True)
class SkillMeta:
    name: str
    display_name: str
    description: str
    is_custom: bool = False


@dataclass(frozen=True)
class SkillRequirement:
    key: str
    prompt: str
    help_url: str | None = None
    validate: dict | None = None


# ---------------------------------------------------------------------------
# Skill directory resolution: custom > built-in
# ---------------------------------------------------------------------------

def _skill_dir(name: str) -> Path | None:
    """Resolve skill directory: custom > built-in. Returns None if not found.

    Also returns None if skill.md exists but is malformed, so that
    broken skills are excluded from credential checks, provider config,
    and execution — not just from the catalog UI.
    """
    for base in (CUSTOM_DIR, CATALOG_DIR):
        candidate = base / name
        skill_file = candidate / "skill.md"
        if candidate.is_dir() and skill_file.is_file():
            try:
                _load_skill_md(skill_file)
            except ValueError:
                continue
            return candidate
    return None


# ---------------------------------------------------------------------------
# Frontmatter parsing (using python-frontmatter)
# ---------------------------------------------------------------------------

def _load_skill_md(path: Path) -> tuple[dict, str]:
    """Parse a skill.md file. Returns (metadata_dict, body).

    Raises ValueError on malformed content so callers can skip gracefully.
    """
    try:
        post = frontmatter.load(str(path))
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}") from e
    return dict(post.metadata), post.content.strip()


# ---------------------------------------------------------------------------
# requires.yaml parsing (using PyYAML)
# ---------------------------------------------------------------------------

def _parse_requires_yaml(text: str) -> list[SkillRequirement]:
    """Parse a requires.yaml file and return SkillRequirements.

    Returns empty list on malformed YAML instead of crashing.
    """
    if not text.strip():
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
        if not isinstance(item, dict):
            continue
        key = item.get("key", "")
        if not key:
            continue
        validate = item.get("validate")
        if isinstance(validate, dict):
            # Normalize all values to strings for consistency
            validate = {k: str(v) for k, v in validate.items()}
        else:
            validate = None
        requirements.append(SkillRequirement(
            key=str(key),
            prompt=str(item.get("prompt", "")),
            help_url=item.get("help_url") or None,
            validate=validate,
        ))
    return requirements


def get_skill_requirements(name: str) -> list[SkillRequirement]:
    """Load requirements from the skill's requires.yaml."""
    skill = _skill_dir(name)
    if not skill:
        return []
    requires_file = skill / "requires.yaml"
    if not requires_file.is_file():
        return []
    text = requires_file.read_text(encoding="utf-8")
    return _parse_requires_yaml(text)


def check_credentials(name: str, user_credentials: dict[str, dict[str, str]]) -> list[SkillRequirement]:
    """Return unsatisfied credential requirements for *name* given stored credentials."""
    requirements = get_skill_requirements(name)
    skill_creds = user_credentials.get(name, {})
    return [r for r in requirements if r.key not in skill_creds]


# ---------------------------------------------------------------------------
# Per-user credential storage (using cryptography.fernet)
# ---------------------------------------------------------------------------

def derive_fernet_key(telegram_token: str) -> bytes:
    """Derive a Fernet-compatible key from the bot token.

    Fernet requires a 32-byte URL-safe base64-encoded key.
    We derive it deterministically from the bot token via SHA-256.
    """
    import base64
    raw = hashlib.sha256(telegram_token.encode()).digest()
    return base64.urlsafe_b64encode(raw)


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


def _credential_file(data_dir: Path, user_id: int) -> Path:
    return data_dir / "credentials" / f"{user_id}.json"


def load_user_credentials(data_dir: Path, user_id: int, key: bytes) -> dict[str, dict[str, str]]:
    """Load and decrypt per-user credentials.

    Returns ``{skill_name: {cred_key: value, ...}, ...}``.
    """
    path = _credential_file(data_dir, user_id)
    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    result: dict[str, dict[str, str]] = {}
    for skill_name, creds in stored.items():
        if not isinstance(creds, dict):
            continue
        decrypted: dict[str, str] = {}
        for cred_key, enc_value in creds.items():
            try:
                decrypted[cred_key] = _decrypt(str(enc_value), key)
            except (InvalidToken, Exception):
                continue  # skip corrupted or tampered entries
        if decrypted:
            result[skill_name] = decrypted
    return result


def save_user_credential(
    data_dir: Path,
    user_id: int,
    skill_name: str,
    cred_key: str,
    value: str,
    key: bytes,
) -> None:
    """Encrypt and save a single credential for a user."""
    path = _credential_file(data_dir, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    stored: dict[str, dict[str, str]] = {}
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}

    skill_creds = stored.setdefault(skill_name, {})
    skill_creds[cred_key] = _encrypt(value, key)

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(stored, indent=2, sort_keys=True), encoding="utf-8")
    tmp.rename(path)


def build_credential_env(
    active_skills: list[str],
    user_credentials: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Flatten per-skill credentials into a single env-var dict for active skills."""
    env: dict[str, str] = {}
    for skill in active_skills:
        creds = user_credentials.get(skill, {})
        env.update(creds)
    return env


# ---------------------------------------------------------------------------
# Credential validation (HTTP check from requires.yaml)
# ---------------------------------------------------------------------------

async def validate_credential(req: SkillRequirement, value: str) -> tuple[bool, str]:
    """Run HTTP validation if defined. Returns (ok, message).

    If no validate spec, returns (True, "").
    """
    if not req.validate:
        return True, ""

    spec = req.validate
    url = spec.get("url", "")
    if not url:
        return True, ""

    method = spec.get("method", "GET").upper()
    header_template = spec.get("header", "")
    try:
        expect_status = int(spec.get("expect_status", "200"))
    except (ValueError, TypeError):
        return False, f"Invalid expect_status in validate spec: {spec.get('expect_status')!r}"

    # Resolve ${KEY} in header with the credential value
    header_value = re.sub(
        r'\$\{' + re.escape(req.key) + r'\}',
        value,
        header_template,
    )

    headers = {}
    if header_value and ":" in header_value:
        hname, _, hval = header_value.partition(":")
        headers[hname.strip()] = hval.strip()
    elif header_value:
        # Assume Authorization header if no colon
        headers["Authorization"] = header_value

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers)
            if resp.status_code == expect_status:
                return True, ""
            return False, f"Expected status {expect_status}, got {resp.status_code}"
    except Exception as e:
        return False, f"Validation request failed: {e}"


# ---------------------------------------------------------------------------
# Catalog discovery
# ---------------------------------------------------------------------------

def load_catalog() -> dict[str, SkillMeta]:
    """Discover skills from built-in catalog and custom skills dir.

    Custom skills override built-in skills with the same name.
    """
    catalog: dict[str, SkillMeta] = {}

    import logging
    _log = logging.getLogger(__name__)

    # Built-in skills first.
    # The canonical key is the directory name — _skill_dir() resolves by directory
    # name, so catalog must use the same key. Frontmatter "name" is display metadata.
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

    # Custom skills override built-in
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
    """Read the markdown body (minus YAML frontmatter) from a skill's skill.md."""
    skill = _skill_dir(name)
    if not skill:
        return ""
    try:
        _, body = _load_skill_md(skill / "skill.md")
    except ValueError:
        return ""
    return body


def get_provider_config_digest(skill_names: list[str], provider_name: str = "") -> str:
    """Return a SHA-256 digest of provider YAML content for the given skills.

    If provider_name is given, only hash that provider's YAML files.
    This avoids cross-provider invalidation (editing claude.yaml won't
    invalidate Codex threads, and vice versa).
    """
    providers = (provider_name,) if provider_name else ("claude", "codex")
    parts: list[str] = []
    for name in sorted(skill_names):
        skill = _skill_dir(name)
        if not skill:
            continue
        for provider in providers:
            yaml_file = skill / f"{provider}.yaml"
            if yaml_file.is_file():
                parts.append(f"{name}/{provider}:" + yaml_file.read_text(encoding="utf-8"))
    if not parts:
        return ""
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def get_skill_digests(skill_names: list[str]) -> dict[str, str]:
    """Return {name: sha256_hex_of_skill.md_content} for each named skill."""
    digests: dict[str, str] = {}
    for name in skill_names:
        skill = _skill_dir(name)
        if not skill:
            continue
        content = (skill / "skill.md").read_bytes()
        digests[name] = hashlib.sha256(content).hexdigest()
    return digests


# ---------------------------------------------------------------------------
# Provider YAML parsing (using PyYAML)
# ---------------------------------------------------------------------------

def _resolve_placeholders(obj, env: dict[str, str]):
    """Recursively replace ${VAR} placeholders in strings with values from env."""
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
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


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
                        lines.append(f"MCP server: {sname} (from {name})")
            if "allowed_tools" in raw:
                for t in raw["allowed_tools"]:
                    lines.append(f"Allowed tool: {t}")
        elif provider == "codex":
            if "scripts" in raw:
                for s in raw["scripts"]:
                    sname = s if isinstance(s, str) else s.get("name", "?")
                    lines.append(f"Script: {sname} (from {name})")
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


PROMPT_SIZE_WARNING_THRESHOLD = 8000


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

# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def build_run_context(
    role: str,
    active_skills: list[str],
    extra_dirs: list[str],
    provider_name: str = "",
    credential_env: dict[str, str] | None = None,
) -> RunContext:
    """Convenience builder for RunContext."""
    cred_env = credential_env or {}
    provider_config = build_provider_config(provider_name, active_skills, cred_env) if provider_name else {}
    cap_summary = build_capability_summary(provider_name, active_skills) if provider_name else ""
    return RunContext(
        extra_dirs=extra_dirs,
        system_prompt=build_system_prompt(role, active_skills),
        capability_summary=cap_summary,
        provider_config=provider_config,
        credential_env=cred_env,
    )


def build_preflight_context(
    role: str,
    active_skills: list[str],
    extra_dirs: list[str],
    provider_name: str = "",
) -> PreflightContext:
    """Convenience builder for PreflightContext."""
    cap_summary = build_capability_summary(provider_name, active_skills) if provider_name else ""
    return PreflightContext(
        extra_dirs=extra_dirs,
        system_prompt=build_system_prompt(role, active_skills),
        capability_summary=cap_summary,
    )


# ---------------------------------------------------------------------------
# Codex script staging
# ---------------------------------------------------------------------------

def stage_codex_scripts(
    data_dir: Path,
    chat_id: int,
    active_skills: list[str],
) -> Path | None:
    """Stage helper scripts from codex.yaml into a chat-scoped directory.

    Returns the scripts directory path if any scripts were staged, None otherwise.
    Syncs scripts to match active skills — removes stale, adds new.
    """
    scripts_dir = data_dir / "scripts" / str(chat_id)

    # Collect all scripts from active skills
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


def cleanup_codex_scripts(data_dir: Path, chat_id: int) -> None:
    """Remove all staged scripts for a chat (called on /new)."""
    scripts_dir = data_dir / "scripts" / str(chat_id)
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


def validate_active_skills(
    skill_names: list[str],
    user_id: int = 0,
    data_dir: Path | None = None,
    encryption_key: bytes | None = None,
) -> list[str]:
    """Validate active skills: catalog presence + credential satisfaction.

    Returns list of error strings.
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
