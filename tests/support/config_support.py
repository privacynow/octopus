"""Shared BotConfig factory for tests."""

import os
from pathlib import Path

from app.config import BotConfig
from octopus_sdk.config import RegistryConnectionConfig
from octopus_sdk.identity import telegram_actor_key
from octopus_sdk.sessions import ProjectBinding


def make_registry_connection(
    *,
    registry_id: str = "default",
    url: str = "http://registry.test",
    enroll_token: str = "enroll-secret",
    registry_scope: str = "full",
    poll_interval_seconds: float = 5.0,
) -> RegistryConnectionConfig:
    return RegistryConnectionConfig(
        registry_id=registry_id,
        url=url,
        enroll_token=enroll_token,
        registry_scope=registry_scope,
        poll_interval_seconds=poll_interval_seconds,
    )


def _normalize_projects(projects):
    """Convert raw tuples to ProjectBinding for backward compatibility with existing tests."""
    if not projects:
        return ()
    result = []
    for p in projects:
        if isinstance(p, ProjectBinding):
            result.append(p)
        elif isinstance(p, tuple):
            # (name, root_dir, extra_dirs) or (name, root_dir, extra_dirs, file_policy, model_profile)
            name = p[0]
            root_dir = p[1]
            extra_dirs = p[2] if len(p) > 2 else ()
            file_policy = p[3] if len(p) > 3 else ""
            model_profile = p[4] if len(p) > 4 else ""
            result.append(ProjectBinding(
                name=name, root_dir=root_dir, extra_dirs=extra_dirs,
                file_policy=file_policy, model_profile=model_profile,
            ))
        else:
            result.append(p)
    return tuple(result)


def make_config(*, data_dir: Path = Path("/tmp/test-data"), **overrides) -> BotConfig:
    test_registry_agent_ids = dict(overrides.pop("registry_agent_ids", {}))
    defaults = dict(
        instance="test",
        telegram_token="x",
        allow_open=True,
        allowed_actor_keys=frozenset(),
        allowed_usernames=frozenset(),
        provider_name="claude",
        model="",
        working_dir=Path("/home/test"),
        extra_dirs=(),
        data_dir=data_dir,
        timeout_seconds=300,
        approval_mode="on",
        autonomous=False,
        role="",
        role_from_file=False,
        default_skills=(),
        stream_update_interval_seconds=1.0,
        typing_interval_seconds=4.0,
        codex_sandbox="workspace-write",
        codex_skip_git_repo_check=True,
        codex_full_auto=False,
        codex_dangerous=False,
        codex_profile="",
        admin_actor_keys=frozenset(),
        admin_usernames=frozenset(),
        admin_users_explicit=False,
        compact_mode=False,
        summary_model="claude-haiku-4-5-20251001",
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
        credential_key="test-credential-key",
        projects=(),
        model_profiles={},
        default_model_profile="",
        public_working_dir="",
        public_model_profiles=frozenset(),
        registry_url="",
        agent_mode="standalone",
        agent_display_name="test",
        agent_slug="test",
        agent_role="",
        agent_tags=(),
        agent_description="",
        agent_registries=(),
        agent_poll_interval_seconds=5.0,
        runtime_mode="local",
        process_role="all",
        claim_lease_ttl_seconds=300,
        claim_sweep_interval_seconds=60.0,
        delegation_timeout_seconds=3600,
        database_url=os.environ.get("OCTOPUS_DATABASE_URL", ""),
        db_pool_min_size=1,
        db_pool_max_size=10,
        db_connect_timeout_seconds=10,
        registry_publish_level="standard",
    )
    defaults.update(overrides)
    if "projects" in defaults:
        defaults["projects"] = _normalize_projects(defaults["projects"])
    cfg = BotConfig(**defaults)
    if test_registry_agent_ids:
        object.__setattr__(cfg, "_test_registry_agent_ids", test_registry_agent_ids)
    return cfg
