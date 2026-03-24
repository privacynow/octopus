"""Configuration loading, validation, and fail-fast checks."""

import ipaddress
import logging
import os
import re
import shutil
import socket
import sys
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from octopus_sdk.sessions import ProjectBinding, field
from pathlib import Path

from dotenv import dotenv_values
from octopus_sdk.config import RegistryConnectionConfig
from app.agents.state import load_registry_connection_state
from octopus_sdk.identity import parse_actor_key, telegram_numeric_id
from app.providers.codex_security import validate_codex_sandbox
from app.startup_diagnostics import sanitize_url_for_logging

log = logging.getLogger(__name__)
_WEBHOOK_LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1"}
_COMPLETION_WEBHOOK_METADATA_HOSTS = {
    "metadata",
    "metadata.aws.internal",
    "metadata.google.internal",
    "metadata.azure.internal",
}
_COMPLETION_WEBHOOK_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}


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
    slug = (instance or "default").strip() or "default"
    return Path.cwd() / ".deploy" / "bots" / slug / ".env"


def derive_agent_slug(raw: str, *, fallback: str = "agent") -> str:
    """Derive a stable, human-safe slug from a display name or instance id."""
    value = (raw or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or fallback


def parse_allowed_users(raw: str) -> tuple[set[str], set[str]]:
    """Parse BOT_ALLOWED_USERS into (actor_keys, usernames).

    Accepts comma-separated values: numeric IDs and @usernames.
    """
    actor_keys: set[str] = set()
    usernames: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        normalized = token.lstrip("@")
        if normalized.isdigit():
            actor_keys.add(parse_actor_key(normalized))
        elif ":" in normalized:
            actor_keys.add(parse_actor_key(normalized))
        else:
            usernames.add(normalized.lower())
    return actor_keys, usernames


class ProviderName(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


class BotMode(StrEnum):
    POLL = "poll"
    WEBHOOK = "webhook"


class AgentMode(StrEnum):
    REGISTRY = "registry"
    STANDALONE = "standalone"


class RuntimeMode(StrEnum):
    LOCAL = "local"
    SHARED = "shared"


class ProcessRole(StrEnum):
    ALL = "all"
    WEBHOOK = "webhook"
    WORKER = "worker"


class FilePolicy(StrEnum):
    INSPECT = "inspect"
    EDIT = "edit"


def _has_valid_http_url(raw: str) -> bool:
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_local_http_url(raw: str) -> bool:
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    return host in {"registry", "localhost", "127.0.0.1", "::1"}


def _is_local_webhook_http_url(raw: str) -> bool:
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    return host in _WEBHOOK_LOCAL_HTTP_HOSTS


def _http_url_policy_error(raw: str, *, setting_name: str) -> str | None:
    if not raw:
        return None
    if not _has_valid_http_url(raw):
        return f"{setting_name} must be a valid http:// or https:// URL when set"
    if raw.startswith("http://") and not _is_local_webhook_http_url(raw):
        return (
            f"{setting_name} uses plain HTTP over a non-local address. "
            "Use https:// for remote webhook targets."
        )
    return None


def completion_webhook_target_block_reason(raw: str) -> str | None:
    """Return a security rejection reason for a completion webhook target."""

    parsed = urlparse(raw)
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return "missing host"
    if host in _COMPLETION_WEBHOOK_METADATA_HOSTS:
        return "cloud metadata host is not allowed"

    allow_loopback = _is_local_webhook_http_url(raw)

    def _blocked_ip_reason(candidate: ipaddress._BaseAddress) -> str | None:
        if candidate in _COMPLETION_WEBHOOK_METADATA_IPS:
            return "cloud metadata address is not allowed"
        if candidate.is_loopback:
            return None if allow_loopback else "loopback addresses are not allowed"
        if candidate.is_link_local:
            return "link-local addresses are not allowed"
        if candidate.is_private:
            return "private addresses are not allowed"
        if candidate.is_multicast:
            return "multicast addresses are not allowed"
        if candidate.is_unspecified:
            return "unspecified addresses are not allowed"
        if candidate.is_reserved:
            return "reserved addresses are not allowed"
        return None

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        return _blocked_ip_reason(ip)

    try:
        resolved = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return "host resolution failed"

    seen_addresses: set[ipaddress._BaseAddress] = set()
    for family, _, _, _, sockaddr in resolved:
        del family
        address_text = sockaddr[0].split("%", 1)[0]
        try:
            candidate = ipaddress.ip_address(address_text)
        except ValueError:
            continue
        if candidate in seen_addresses:
            continue
        seen_addresses.add(candidate)
        if (reason := _blocked_ip_reason(candidate)) is not None:
            return reason
    return None


def _has_valid_postgres_url(raw: str) -> bool:
    parsed = urlparse(raw)
    return (parsed.scheme == "postgresql" or parsed.scheme.startswith("postgresql+")) and bool(parsed.netloc)


@dataclass(frozen=True)
class BotConfig:
    instance: str
    telegram_token: str
    allow_open: bool
    allowed_actor_keys: frozenset[str]
    allowed_usernames: frozenset[str]
    provider_name: str
    model: str
    working_dir: Path
    extra_dirs: tuple[Path, ...]
    data_dir: Path
    timeout_seconds: int
    approval_mode: str
    autonomous: bool
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
    admin_actor_keys: frozenset[str]
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
    telegram_api_base_url: str
    telegram_file_api_base_url: str
    completion_webhook_url: str
    credential_key: str
    # Projects — optional named working directories
    projects: tuple[ProjectBinding, ...]  # parsed from BOT_PROJECTS
    # Model profiles — stable user-facing tier names mapped to provider model IDs
    model_profiles: dict[str, str]  # e.g. {"fast": "claude-haiku-4-5-20251001", ...}
    default_model_profile: str  # "fast", "balanced", "best", or "" (use raw BOT_MODEL)
    # Public trust profile
    public_working_dir: str  # forced working dir for public users (empty = use working_dir)
    public_model_profiles: frozenset[str]  # allowed profiles for public users (empty = all)
    # Skill registry
    registry_url: str  # URL to a JSON skill registry index (empty = disabled)
    # Agent/registry runtime
    agent_mode: str  # "registry" (default via setup) | "standalone"
    agent_display_name: str
    agent_slug: str
    agent_role: str
    agent_tags: tuple[str, ...]
    agent_description: str
    agent_capabilities: tuple[str, ...]
    agent_registries: tuple[RegistryConnectionConfig, ...]
    agent_poll_interval_seconds: float
    # Runtime mode. local = inline/worker hybrid; shared = persist-first worker-owned ingress.
    runtime_mode: str  # BOT_RUNTIME_MODE: "local" (default) | "shared"
    process_role: str  # BOT_PROCESS_ROLE: "all" (default) | "webhook" | "worker"
    claim_lease_ttl_seconds: int  # BOT_CLAIM_LEASE_TTL, max age for claimed work before stale recovery
    claim_sweep_interval_seconds: float  # BOT_CLAIM_SWEEP_INTERVAL_SECONDS, periodic stale-claim sweep cadence
    delegation_timeout_seconds: int  # BOT_DELEGATION_TIMEOUT_SECONDS, max age for pending delegations before expiry
    # Postgres optional for local runtime. Empty = SQLite (default); set = Postgres as store backend.
    database_url: str  # BOT_DATABASE_URL (postgresql://...)
    db_pool_min_size: int
    db_pool_max_size: int
    db_connect_timeout_seconds: int
    # Registry publish level — controls which event kinds are published to the registry UI
    registry_publish_level: str  # BOT_REGISTRY_PUBLISH_LEVEL: "minimal" | "standard" | "full"
    # Registry agent IDs — populated from enrollment state at startup. Single writer: enrollment
    # pipeline writes connection state to disk, load_config reads it into this read model.
    # Keys are registry_id (e.g. "local"), values are the agent_id assigned by that registry.
    registry_agent_ids: dict[str, str]  # e.g. {"local": "0ace408e..."}; empty dict if no registries


    @property
    def provider(self) -> str:
        return self.provider_name

    def agent_id_for_registry(self, registry_id: str) -> str:
        """Return the agent_id assigned by a specific registry, or empty string."""
        return self.registry_agent_ids.get(registry_id, "")


PUBLISH_LEVEL_KINDS: dict[str, set[str]] = {
    "minimal": {"message.user", "message.bot", "task.status", "error"},
    "standard": {
        "message.user", "message.bot", "task.status", "error",
        "provider.request", "provider.response", "tool.execution",
        "approval.requested",
        "approval.decided",
        "delegation.proposed", "delegation.submitted", "delegation.completed",
    },
    "full": {
        "message.user", "message.bot", "task.status", "error",
        "provider.request", "provider.response", "tool.execution",
        "approval.requested",
        "approval.decided",
        "delegation.proposed", "delegation.submitted", "delegation.completed",
    },
}


def should_publish_event(config: BotConfig, kind: str) -> bool:
    """Return True if the configured publish level includes the given event kind."""
    allowed = PUBLISH_LEVEL_KINDS.get(config.registry_publish_level)
    if allowed is None:
        return False
    return kind in allowed


def _parse_model_profiles(raw: str) -> dict[str, str]:
    """Parse BOT_MODEL_PROFILES into a dict of {profile_name: model_id}.

    Format: "fast:claude-haiku-4-5-20251001,balanced:claude-sonnet-4-6,best:claude-opus-4-6"
    """
    if not raw.strip():
        return {}
    profiles: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        name, model_id = entry.split(":", 1)
        name, model_id = name.strip(), model_id.strip()
        if name and model_id:
            profiles[name] = model_id
    return profiles


def _parse_projects(raw: str) -> tuple[ProjectBinding, ...]:
    """Parse BOT_PROJECTS into a tuple of ProjectBinding.

    Format: "name:/path[|policy[|model_profile]], ..."
    Separator between root_dir and optional fields is "|" to avoid
    ambiguity with path "/" separators.

    Examples:
      "frontend:/home/app/frontend"
      "frontend:/home/app/frontend|inspect"
      "frontend:/home/app/frontend|inspect|fast"
      "frontend:/home/app/frontend||fast"   (skip policy, set profile)
    """
    if not raw.strip():
        return ()
    projects: list[ProjectBinding] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        name, rest = entry.split(":", 1)
        name = name.strip()
        rest = rest.strip()
        if not name or not rest:
            continue
        parts = rest.split("|")
        root_dir = parts[0].strip()
        file_policy = parts[1].strip() if len(parts) > 1 else ""
        model_profile = parts[2].strip() if len(parts) > 2 else ""
        if root_dir:
            projects.append(ProjectBinding(
                name=name,
                root_dir=root_dir,
                file_policy=file_policy,
                model_profile=model_profile,
            ))
    return tuple(projects)


def _parse_agent_registries(
    *,
    get,
    env_keys: set[str],
    default_scope: str,
    default_poll_interval_seconds: float,
) -> tuple[RegistryConnectionConfig, ...]:
    indexed_pattern = re.compile(r"^BOT_AGENT_REGISTRY_(\d+)_(ID|URL|ENROLL_TOKEN|SCOPE)$")
    indices = sorted(
        {
            int(match.group(1))
            for key in env_keys
            if (match := indexed_pattern.match(key))
        }
    )
    registries: list[RegistryConnectionConfig] = []
    for index in indices:
        url = get(f"BOT_AGENT_REGISTRY_{index}_URL").strip()
        enroll_token = get(f"BOT_AGENT_REGISTRY_{index}_ENROLL_TOKEN").strip()
        registry_id = get(f"BOT_AGENT_REGISTRY_{index}_ID", f"registry-{index}").strip() or f"registry-{index}"
        registry_scope = (
            get(f"BOT_AGENT_REGISTRY_{index}_SCOPE", default_scope).strip().lower() or default_scope
        )
        if not url and not enroll_token:
            continue
        registries.append(
            RegistryConnectionConfig(
                registry_id=registry_id,
                url=url,
                enroll_token=enroll_token,
                registry_scope=registry_scope,
                poll_interval_seconds=default_poll_interval_seconds,
            )
        )
    return tuple(registries)


def _validated_publish_level(raw: str) -> str:
    value = raw.strip().lower() or "standard"
    if value not in PUBLISH_LEVEL_KINDS:
        raise SystemExit(
            f"CONFIG ERROR: BOT_REGISTRY_PUBLISH_LEVEL must be one of "
            f"{', '.join(sorted(PUBLISH_LEVEL_KINDS))}, got '{value}'"
        )
    return value


def load_config(instance: str | None = None) -> BotConfig:
    """Load config from env file + environment variables.

    Instance env file: .deploy/bots/<instance>/.env
    Environment variables override the file (env file is the base,
    os.environ wins on conflicts).

    Does NOT mutate os.environ, so successive calls for different
    instances are safe.
    """
    instance = instance or os.environ.get("BOT_INSTANCE", "default")

    # Build a merged config dict: env file as base, os.environ overrides
    env_file = env_path_for_instance(instance)
    file_vars = load_dotenv_file(env_file) if env_file.exists() else {}
    env_keys = set(file_vars) | set(os.environ)

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

    def get_codex_sandbox(key: str, default: str) -> str:
        raw = get(key, default)
        try:
            return validate_codex_sandbox(raw)
        except ValueError as exc:
            raise SystemExit(f"CONFIG ERROR: {exc}") from exc

    default_data = Path.home() / ".octopus-agent" / instance

    extra_dirs_raw = get("BOT_EXTRA_DIRS")
    extra_dirs = tuple(
        Path(d.strip()) for d in extra_dirs_raw.split(",") if d.strip()
    )

    approval = get("BOT_APPROVAL_MODE", "on").lower()
    if approval not in {"on", "off"}:
        approval = "on"

    autonomous = get_bool("BOT_AUTONOMOUS")
    if autonomous and "BOT_APPROVAL_MODE" not in os.environ:
        approval = "off"

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

    agent_display_name = get("BOT_AGENT_DISPLAY_NAME", instance).strip() or instance
    agent_poll_interval_seconds = max(1.0, get_float("BOT_AGENT_POLL_INTERVAL_SECONDS", "5.0"))
    agent_registries = _parse_agent_registries(
        get=get,
        env_keys=env_keys,
        default_scope="full",
        default_poll_interval_seconds=agent_poll_interval_seconds,
    )
    raw_agent_mode = get("BOT_AGENT_MODE", "").strip().lower()
    agent_mode = raw_agent_mode or ("registry" if agent_registries else "standalone")
    agent_role = get("BOT_AGENT_ROLE").strip()
    agent_tags = tuple(
        s.strip() for s in get("BOT_AGENT_TAGS").split(",") if s.strip()
    )
    raw_agent_capabilities = (
        get("BOT_AGENT_CAPABILITIES").strip()
        or get("BOT_AGENT_SKILLS").strip()
    )
    agent_capabilities = tuple(
        s.strip() for s in raw_agent_capabilities.split(",") if s.strip()
    )
    agent_slug = derive_agent_slug(
        get("BOT_AGENT_SLUG").strip() or agent_display_name,
        fallback=derive_agent_slug(instance, fallback="agent"),
    )

    raw_users = get("BOT_ALLOWED_USERS")
    actor_keys, usernames = parse_allowed_users(raw_users)

    raw_admins = get("BOT_ADMIN_USERS")
    admin_explicit = bool(raw_admins)
    if raw_admins:
        admin_actor_keys, admin_names = parse_allowed_users(raw_admins)
    else:
        # Fallback: all allowed users are admins
        admin_actor_keys, admin_names = actor_keys, usernames

    # Read agent IDs from enrollment state files (single writer: enrollment pipeline)
    data_dir = Path(get("BOT_DATA_DIR", str(default_data)))
    registry_agent_ids: dict[str, str] = {}
    for reg in agent_registries:
        state = load_registry_connection_state(data_dir, reg.registry_id, default_scope=reg.registry_scope)
        if state.agent_id:
            registry_agent_ids[reg.registry_id] = state.agent_id

    return BotConfig(
        instance=instance,
        telegram_token=get("TELEGRAM_BOT_TOKEN"),
        allow_open=get_bool("BOT_ALLOW_OPEN"),
        allowed_actor_keys=frozenset(actor_keys),
        allowed_usernames=frozenset(usernames),
        provider_name=get("BOT_PROVIDER"),
        model=get("BOT_MODEL"),
        working_dir=Path(get("BOT_WORKING_DIR", str(Path.home()))),
        extra_dirs=extra_dirs,
        data_dir=data_dir,
        timeout_seconds=get_int("BOT_TIMEOUT_SECONDS", "300"),
        approval_mode=approval,
        autonomous=autonomous,
        role=role_str,
        role_from_file=role_from_file,
        default_skills=default_skills,
        stream_update_interval_seconds=get_float(
            "BOT_STREAM_UPDATE_INTERVAL", "1.0"
        ),
        typing_interval_seconds=get_float(
            "BOT_TYPING_INTERVAL", "4.0"
        ),
        codex_sandbox=get_codex_sandbox("CODEX_SANDBOX", "workspace-write"),
        codex_skip_git_repo_check=get_bool("CODEX_SKIP_GIT_REPO_CHECK", "1"),
        codex_full_auto=get_bool("CODEX_FULL_AUTO"),
        codex_dangerous=get_bool("CODEX_DANGEROUS"),
        codex_profile=get("CODEX_PROFILE"),
        admin_actor_keys=frozenset(admin_actor_keys),
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
        telegram_api_base_url=get("BOT_TELEGRAM_API_BASE_URL").strip(),
        telegram_file_api_base_url=get("BOT_TELEGRAM_FILE_API_BASE_URL").strip(),
        completion_webhook_url=get("BOT_COMPLETION_WEBHOOK_URL").strip(),
        credential_key=get("BOT_CREDENTIAL_KEY").strip(),
        projects=_parse_projects(get("BOT_PROJECTS")),
        model_profiles=_parse_model_profiles(get("BOT_MODEL_PROFILES")),
        default_model_profile=get("BOT_DEFAULT_PROFILE"),
        public_working_dir=get("BOT_PUBLIC_WORKING_DIR"),
        public_model_profiles=frozenset(
            s.strip() for s in get("BOT_PUBLIC_MODEL_PROFILES").split(",") if s.strip()
        ),
        registry_url=get("BOT_REGISTRY_URL"),
        agent_mode=agent_mode,
        agent_display_name=agent_display_name,
        agent_slug=agent_slug,
        agent_role=agent_role,
        agent_tags=agent_tags,
        agent_description=get("BOT_AGENT_DESCRIPTION").strip(),
        agent_capabilities=agent_capabilities,
        agent_registries=agent_registries,
        agent_poll_interval_seconds=agent_poll_interval_seconds,
        runtime_mode=get("BOT_RUNTIME_MODE", "local").strip().lower() or "local",
        process_role=get("BOT_PROCESS_ROLE", "all").strip().lower() or "all",
        claim_lease_ttl_seconds=get_int("BOT_CLAIM_LEASE_TTL", "300"),
        claim_sweep_interval_seconds=max(0.1, get_float("BOT_CLAIM_SWEEP_INTERVAL_SECONDS", "60.0")),
        delegation_timeout_seconds=get_int("BOT_DELEGATION_TIMEOUT_SECONDS", "3600"),
        database_url=get("BOT_DATABASE_URL", "").strip(),
        db_pool_min_size=max(0, get_int("BOT_DB_POOL_MIN_SIZE", "1")),
        db_pool_max_size=max(1, get_int("BOT_DB_POOL_MAX_SIZE", "10")),
        db_connect_timeout_seconds=max(1, get_int("BOT_DB_CONNECT_TIMEOUT", "10")),
        registry_publish_level=_validated_publish_level(get("BOT_REGISTRY_PUBLISH_LEVEL", "standard")),
        registry_agent_ids=registry_agent_ids,
    )


def load_config_provider_health() -> BotConfig:
    """Load minimal config from environment for provider-only health checks.

    Used by --provider-health. Does not require BOT_DATABASE_URL or Telegram
    config. Reads BOT_PROVIDER, BOT_MODEL, BOT_DATA_DIR, BOT_WORKING_DIR, and
    provider-specific vars so provider auth and runtime probes work correctly.
    """
    def get(key: str, default: str = "") -> str:
        return os.environ.get(key, default)

    def get_bool(key: str, default: str = "0") -> bool:
        return get(key, default).lower() in {"1", "true", "yes", "on"}

    def get_int(key: str, default: str) -> int:
        raw = get(key, default)
        try:
            return int(raw)
        except ValueError:
            return int(default)

    def get_float(key: str, default: str) -> float:
        raw = get(key, default)
        try:
            return float(raw)
        except ValueError:
            return float(default)

    def get_codex_sandbox(key: str, default: str) -> str:
        raw = get(key, default)
        try:
            return validate_codex_sandbox(raw)
        except ValueError as exc:
            raise SystemExit(f"CONFIG ERROR: {exc}") from exc

    instance = get("BOT_INSTANCE", "default")
    default_data = Path.home() / ".octopus-agent" / instance
    extra_dirs_raw = get("BOT_EXTRA_DIRS")
    extra_dirs = tuple(
        Path(d.strip()) for d in extra_dirs_raw.split(",") if d.strip()
    )
    return BotConfig(
        instance=instance,
        telegram_token=get("TELEGRAM_BOT_TOKEN").strip(),
        allow_open=False,
        allowed_actor_keys=frozenset(),
        allowed_usernames=frozenset(),
        provider_name=get("BOT_PROVIDER", "claude").strip() or "claude",
        model=get("BOT_MODEL"),
        working_dir=Path(get("BOT_WORKING_DIR", str(Path.home()))),
        extra_dirs=extra_dirs,
        data_dir=Path(get("BOT_DATA_DIR", str(default_data))),
        timeout_seconds=get_int("BOT_TIMEOUT_SECONDS", "300"),
        approval_mode="on",
        autonomous=False,
        role="",
        role_from_file=False,
        default_skills=(),
        stream_update_interval_seconds=get_float("BOT_STREAM_UPDATE_INTERVAL", "1.0"),
        typing_interval_seconds=get_float("BOT_TYPING_INTERVAL", "4.0"),
        codex_sandbox=get_codex_sandbox("CODEX_SANDBOX", "workspace-write"),
        codex_skip_git_repo_check=get_bool("CODEX_SKIP_GIT_REPO_CHECK", "1"),
        codex_full_auto=get_bool("CODEX_FULL_AUTO"),
        codex_dangerous=get_bool("CODEX_DANGEROUS"),
        codex_profile=get("CODEX_PROFILE"),
        admin_actor_keys=frozenset(),
        admin_usernames=frozenset(),
        admin_users_explicit=False,
        compact_mode=True,
        summary_model=get("BOT_SUMMARY_MODEL", "claude-haiku-4-5-20251001"),
        rate_limit_per_minute=0,
        rate_limit_per_hour=0,
        bot_mode="poll",
        webhook_url="",
        webhook_listen="127.0.0.1",
        webhook_port=8443,
        webhook_secret="",
        telegram_api_base_url="",
        telegram_file_api_base_url="",
        completion_webhook_url="",
        credential_key=get("BOT_CREDENTIAL_KEY").strip(),
        projects=(),
        model_profiles={},
        default_model_profile="",
        public_working_dir="",
        public_model_profiles=frozenset(),
        registry_url="",
        agent_mode="standalone",
        agent_display_name=instance,
        agent_slug=derive_agent_slug(instance, fallback="agent"),
        agent_role="",
        agent_tags=(),
        agent_description="",
        agent_capabilities=(),
        agent_registries=(),
        agent_poll_interval_seconds=5.0,
        runtime_mode="local",
        process_role="all",
        claim_lease_ttl_seconds=300,
        claim_sweep_interval_seconds=60.0,
        delegation_timeout_seconds=3600,
        database_url="",
        db_pool_min_size=1,
        db_pool_max_size=10,
        db_connect_timeout_seconds=10,
        registry_publish_level="standard",
        registry_agent_ids={},
    )


def validate_config(config: BotConfig) -> list[str]:
    """Return list of errors. Empty means healthy."""
    errors: list[str] = []

    has_registry_ingress_channel = (
        config.agent_mode == AgentMode.REGISTRY.value
        and any(registry.registry_scope in {"channel", "full"} for registry in config.agent_registries)
    )
    if not config.telegram_token and not has_registry_ingress_channel:
        errors.append(
            "At least one ingress-capable channel is required. Set TELEGRAM_BOT_TOKEN in your bot env file, "
            "or configure a registry connection with BOT_AGENT_REGISTRY_SCOPE=channel/full "
            "(or BOT_AGENT_REGISTRY_<n>_SCOPE=channel/full), or run ./octopus."
        )

    if config.provider_name not in ProviderName._value2member_map_:
        errors.append(
            f"BOT_PROVIDER must be 'claude' or 'codex', got '{config.provider_name}'. "
            "Set BOT_PROVIDER=claude or BOT_PROVIDER=codex in the bot env file."
        )

    if not config.allowed_actor_keys and not config.allowed_usernames and not config.allow_open:
        errors.append(
            "Access not configured: BOT_ALLOWED_USERS is empty and BOT_ALLOW_OPEN is not set. "
            "Set BOT_ALLOWED_USERS=<your-telegram-user-id> or BOT_ALLOW_OPEN=1 in the bot env file."
        )

    if not config.working_dir.is_dir():
        errors.append(f"BOT_WORKING_DIR does not exist: {config.working_dir}")

    binary = "claude" if config.provider_name == "claude" else "codex"
    if config.provider_name in {"claude", "codex"} and not shutil.which(binary):
        errors.append(
            f"Provider binary '{binary}' not found in PATH. "
            f"Install the {binary} CLI, or rebuild the managed bot image with ./octopus redeploy bots."
        )

    for d in config.extra_dirs:
        if not d.is_dir():
            errors.append(f"BOT_EXTRA_DIRS path does not exist or is not a directory: {d}")

    if not config.role_from_file and ('"' in config.role or '\\' in config.role):
        errors.append(
            'BOT_ROLE contains " or \\. Use <instance>.role.md for complex roles.'
        )

    if config.autonomous:
        if config.allow_open:
            errors.append(
                "BOT_AUTONOMOUS=1 and BOT_ALLOW_OPEN=1 cannot both be set. "
                "Autonomous mode requires a private bot with explicit BOT_ALLOWED_USERS."
            )
        if not config.allowed_actor_keys and not config.allowed_usernames:
            errors.append(
                "BOT_AUTONOMOUS=1 requires BOT_ALLOWED_USERS to be set. "
                "Autonomous mode must have at least one authorized user."
            )

    if config.codex_full_auto and config.codex_dangerous:
        errors.append("CODEX_FULL_AUTO and CODEX_DANGEROUS cannot both be set")
    try:
        validate_codex_sandbox(config.codex_sandbox)
    except ValueError as exc:
        errors.append(str(exc))

    if config.bot_mode not in BotMode._value2member_map_:
        errors.append(
            f"BOT_MODE must be 'poll' or 'webhook', got '{config.bot_mode}'"
        )

    if config.agent_mode not in AgentMode._value2member_map_:
        errors.append(
            f"BOT_AGENT_MODE must be 'registry' or 'standalone', got '{config.agent_mode}'"
        )

    seen_registry_ids: set[str] = set()
    for registry in config.agent_registries:
        if not registry.registry_id:
            errors.append("Each registry connection must have a non-empty BOT_AGENT_REGISTRY_<n>_ID")
        elif registry.registry_id in seen_registry_ids:
            errors.append(f"Duplicate registry connection id: '{registry.registry_id}'")
        seen_registry_ids.add(registry.registry_id)
        if not _has_valid_http_url(registry.url):
            errors.append(
                f"BOT_AGENT_REGISTRY_<n>_URL must be a valid http:// or https:// URL when set "
                f"(connection '{registry.registry_id}')"
            )
        elif registry.url.startswith("http://") and not _is_local_http_url(registry.url):
            errors.append(
                f"Registry connection '{registry.registry_id}' uses plain HTTP over a non-local address. "
                "Use https:// for remote registries."
            )
        if registry.registry_scope not in {"channel", "coordination", "full"}:
            errors.append(
                f"Registry connection '{registry.registry_id}' has invalid scope '{registry.registry_scope}'. "
                "Use channel, coordination, or full."
            )

    if config.agent_poll_interval_seconds <= 0:
        errors.append("BOT_AGENT_POLL_INTERVAL_SECONDS must be greater than 0")

    if config.claim_lease_ttl_seconds <= 0:
        errors.append("BOT_CLAIM_LEASE_TTL must be greater than 0")

    if config.claim_sweep_interval_seconds <= 0:
        errors.append("BOT_CLAIM_SWEEP_INTERVAL_SECONDS must be greater than 0")

    if config.delegation_timeout_seconds <= 0:
        errors.append("BOT_DELEGATION_TIMEOUT_SECONDS must be greater than 0")

    if config.runtime_mode == RuntimeMode.SHARED.value:
        if config.bot_mode != BotMode.WEBHOOK.value:
            errors.append(
                "BOT_RUNTIME_MODE=shared requires BOT_MODE=webhook. "
                "Shared Runtime uses persist-first webhook ingress; "
                "polling mode is Local Runtime only."
            )
    elif config.runtime_mode != RuntimeMode.LOCAL.value:
        errors.append(
            f"BOT_RUNTIME_MODE must be 'local' or 'shared', got '{config.runtime_mode}'."
        )

    if config.process_role not in ProcessRole._value2member_map_:
        errors.append(
            f"BOT_PROCESS_ROLE must be 'all', 'webhook', or 'worker', got '{config.process_role}'."
        )
    elif config.process_role != ProcessRole.ALL.value:
        if config.runtime_mode != RuntimeMode.SHARED.value:
            errors.append(
                f"BOT_PROCESS_ROLE={config.process_role} requires BOT_RUNTIME_MODE=shared."
            )
        if config.process_role == ProcessRole.WEBHOOK.value and config.bot_mode != BotMode.WEBHOOK.value:
            errors.append(
                "BOT_PROCESS_ROLE=webhook requires BOT_MODE=webhook."
            )

    if config.bot_mode == BotMode.WEBHOOK.value:
        if not config.webhook_url:
            errors.append("BOT_WEBHOOK_URL is required when BOT_MODE=webhook")
    if config.webhook_url:
        if error := _http_url_policy_error(config.webhook_url, setting_name="BOT_WEBHOOK_URL"):
            errors.append(error)

    if config.telegram_api_base_url and not _has_valid_http_url(config.telegram_api_base_url):
        errors.append(
            "BOT_TELEGRAM_API_BASE_URL must be a valid http:// or https:// URL when set"
        )

    if config.telegram_file_api_base_url and not _has_valid_http_url(config.telegram_file_api_base_url):
        errors.append(
            "BOT_TELEGRAM_FILE_API_BASE_URL must be a valid http:// or https:// URL when set"
        )

    if config.completion_webhook_url:
        if error := _http_url_policy_error(
            config.completion_webhook_url,
            setting_name="BOT_COMPLETION_WEBHOOK_URL",
        ):
            errors.append(error)
        elif reason := completion_webhook_target_block_reason(config.completion_webhook_url):
            errors.append(
                f"BOT_COMPLETION_WEBHOOK_URL target is not allowed: {reason}"
            )

    if config.database_url and not _has_valid_postgres_url(config.database_url):
        errors.append(
            "BOT_DATABASE_URL must be a valid postgresql:// connection string when set"
        )

    seen_project_names: set[str] = set()
    for proj in config.projects:
        if proj.name in seen_project_names:
            errors.append(f"Duplicate project name: '{proj.name}'")
        seen_project_names.add(proj.name)
        if not Path(proj.root_dir).is_dir():
            errors.append(f"Project '{proj.name}' root dir does not exist: {proj.root_dir}")
        if proj.file_policy and proj.file_policy not in FilePolicy._value2member_map_:
            errors.append(f"Project '{proj.name}' has invalid file_policy: '{proj.file_policy}'")
        if proj.model_profile:
            if not config.model_profiles:
                errors.append(
                    f"Project '{proj.name}' sets model_profile='{proj.model_profile}' "
                    "but no BOT_MODEL_PROFILES are configured"
                )
            elif proj.model_profile not in config.model_profiles:
                errors.append(f"Project '{proj.name}' has unknown model_profile: '{proj.model_profile}'")

    # Validate default_skills against catalog
    if config.default_skills:
        try:
            from app.content_seed import builtin_skill_tracks

            known = {record.slug for record in builtin_skill_tracks()}
            for skill_name in config.default_skills:
                if skill_name not in known:
                    errors.append(f"BOT_SKILLS references unknown built-in skill: '{skill_name}'")
        except Exception as exc:
            log.warning(
                "Built-in skill catalog unavailable during config validation: %s",
                exc.__class__.__name__,
            )
            errors.append(
                "BOT_SKILLS could not be validated because the built-in skill catalog could not be loaded"
            )

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
