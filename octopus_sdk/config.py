"""Channel-neutral bot configuration contracts and registry publish policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from octopus_sdk.sessions import ProjectBinding


@dataclass(frozen=True)
class RegistryConnectionConfig:
    registry_id: str
    url: str
    enroll_token: str
    registry_scope: str
    poll_interval_seconds: float = 5.0


@dataclass(frozen=True)
class BotConfigBase:
    instance: str
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
    role_from_file: bool
    default_skills: tuple[str, ...]
    stream_update_interval_seconds: float
    typing_interval_seconds: float
    codex_sandbox: str
    codex_skip_git_repo_check: bool
    codex_full_auto: bool
    codex_dangerous: bool
    codex_profile: str
    codex_reasoning_effort: str
    admin_actor_keys: frozenset[str]
    admin_usernames: frozenset[str]
    admin_users_explicit: bool
    compact_mode: bool
    summary_model: str
    rate_limit_per_minute: int
    rate_limit_per_hour: int
    projects: tuple[ProjectBinding, ...]
    model_profiles: dict[str, str]
    default_model_profile: str
    public_working_dir: str
    public_model_profiles: frozenset[str]
    registry_url: str
    agent_mode: str
    agent_display_name: str
    agent_slug: str
    agent_role: str
    agent_tags: tuple[str, ...]
    agent_description: str
    agent_registries: tuple[RegistryConnectionConfig, ...]
    agent_poll_interval_seconds: float
    runtime_mode: str
    process_role: str
    claim_lease_ttl_seconds: int
    claim_sweep_interval_seconds: float
    delegation_timeout_seconds: int
    database_url: str
    db_pool_min_size: int
    db_pool_max_size: int
    db_connect_timeout_seconds: int
    registry_publish_level: str

    @property
    def provider(self) -> str:
        return self.provider_name


PUBLISH_LEVEL_KINDS: dict[str, set[str]] = {
    "minimal": {"message.user", "message.bot", "task.status", "error"},
    "standard": {
        "message.user",
        "message.bot",
        "task.status",
        "error",
        "provider.request",
        "provider.response",
        "tool.execution",
        "approval.requested",
        "approval.decided",
        "delegation.proposed",
        "delegation.submitted",
        "delegation.completed",
    },
    "full": {
        "message.user",
        "message.bot",
        "task.status",
        "error",
        "provider.request",
        "provider.response",
        "tool.execution",
        "approval.requested",
        "approval.decided",
        "delegation.proposed",
        "delegation.submitted",
        "delegation.completed",
    },
}


def should_publish_event(config: BotConfigBase, kind: str) -> bool:
    allowed = PUBLISH_LEVEL_KINDS.get(config.registry_publish_level)
    if allowed is None:
        return False
    return kind in allowed
