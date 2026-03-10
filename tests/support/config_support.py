"""Shared BotConfig factory for tests."""

from pathlib import Path

from app.config import BotConfig


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
        registry_url="",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)
