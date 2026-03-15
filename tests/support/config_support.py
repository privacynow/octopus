"""Shared BotConfig factory for tests."""

from pathlib import Path

from app.config import BotConfig
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
    defaults = dict(
        instance="test",
        telegram_token="x",
        allow_open=True,
        allowed_user_ids=frozenset(),
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
        admin_user_ids=frozenset(),
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
        projects=(),
        model_profiles={},
        default_model_profile="",
        public_working_dir="",
        public_model_profiles=frozenset(),
        registry_url="",
        runtime_mode="local",
        database_url="",
        db_pool_min_size=1,
        db_pool_max_size=10,
        db_connect_timeout_seconds=10,
    )
    defaults.update(overrides)
    if "projects" in defaults:
        defaults["projects"] = _normalize_projects(defaults["projects"])
    return BotConfig(**defaults)
