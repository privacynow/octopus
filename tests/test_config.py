"""Tests for config.py — env parsing, validation, webhook mode."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import load_config, load_dotenv_file, parse_allowed_users, validate_config
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

def test_main_calls_run_polling_in_poll_mode():
    """When BOT_MODE=poll, main() calls app.run_polling()."""
    cfg = make_config(bot_mode="poll")
    mock_app = MagicMock()
    with patch("app.main.load_config", return_value=cfg), \
         patch("app.main.make_provider"), \
         patch("app.main.fail_fast"), \
         patch("app.main.ensure_data_dirs"), \
         patch("app.main.startup_recovery"), \
         patch("app.main.build_application", return_value=mock_app), \
         patch("app.main.close_db"), \
         patch("sys.argv", ["bot"]):
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
    )
    mock_app = MagicMock()
    with patch("app.main.load_config", return_value=cfg), \
         patch("app.main.make_provider"), \
         patch("app.main.fail_fast"), \
         patch("app.main.ensure_data_dirs"), \
         patch("app.main.startup_recovery"), \
         patch("app.main.build_application", return_value=mock_app), \
         patch("app.main.close_db"), \
         patch("sys.argv", ["bot"]):
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
    )
    mock_app = MagicMock()
    with patch("app.main.load_config", return_value=cfg), \
         patch("app.main.make_provider"), \
         patch("app.main.fail_fast"), \
         patch("app.main.ensure_data_dirs"), \
         patch("app.main.startup_recovery"), \
         patch("app.main.build_application", return_value=mock_app), \
         patch("app.main.close_db"), \
         patch("sys.argv", ["bot"]):
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
