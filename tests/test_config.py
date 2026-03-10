"""Tests for config.py — env parsing, validation."""

import os
import tempfile
from pathlib import Path

from app.config import load_dotenv_file, parse_allowed_users, validate_config
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
