"""Configuration loading, validation, and fail-fast checks."""

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Parse a .env file. Returns the key-value pairs found.

    Uses python-dotenv for robust handling of quoting, escapes,
    multiline values, and inline comments.
    """
    if not path.exists():
        return {}
    raw = dotenv_values(path)
    return {k: v for k, v in raw.items() if v is not None}


def env_path_for_instance(instance: str) -> Path:
    return Path.home() / ".config" / "telegram-agent-bot" / f"{instance}.env"


def parse_allowed_users(raw: str) -> tuple[set[int], set[str]]:
    """Parse BOT_ALLOWED_USERS into (user_ids, usernames).

    Accepts comma-separated values: numeric IDs and @usernames.
    """
    ids: set[int] = set()
    usernames: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        normalized = token.lstrip("@")
        if normalized.isdigit():
            ids.add(int(normalized))
        else:
            usernames.add(normalized.lower())
    return ids, usernames


@dataclass(frozen=True)
class BotConfig:
    instance: str
    telegram_token: str
    allow_open: bool
    allowed_user_ids: frozenset[int]
    allowed_usernames: frozenset[str]
    provider_name: str
    model: str
    working_dir: Path
    extra_dirs: tuple[Path, ...]
    data_dir: Path
    timeout_seconds: int
    approval_mode: str
    role: str
    role_from_file: bool  # True if role came from <instance>.role.md
    default_skills: tuple[str, ...]
    stream_update_interval_seconds: float
    typing_interval_seconds: float
    # Codex-specific
    codex_sandbox: str
    codex_skip_git_repo_check: bool
    codex_full_auto: bool
    codex_dangerous: bool
    codex_profile: str
    # Admin users — gates store install/uninstall/update
    admin_user_ids: frozenset[int]
    admin_usernames: frozenset[str]
    admin_users_explicit: bool  # True if BOT_ADMIN_USERS was set
    # Compact mode — mobile-friendly response summarization
    compact_mode: bool
    summary_model: str
    # Rate limiting (0 = disabled)
    rate_limit_per_minute: int
    rate_limit_per_hour: int
    # Transport mode
    bot_mode: str  # "poll" or "webhook"
    webhook_url: str
    webhook_listen: str
    webhook_port: int
    webhook_secret: str
    # Projects — optional named working directories
    projects: tuple[tuple[str, str, tuple[str, ...]], ...]  # ((name, root_dir, extra_dirs), ...)
    # Skill registry
    registry_url: str  # URL to a JSON skill registry index (empty = disabled)


def _parse_projects(raw: str) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Parse BOT_PROJECTS into a tuple of (name, root_dir, extra_dirs).

    Format: "name1:/path/to/dir1,name2:/path/to/dir2"
    Each entry is "name:path" where path is the project root directory.
    """
    if not raw.strip():
        return ()
    projects: list[tuple[str, str, tuple[str, ...]]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        name, path = entry.split(":", 1)
        name, path = name.strip(), path.strip()
        if name and path:
            projects.append((name, path, ()))
    return tuple(projects)


def load_config(instance: str | None = None) -> BotConfig:
    """Load config from env file + environment variables.

    Instance env file: ~/.config/telegram-agent-bot/<instance>.env
    Environment variables override the file (env file is the base,
    os.environ wins on conflicts).

    Does NOT mutate os.environ, so successive calls for different
    instances are safe.
    """
    instance = instance or os.environ.get("BOT_INSTANCE", "default")

    # Build a merged config dict: env file as base, os.environ overrides
    env_file = env_path_for_instance(instance)
    file_vars = load_dotenv_file(env_file) if env_file.exists() else {}

    def get(key: str, default: str = "") -> str:
        """Env var wins over file, file wins over default."""
        return os.environ.get(key, file_vars.get(key, default))

    def get_bool(key: str, default: str = "0") -> bool:
        return get(key, default).lower() in {"1", "true", "yes", "on"}

    def get_int(key: str, default: str) -> int:
        raw = get(key, default)
        try:
            return int(raw)
        except ValueError:
            raise SystemExit(f"CONFIG ERROR: {key} must be an integer, got '{raw}'")

    def get_float(key: str, default: str) -> float:
        raw = get(key, default)
        try:
            return float(raw)
        except ValueError:
            raise SystemExit(f"CONFIG ERROR: {key} must be a number, got '{raw}'")

    default_data = Path.home() / ".telegram-agent-bot" / instance

    extra_dirs_raw = get("BOT_EXTRA_DIRS")
    extra_dirs = tuple(
        Path(d.strip()) for d in extra_dirs_raw.split(",") if d.strip()
    )

    approval = get("BOT_APPROVAL_MODE", "on").lower()
    if approval not in {"on", "off"}:
        approval = "on"

    role_str = get("BOT_ROLE")
    role_from_file = False
    # Check for role.md override
    role_md = env_file.with_suffix(".role.md")
    if role_md.exists():
        role_str = role_md.read_text().strip()
        role_from_file = True

    default_skills_raw = get("BOT_SKILLS")
    default_skills = tuple(
        s.strip() for s in default_skills_raw.split(",") if s.strip()
    )

    raw_users = get("BOT_ALLOWED_USERS")
    user_ids, usernames = parse_allowed_users(raw_users)

    raw_admins = get("BOT_ADMIN_USERS")
    admin_explicit = bool(raw_admins)
    if raw_admins:
        admin_ids, admin_names = parse_allowed_users(raw_admins)
    else:
        # Fallback: all allowed users are admins
        admin_ids, admin_names = user_ids, usernames

    return BotConfig(
        instance=instance,
        telegram_token=get("TELEGRAM_BOT_TOKEN"),
        allow_open=get_bool("BOT_ALLOW_OPEN"),
        allowed_user_ids=frozenset(user_ids),
        allowed_usernames=frozenset(usernames),
        provider_name=get("BOT_PROVIDER"),
        model=get("BOT_MODEL"),
        working_dir=Path(get("BOT_WORKING_DIR", str(Path.home()))),
        extra_dirs=extra_dirs,
        data_dir=Path(get("BOT_DATA_DIR", str(default_data))),
        timeout_seconds=get_int("BOT_TIMEOUT_SECONDS", "300"),
        approval_mode=approval,
        role=role_str,
        role_from_file=role_from_file,
        default_skills=default_skills,
        stream_update_interval_seconds=get_float(
            "BOT_STREAM_UPDATE_INTERVAL", "1.0"
        ),
        typing_interval_seconds=get_float(
            "BOT_TYPING_INTERVAL", "4.0"
        ),
        codex_sandbox=get("CODEX_SANDBOX", "workspace-write"),
        codex_skip_git_repo_check=get_bool("CODEX_SKIP_GIT_REPO_CHECK", "1"),
        codex_full_auto=get_bool("CODEX_FULL_AUTO"),
        codex_dangerous=get_bool("CODEX_DANGEROUS"),
        codex_profile=get("CODEX_PROFILE"),
        admin_user_ids=frozenset(admin_ids),
        admin_usernames=frozenset(admin_names),
        admin_users_explicit=admin_explicit,
        compact_mode=get_bool("BOT_COMPACT_MODE"),
        summary_model=get("BOT_SUMMARY_MODEL", "claude-haiku-4-5-20251001"),
        rate_limit_per_minute=get_int("BOT_RATE_LIMIT_PER_MINUTE", "0"),
        rate_limit_per_hour=get_int("BOT_RATE_LIMIT_PER_HOUR", "0"),
        bot_mode=get("BOT_MODE", "poll").lower(),
        webhook_url=get("BOT_WEBHOOK_URL"),
        webhook_listen=get("BOT_WEBHOOK_LISTEN", "127.0.0.1"),
        webhook_port=get_int("BOT_WEBHOOK_PORT", "8443"),
        webhook_secret=get("BOT_WEBHOOK_SECRET"),
        projects=_parse_projects(get("BOT_PROJECTS")),
        registry_url=get("BOT_REGISTRY_URL"),
    )


def validate_config(config: BotConfig) -> list[str]:
    """Return list of errors. Empty means healthy."""
    errors: list[str] = []

    if not config.telegram_token:
        errors.append("TELEGRAM_BOT_TOKEN is not set")

    if config.provider_name not in {"claude", "codex"}:
        errors.append(
            f"BOT_PROVIDER must be 'claude' or 'codex', got '{config.provider_name}'"
        )

    if not config.allowed_user_ids and not config.allowed_usernames and not config.allow_open:
        errors.append(
            "BOT_ALLOWED_USERS is empty and BOT_ALLOW_OPEN is not set. "
            "Set BOT_ALLOW_OPEN=1 to explicitly allow open access."
        )

    if not config.working_dir.is_dir():
        errors.append(f"BOT_WORKING_DIR does not exist: {config.working_dir}")

    binary = "claude" if config.provider_name == "claude" else "codex"
    if config.provider_name in {"claude", "codex"} and not shutil.which(binary):
        errors.append(f"Provider binary '{binary}' not found in PATH")

    for d in config.extra_dirs:
        if not d.is_dir():
            errors.append(f"BOT_EXTRA_DIRS path does not exist or is not a directory: {d}")

    if not config.role_from_file and ('"' in config.role or '\\' in config.role):
        errors.append(
            'BOT_ROLE contains " or \\. Use <instance>.role.md for complex roles.'
        )

    if config.codex_full_auto and config.codex_dangerous:
        errors.append("CODEX_FULL_AUTO and CODEX_DANGEROUS cannot both be set")

    if config.bot_mode not in {"poll", "webhook"}:
        errors.append(
            f"BOT_MODE must be 'poll' or 'webhook', got '{config.bot_mode}'"
        )

    if config.bot_mode == "webhook":
        if not config.webhook_url:
            errors.append("BOT_WEBHOOK_URL is required when BOT_MODE=webhook")

    seen_project_names: set[str] = set()
    for name, root_dir, _ in config.projects:
        if name in seen_project_names:
            errors.append(f"Duplicate project name: '{name}'")
        seen_project_names.add(name)
        if not Path(root_dir).is_dir():
            errors.append(f"Project '{name}' root dir does not exist: {root_dir}")

    # Validate default_skills against catalog
    if config.default_skills:
        from app.skills import load_catalog
        try:
            catalog = load_catalog()
            for skill_name in config.default_skills:
                if skill_name not in catalog:
                    errors.append(f"BOT_SKILLS references unknown skill: '{skill_name}'")
        except Exception:
            pass  # Don't block startup if catalog can't load

    # Validate data dir writability
    data_dir = config.data_dir
    try:
        if data_dir.exists():
            if not data_dir.is_dir():
                errors.append(f"BOT_DATA_DIR exists but is not a directory: {data_dir}")
            elif not os.access(data_dir, os.W_OK):
                errors.append(f"BOT_DATA_DIR is not writable: {data_dir}")
        else:
            # Check if parent is writable (we'd need to create it)
            parent = data_dir
            while not parent.exists():
                parent = parent.parent
            if not os.access(parent, os.W_OK):
                errors.append(f"BOT_DATA_DIR cannot be created (parent not writable): {data_dir}")
    except PermissionError:
        errors.append(f"BOT_DATA_DIR is not accessible: {data_dir}")

    return errors


def fail_fast(config: BotConfig) -> None:
    """Print errors and exit if config is invalid."""
    errors = validate_config(config)
    if errors:
        for e in errors:
            print(f"CONFIG ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
