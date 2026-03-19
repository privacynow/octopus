"""Shared BotConfig factory for tests."""

from pathlib import Path

from app.config import BotConfig
from app.identity import telegram_actor_key
from app.session_state import ProjectBinding


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
    if "allowed_user_ids" in overrides and "allowed_actor_keys" not in overrides:
        overrides["allowed_actor_keys"] = frozenset(
            telegram_actor_key(user_id) for user_id in overrides.pop("allowed_user_ids")
        )
    if "admin_user_ids" in overrides and "admin_actor_keys" not in overrides:
        overrides["admin_actor_keys"] = frozenset(
            telegram_actor_key(user_id) for user_id in overrides.pop("admin_user_ids")
        )
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
        credential_key="",
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
        agent_capabilities=(),
        agent_registry_url="",
        agent_registry_enroll_token="",
        agent_poll_interval_seconds=5.0,
        runtime_mode="local",
        process_role="all",
        claim_lease_ttl_seconds=300,
        claim_sweep_interval_seconds=60.0,
        database_url="",
        db_pool_min_size=1,
        db_pool_max_size=10,
        db_connect_timeout_seconds=10,
    )
    defaults.update(overrides)
    if "projects" in defaults:
        defaults["projects"] = _normalize_projects(defaults["projects"])
    return BotConfig(**defaults)
