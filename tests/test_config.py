"""Tests for config.py — env parsing, validation, webhook mode."""

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import _parse_projects, load_config, load_dotenv_file, parse_allowed_users, validate_config
from app.session_state import ProjectBinding
from tests.support.config_support import make_config


# -- load_dotenv_file --

def test_load_dotenv_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("KEY1=value1\n")
        f.write("KEY2='quoted'\n")
        f.write('KEY3="double"\n')
        f.write("# comment\n")
        f.write("\n")
        f.write("KEY4=has=equals\n")
        f.name
    result = load_dotenv_file(Path(f.name))
    assert result.get("KEY1") == "value1"
    assert result.get("KEY2") == "quoted"
    assert result.get("KEY3") == "double"
    assert ("comment" in result) == False
    assert result.get("KEY4") == "has=equals"
    os.unlink(f.name)

def test_load_dotenv_missing_file():
    assert load_dotenv_file(Path("/nonexistent/.env")) == {}


# -- parse_allowed_users --

def test_parse_allowed_users():
    ids, names = parse_allowed_users("123,456,@alice,bob")
    assert ids == {123, 456}
    assert names == {"alice", "bob"}

def test_parse_allowed_users_empty():
    ids2, names2 = parse_allowed_users("")
    assert (ids2, names2) == (set(), set())

def test_parse_allowed_users_only_commas():
    ids3, names3 = parse_allowed_users("  , ,")
    assert (ids3, names3) == (set(), set())


# -- validate_config --

def test_validate_config_valid():
    errors = validate_config(
        make_config(
            telegram_token="fake-token",
            allow_open=False,
            allowed_user_ids=frozenset({123}),
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    # May have "claude not found" if not installed, that's ok
    token_errors = [e for e in errors if "TOKEN" in e]
    assert token_errors == []

def test_validate_config_missing_token():
    errors2 = validate_config(
        make_config(
            telegram_token="",
            allow_open=False,
            allowed_user_ids=frozenset({123}),
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert any("TOKEN" in e for e in errors2)
    assert any(".env.bot" in e or "env file" in e for e in errors2)

def test_validate_config_bad_provider():
    errors3 = validate_config(
        make_config(
            telegram_token="fake-token",
            allow_open=False,
            allowed_user_ids=frozenset({123}),
            provider_name="invalid",
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert any("BOT_PROVIDER" in e for e in errors3)

def test_validate_config_no_users_no_open():
    errors4 = validate_config(
        make_config(
            telegram_token="fake-token",
            allowed_user_ids=frozenset(),
            allow_open=False,
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert any("BOT_ALLOWED_USERS" in e for e in errors4)
    assert any("BOT_ALLOW_OPEN" in e or ".env.bot" in e for e in errors4)


def test_startup_fails_with_clear_config_error():
    """Startup exits with CONFIG ERROR and points to the missing setting (Docker/onboarding)."""
    env = os.environ.copy()
    env["TELEGRAM_BOT_TOKEN"] = ""
    env["BOT_PROVIDER"] = "claude"
    env["BOT_ALLOW_OPEN"] = "1"
    env.pop("BOT_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "app.main"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    assert result.returncode == 1
    assert "CONFIG ERROR" in result.stderr
    assert "TELEGRAM_BOT_TOKEN" in result.stderr
    assert ".env.bot" in result.stderr or "env file" in result.stderr

def test_validate_config_open_access():
    errors5 = validate_config(
        make_config(
            telegram_token="fake-token",
            allowed_user_ids=frozenset(),
            allow_open=True,
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert [e for e in errors5 if "ALLOWED" in e] == []

def test_validate_config_codex_mutual_exclusion():
    errors6 = validate_config(
        make_config(
            telegram_token="fake-token",
            allow_open=False,
            allowed_user_ids=frozenset({123}),
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
            codex_full_auto=True,
            codex_dangerous=True,
        )
    )
    assert any("CODEX_FULL_AUTO" in e for e in errors6)


# -- BOT_SKILLS validation --

def test_validate_config_unknown_skill():
    errors_bad_skill = validate_config(make_config(default_skills=("nonexistent-skill-xyz",), provider_name="claude"))
    assert len([e for e in errors_bad_skill if "nonexistent-skill-xyz" in e]) > 0

def test_validate_config_valid_skill():
    errors_good_skill = validate_config(make_config(default_skills=("github-integration",), provider_name="claude"))
    assert len([e for e in errors_good_skill if "BOT_SKILLS" in e and "github-integration" in e]) == 0

def test_validate_config_no_skills():
    errors_no_skills = validate_config(make_config(default_skills=(), provider_name="claude"))
    assert len([e for e in errors_no_skills if "BOT_SKILLS" in e]) == 0


# -- Webhook / transport mode --

def test_validate_config_invalid_bot_mode():
    errors = validate_config(make_config(bot_mode="invalid"))
    assert any("BOT_MODE" in e for e in errors)

def test_validate_config_webhook_mode_requires_url():
    errors = validate_config(make_config(bot_mode="webhook", webhook_url=""))
    assert any("BOT_WEBHOOK_URL" in e for e in errors)

def test_validate_config_database_url_must_be_postgres():
    """BOT_DATABASE_URL when set must be a postgresql:// URL."""
    errors = validate_config(make_config(database_url="mysql://localhost/db"))
    assert any("BOT_DATABASE_URL" in e and "postgresql" in e for e in errors)
    errors_empty = validate_config(make_config(database_url=""))
    assert not any("BOT_DATABASE_URL" in e for e in errors_empty)
    errors_ok = validate_config(make_config(database_url="postgresql://localhost/bot"))
    assert not any("BOT_DATABASE_URL" in e for e in errors_ok)


def test_validate_config_webhook_mode_with_url():
    errors = validate_config(make_config(
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    ))
    webhook_errors = [e for e in errors if "webhook" in e.lower()]
    assert webhook_errors == []

def test_validate_config_poll_mode_no_webhook_errors():
    errors = validate_config(make_config(bot_mode="poll", webhook_url=""))
    webhook_errors = [e for e in errors if "webhook" in e.lower()]
    assert webhook_errors == []

def test_config_defaults_to_poll():
    cfg = make_config()
    assert cfg.bot_mode == "poll"
    assert cfg.webhook_port == 8443


# -- main.py mode selection --


def _runtime_ok_provider(name: str = "claude"):
    """Provider double that matches main()'s startup health contract."""
    provider = MagicMock()
    provider.name = name
    provider.check_runtime_health = AsyncMock(return_value=[])
    return provider


@contextmanager
def _patched_main_runtime(cfg, mock_app, provider=None):
    """Patch main() dependencies for mode-selection tests.

    main() now always validates provider runtime auth before starting, so the
    provider double must expose an awaitable check_runtime_health().
    """
    provider = provider or _runtime_ok_provider()

    @contextmanager
    def _fake_conn():
        yield MagicMock()

    with patch("app.main.load_config", return_value=cfg), \
         patch("app.main.make_provider", return_value=provider), \
         patch("app.main.fail_fast"), \
         patch("app.main.ensure_data_dirs"), \
         patch("app.main.startup_recovery"), \
         patch("app.main.build_application", return_value=mock_app), \
         patch("app.main.close_db"), \
         patch("app.main.close_transport_db"), \
         patch("app.main.recover_stale_claims"), \
         patch("app.main.purge_old"), \
         patch("app.db.postgres.get_connection", side_effect=lambda *a, **k: _fake_conn()), \
         patch("app.db.postgres_doctor.run_doctor", return_value=[]), \
         patch("app.db.postgres.close_pools"), \
         patch("sys.argv", ["bot"]):
        yield provider

def test_main_calls_run_polling_in_poll_mode():
    """When BOT_MODE=poll, main() calls app.run_polling()."""
    cfg = make_config(bot_mode="poll", database_url="postgresql://bot:bot@localhost:5432/bot")
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app):
        from app.main import main
        main()
    mock_app.run_polling.assert_called_once()
    mock_app.run_webhook.assert_not_called()


def test_main_calls_run_webhook_in_webhook_mode():
    """When BOT_MODE=webhook, main() calls app.run_webhook() with correct args."""
    cfg = make_config(
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        webhook_listen="0.0.0.0",
        webhook_port=8443,
        webhook_secret="my-secret",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app):
        from app.main import main
        main()
    mock_app.run_webhook.assert_called_once_with(
        listen="0.0.0.0",
        port=8443,
        webhook_url="https://bot.example.com/webhook",
        secret_token="my-secret",
        url_path="/webhook",
    )
    mock_app.run_polling.assert_not_called()


def test_main_webhook_empty_secret_passes_none():
    """Empty BOT_WEBHOOK_SECRET should pass secret_token=None."""
    cfg = make_config(
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        webhook_secret="",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app):
        from app.main import main
        main()
    call_kwargs = mock_app.run_webhook.call_args[1]
    assert call_kwargs["secret_token"] is None


def test_load_config_reads_webhook_env_vars():
    """load_config picks up BOT_MODE and webhook env vars from .env file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOWED_USERS=123\n")
        f.write("BOT_MODE=webhook\n")
        f.write("BOT_WEBHOOK_URL=https://example.com/hook\n")
        f.write("BOT_WEBHOOK_LISTEN=0.0.0.0\n")
        f.write("BOT_WEBHOOK_PORT=9443\n")
        f.write("BOT_WEBHOOK_SECRET=s3cret\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-wh")
        assert cfg.bot_mode == "webhook"
        assert cfg.webhook_url == "https://example.com/hook"
        assert cfg.webhook_listen == "0.0.0.0"
        assert cfg.webhook_port == 9443
        assert cfg.webhook_secret == "s3cret"
    finally:
        os.unlink(env_path)


def test_validate_config_rejects_shared_runtime_mode():
    """Phase 13: BOT_RUNTIME_MODE=shared is rejected until Phase 18."""
    errors = validate_config(make_config(runtime_mode="shared"))
    assert any("shared" in e.lower() and "phase 18" in e.lower() for e in errors)


def test_validate_config_accepts_local_runtime_mode():
    """Phase 13: BOT_RUNTIME_MODE=local is valid (default)."""
    errors = validate_config(make_config(runtime_mode="local"))
    runtime_errors = [e for e in errors if "RUNTIME" in e or "runtime" in e]
    assert runtime_errors == []


def test_load_config_reads_database_url_and_pool_settings():
    """load_config picks up BOT_DATABASE_URL and pool settings from .env."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("BOT_DATABASE_URL=postgresql://localhost:5432/botdb\n")
        f.write("BOT_DB_POOL_MIN_SIZE=2\n")
        f.write("BOT_DB_POOL_MAX_SIZE=20\n")
        f.write("BOT_DB_CONNECT_TIMEOUT=15\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-db")
        assert cfg.database_url == "postgresql://localhost:5432/botdb"
        assert cfg.db_pool_min_size == 2
        assert cfg.db_pool_max_size == 20
        assert cfg.db_connect_timeout_seconds == 15
    finally:
        os.unlink(env_path)


# -- Config validation edge cases (from test_high_risk.py) --


def test_config_bad_timeout():
    """Non-integer BOT_TIMEOUT_SECONDS must produce a friendly SystemExit."""
    old_env = os.environ.get("BOT_TIMEOUT_SECONDS")
    old_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    old_provider = os.environ.get("BOT_PROVIDER")
    old_working_dir = os.environ.get("BOT_WORKING_DIR")
    old_data_dir = os.environ.get("BOT_DATA_DIR")
    old_allow_open = os.environ.get("BOT_ALLOW_OPEN")
    os.environ["TELEGRAM_BOT_TOKEN"] = "x"
    os.environ["BOT_PROVIDER"] = "claude"
    os.environ["BOT_WORKING_DIR"] = tempfile.gettempdir()
    os.environ["BOT_DATA_DIR"] = tempfile.gettempdir()
    os.environ["BOT_ALLOW_OPEN"] = "1"
    os.environ["BOT_TIMEOUT_SECONDS"] = "not_a_number"
    try:
        load_config("test")
        assert False, "bad timeout should raise SystemExit"
    except SystemExit as exc:
        assert "BOT_TIMEOUT_SECONDS must be an integer" in str(exc)
    finally:
        if old_env is not None:
            os.environ["BOT_TIMEOUT_SECONDS"] = old_env
        else:
            os.environ.pop("BOT_TIMEOUT_SECONDS", None)
        for key, value in (
            ("TELEGRAM_BOT_TOKEN", old_token),
            ("BOT_PROVIDER", old_provider),
            ("BOT_WORKING_DIR", old_working_dir),
            ("BOT_DATA_DIR", old_data_dir),
            ("BOT_ALLOW_OPEN", old_allow_open),
        ):
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)


def test_data_dir_writable():
    cfg_writable = make_config(data_dir=Path("/tmp"))
    errors_writable = [e for e in validate_config(cfg_writable) if "DATA_DIR" in e]
    assert errors_writable == []


def test_data_dir_unwritable():
    cfg_bad = make_config(data_dir=Path("/root/impossible/path"))
    errors_bad = [e for e in validate_config(cfg_bad) if "DATA_DIR" in e]
    assert len(errors_bad) > 0


def test_data_dir_is_file():
    with tempfile.NamedTemporaryFile() as f:
        cfg_file = make_config(data_dir=Path(f.name))
        errors_file = [e for e in validate_config(cfg_file) if "DATA_DIR" in e]
        assert len(errors_file) > 0


def test_extra_dirs_valid():
    cfg_good_dirs = make_config(extra_dirs=(Path("/tmp"),))
    errors_good = [e for e in validate_config(cfg_good_dirs) if "EXTRA_DIRS" in e]
    assert errors_good == []


def test_extra_dirs_nonexistent():
    cfg_bad_dirs = make_config(extra_dirs=(Path("/nonexistent/fake/dir"),))
    errors_bad = [e for e in validate_config(cfg_bad_dirs) if "EXTRA_DIRS" in e]
    assert len(errors_bad) > 0


def test_extra_dirs_mixed():
    cfg_mixed = make_config(extra_dirs=(Path("/tmp"), Path("/no/such/path")))
    errors_mixed = [e for e in validate_config(cfg_mixed) if "EXTRA_DIRS" in e]
    assert len(errors_mixed) == 1


def test_config_isolation():
    """load_config() must not leak state across instances."""
    import app.config as config_mod

    env_a = {
        "TELEGRAM_BOT_TOKEN": "token-a",
        "BOT_PROVIDER": "claude",
        "BOT_WORKING_DIR": tempfile.gettempdir(),
        "BOT_DATA_DIR": tempfile.gettempdir(),
        "BOT_ALLOW_OPEN": "1",
        "BOT_MODEL": "model-a",
    }
    env_b = {
        "TELEGRAM_BOT_TOKEN": "token-b",
        "BOT_PROVIDER": "codex",
        "BOT_WORKING_DIR": tempfile.gettempdir(),
        "BOT_DATA_DIR": tempfile.gettempdir(),
        "BOT_ALLOW_OPEN": "1",
        "BOT_MODEL": "model-b",
    }

    orig_env_path = config_mod.env_path_for_instance
    try:
        # Instance A
        config_mod.env_path_for_instance = lambda name: Path("/dev/null")
        saved = {k: os.environ.get(k) for k in env_a}
        os.environ.update(env_a)
        cfg_a = load_config("inst-a")

        # Instance B — different env
        os.environ.update(env_b)
        cfg_b = load_config("inst-b")

        assert cfg_a.model == "model-a"
        assert cfg_b.model == "model-b"
        assert cfg_a.provider_name == "claude"
        assert cfg_b.provider_name == "codex"
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        config_mod.env_path_for_instance = orig_env_path


# -- _parse_projects (Phase 15: ProjectBinding with | separator) --


def test_parse_projects_minimal():
    """Name and path only — no optional fields."""
    result = _parse_projects("frontend:/home/app/frontend")
    assert len(result) == 1
    assert result[0] == ProjectBinding(name="frontend", root_dir="/home/app/frontend")
    assert result[0].file_policy == ""
    assert result[0].model_profile == ""


def test_parse_projects_with_policy():
    """Name, path, and file_policy via | separator."""
    result = _parse_projects("frontend:/home/app/frontend|inspect")
    assert len(result) == 1
    assert result[0].name == "frontend"
    assert result[0].root_dir == "/home/app/frontend"
    assert result[0].file_policy == "inspect"
    assert result[0].model_profile == ""


def test_parse_projects_with_policy_and_profile():
    """Full format: name:/path|policy|profile."""
    result = _parse_projects("frontend:/home/app/frontend|edit|fast")
    assert len(result) == 1
    assert result[0].file_policy == "edit"
    assert result[0].model_profile == "fast"


def test_parse_projects_multiple():
    """Multiple projects comma-separated."""
    result = _parse_projects(
        "fe:/home/fe|inspect, be:/home/be|edit|best"
    )
    assert len(result) == 2
    assert result[0].name == "fe"
    assert result[0].file_policy == "inspect"
    assert result[1].name == "be"
    assert result[1].model_profile == "best"


def test_parse_projects_empty_and_whitespace():
    """Empty string and whitespace-only produce no projects."""
    assert _parse_projects("") == ()
    assert _parse_projects("   ") == ()


def test_parse_projects_skip_malformed():
    """Entries missing ':' or missing name/path are skipped."""
    result = _parse_projects("good:/tmp, bad-no-colon, :/no-name, empty:, good2:/tmp")
    names = [p.name for p in result]
    assert names == ["good", "good2"]


def test_parse_projects_empty_policy_placeholder():
    """Empty policy field with profile: name:/path||fast."""
    result = _parse_projects("fe:/home/fe||fast")
    assert result[0].file_policy == ""
    assert result[0].model_profile == "fast"


# -- validate_config: project field validation --


def test_validate_config_rejects_invalid_file_policy():
    """file_policy must be 'inspect', 'edit', or empty."""
    cfg = make_config(projects=(
        ProjectBinding(name="bad", root_dir="/tmp", file_policy="write"),
    ))
    errors = validate_config(cfg)
    assert any("file_policy" in e and "'bad'" in e for e in errors)


def test_validate_config_accepts_valid_file_policies():
    """inspect, edit, and empty are all valid."""
    for policy in ("inspect", "edit", ""):
        cfg = make_config(projects=(
            ProjectBinding(name="ok", root_dir="/tmp", file_policy=policy),
        ))
        errors = validate_config(cfg)
        policy_errors = [e for e in errors if "file_policy" in e]
        assert policy_errors == [], f"Unexpected error for policy '{policy}': {policy_errors}"


def test_validate_config_rejects_unknown_model_profile():
    """model_profile must exist in model_profiles when profiles are configured."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile="nonexistent"),
        ),
        model_profiles={"fast": "claude-haiku-4-5-20251001"},
    )
    errors = validate_config(cfg)
    assert any("model_profile" in e and "'proj'" in e for e in errors)


def test_validate_config_rejects_model_profile_when_no_profiles_configured():
    """model_profile set but no BOT_MODEL_PROFILES configured is an error."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile="anything"),
        ),
        model_profiles={},
    )
    errors = validate_config(cfg)
    profile_errors = [e for e in errors if "model_profile" in e]
    assert len(profile_errors) == 1
    assert "no BOT_MODEL_PROFILES" in profile_errors[0]


def test_validate_config_allows_empty_model_profile_when_no_profiles_configured():
    """Empty model_profile with no BOT_MODEL_PROFILES is fine (no default to resolve)."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile=""),
        ),
        model_profiles={},
    )
    errors = validate_config(cfg)
    profile_errors = [e for e in errors if "model_profile" in e]
    assert profile_errors == []


def test_validate_config_accepts_known_model_profile():
    """Profile that exists in model_profiles is valid."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile="fast"),
        ),
        model_profiles={"fast": "claude-haiku-4-5-20251001"},
    )
    errors = validate_config(cfg)
    profile_errors = [e for e in errors if "model_profile" in e]
    assert profile_errors == []


def test_validate_config_duplicate_project_names():
    """Duplicate project names are rejected."""
    cfg = make_config(projects=(
        ProjectBinding(name="dup", root_dir="/tmp"),
        ProjectBinding(name="dup", root_dir="/tmp"),
    ))
    errors = validate_config(cfg)
    assert any("Duplicate" in e and "'dup'" in e for e in errors)
