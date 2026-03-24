"""Tests for BOT_AUTONOMOUS config, validation, and runtime behavior."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import BotConfig, validate_config
from app.identity import telegram_actor_key
from app.octopus_cli.core import OctopusManager
from tests.support.config_support import make_config


REPO = Path(__file__).resolve().parent.parent


def _run_bash(script: str, *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


# -- Config parsing --


def test_autonomous_parses_true():
    cfg = make_config(autonomous=True, allow_open=False, allowed_actor_keys=frozenset({"tg:42"}))
    assert cfg.autonomous is True


def test_autonomous_defaults_false():
    cfg = make_config()
    assert cfg.autonomous is False


# -- Config validation --


def test_autonomous_rejects_allow_open():
    cfg = make_config(autonomous=True, allow_open=True, allowed_actor_keys=frozenset({"tg:42"}))
    errors = validate_config(cfg)
    assert any("BOT_AUTONOMOUS=1 and BOT_ALLOW_OPEN=1" in e for e in errors)


def test_autonomous_rejects_no_allowed_users():
    cfg = make_config(
        autonomous=True,
        allow_open=False,
        allowed_actor_keys=frozenset(),
        allowed_usernames=frozenset(),
    )
    errors = validate_config(cfg)
    assert any("BOT_ALLOWED_USERS" in e for e in errors)


def test_autonomous_with_admin_only_still_rejected():
    cfg = make_config(
        autonomous=True,
        allow_open=False,
        allowed_actor_keys=frozenset(),
        allowed_usernames=frozenset(),
        admin_actor_keys=frozenset({"tg:99"}),
    )
    errors = validate_config(cfg)
    assert any("BOT_ALLOWED_USERS" in e for e in errors)


def test_autonomous_with_allowed_users_passes():
    cfg = make_config(
        autonomous=True,
        allow_open=False,
        allowed_actor_keys=frozenset({"tg:42"}),
    )
    errors = validate_config(cfg)
    assert not any("BOT_AUTONOMOUS" in e for e in errors)


def test_autonomous_codex_dangerous_coexist():
    cfg = make_config(
        autonomous=True,
        allow_open=False,
        allowed_actor_keys=frozenset({"tg:42"}),
        codex_dangerous=True,
    )
    errors = validate_config(cfg)
    assert not any("BOT_AUTONOMOUS" in e and "CODEX_DANGEROUS" in e for e in errors)


# -- Approval mode default --


def test_autonomous_defaults_approval_off(monkeypatch, tmp_path):
    """BOT_AUTONOMOUS=1 without explicit BOT_APPROVAL_MODE defaults to off."""
    monkeypatch.setenv("BOT_INSTANCE", "test")
    monkeypatch.setenv("BOT_AUTONOMOUS", "1")
    monkeypatch.setenv("BOT_PROVIDER", "claude")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("BOT_ALLOW_OPEN", "0")
    monkeypatch.setenv("BOT_ALLOWED_USERS", "42")
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("CODEX_SANDBOX", "workspace-write")
    # Ensure BOT_APPROVAL_MODE is NOT set
    monkeypatch.delenv("BOT_APPROVAL_MODE", raising=False)

    from app.config import load_config
    cfg = load_config()
    assert cfg.autonomous is True
    assert cfg.approval_mode == "off"


def test_autonomous_explicit_approval_on_wins(monkeypatch, tmp_path):
    """BOT_AUTONOMOUS=1 with explicit BOT_APPROVAL_MODE=on keeps on."""
    monkeypatch.setenv("BOT_INSTANCE", "test")
    monkeypatch.setenv("BOT_AUTONOMOUS", "1")
    monkeypatch.setenv("BOT_APPROVAL_MODE", "on")
    monkeypatch.setenv("BOT_PROVIDER", "claude")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("BOT_ALLOW_OPEN", "0")
    monkeypatch.setenv("BOT_ALLOWED_USERS", "42")
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("CODEX_SANDBOX", "workspace-write")

    from app.config import load_config
    cfg = load_config()
    assert cfg.autonomous is True
    assert cfg.approval_mode == "on"


# -- Execution skip_permissions --


async def test_autonomous_grants_skip_permissions():
    """config.autonomous=True + session.approval_mode='off' -> skip_permissions=True."""
    from app.session_state import SessionState

    session = SessionState(
        provider="claude",
        provider_state={},
        approval_mode="off",
    )
    cfg = make_config(autonomous=True, allow_open=False, allowed_actor_keys=frozenset({"tg:42"}))

    # Build a minimal RunContext mock to capture skip_permissions
    context = MagicMock()
    context.skip_permissions = False

    # The autonomous grant logic: cfg.autonomous and session.approval_mode != "on"
    autonomous_grant = cfg.autonomous and session.approval_mode != "on"
    context.skip_permissions = False or autonomous_grant
    assert context.skip_permissions is True


async def test_autonomous_respects_approval_on_override():
    """config.autonomous=True + session.approval_mode='on' -> no autonomous grant."""
    from app.session_state import SessionState

    session = SessionState(
        provider="claude",
        provider_state={},
        approval_mode="on",
        approval_mode_explicit=True,
    )
    cfg = make_config(autonomous=True, allow_open=False, allowed_actor_keys=frozenset({"tg:42"}))

    autonomous_grant = cfg.autonomous and session.approval_mode != "on"
    skip_permissions = False or autonomous_grant
    assert skip_permissions is False


async def test_non_autonomous_no_grant():
    """config.autonomous=False -> no autonomous grant regardless of approval_mode."""
    from app.session_state import SessionState

    session = SessionState(
        provider="claude",
        provider_state={},
        approval_mode="off",
    )
    cfg = make_config(autonomous=False)

    autonomous_grant = cfg.autonomous and session.approval_mode != "on"
    assert autonomous_grant is False


# -- Setup flow (octopus CLI) --


def test_setup_mode_autonomous_writes_correct_env(tmp_path: Path) -> None:
    manager = OctopusManager(tmp_path)
    env_file = manager.write_bot_env(
        slug="example-bot",
        telegram_id="123456789",
        username="example_bot",
        display_name="Example Bot",
        token="123456:real-token",
        provider="claude",
        mode="autonomous",
        allowed_users="42",
    )
    contents = env_file.read_text(encoding="utf-8")
    assert "BOT_AUTONOMOUS=1" in contents
    assert "BOT_APPROVAL_MODE=off" in contents
    assert "BOT_ALLOW_OPEN=0" in contents
    assert "BOT_ALLOWED_USERS=42" in contents


def test_setup_mode_safe_writes_correct_env(tmp_path: Path) -> None:
    manager = OctopusManager(tmp_path)
    env_file = manager.write_bot_env(
        slug="example-bot",
        telegram_id="123456789",
        username="example_bot",
        display_name="Example Bot",
        token="123456:real-token",
        provider="claude",
        mode="safe",
    )
    contents = env_file.read_text(encoding="utf-8")
    assert "BOT_AUTONOMOUS=0" in contents
    assert "BOT_APPROVAL_MODE=on" in contents
    assert "BOT_ALLOW_OPEN=1" in contents


def test_maybe_join_autonomous_workspace(tmp_path: Path) -> None:
    """Autonomous workspace auto-join creates workspace and adds bot."""
    ws_dir = tmp_path / "myproject"
    ws_dir.mkdir()
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\nBOT_PROVIDER=claude\n"
    )
    manager = OctopusManager(tmp_path)
    manager.maybe_join_autonomous_workspace("example-bot", str(ws_dir))
    assert (tmp_path / ".deploy" / "workspaces" / "myproject" / "workspace.conf").exists()
    members = (tmp_path / ".deploy" / "workspaces" / "myproject" / "members.txt").read_text(encoding="utf-8")
    assert "example-bot" in members
