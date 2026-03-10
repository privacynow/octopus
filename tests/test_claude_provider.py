"""Tests for claude provider — command building, session state."""

import os
from pathlib import Path

from app.providers.claude import ClaudeProvider
from tests.support.config_support import make_config


def test_new_provider_state():
    p = ClaudeProvider(make_config())
    state = p.new_provider_state()
    assert bool(state.get("session_id"))
    assert state["started"] is False


def test_command_building_new_session():
    p = ClaudeProvider(make_config())
    state_new = {"session_id": "abc-123", "started": False}
    cmd = p._build_run_cmd(state_new, "hello world")
    assert "claude" in cmd
    assert "-p" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--verbose" in cmd
    assert "--session-id" in cmd
    assert "abc-123" in cmd
    assert cmd[-1] == "hello world"
    assert cmd[-2] == "--"


def test_command_building_resume():
    p = ClaudeProvider(make_config())
    state_resume = {"session_id": "abc-123", "started": True}
    cmd2 = p._build_run_cmd(state_resume, "continue")
    assert "--resume" in cmd2
    assert "abc-123" in cmd2
    assert "--session-id" not in cmd2


def test_command_building_with_model():
    state_new = {"session_id": "abc-123", "started": False}
    p2 = ClaudeProvider(make_config(model="claude-sonnet-4-6"))
    cmd3 = p2._build_run_cmd(state_new, "test")
    assert "--model" in cmd3
    assert "claude-sonnet-4-6" in cmd3


def test_command_building_extra_dirs():
    state_new = {"session_id": "abc-123", "started": False}
    p3 = ClaudeProvider(make_config(extra_dirs=(Path("/extra/dir"),)))
    cmd4 = p3._build_run_cmd(state_new, "test")
    assert "--add-dir" in cmd4
    assert "/extra/dir" in cmd4


def test_command_building_extra_dirs_from_retry():
    p = ClaudeProvider(make_config())
    state_new = {"session_id": "abc-123", "started": False}
    cmd5 = p._build_run_cmd(state_new, "test", extra_dirs=["/etc"])
    assert "--add-dir" in cmd5
    assert "/etc" in cmd5


def test_preflight_command():
    p = ClaudeProvider(make_config())
    cmd6 = p._build_preflight_cmd("test preflight")
    assert "claude" in cmd6
    assert "-p" in cmd6
    assert "--output-format" in cmd6
    assert "stream-json" in cmd6
    assert "--session-id" not in cmd6
    assert "--resume" not in cmd6


def test_clean_env():
    os.environ["CLAUDECODE"] = "1"
    env = ClaudeProvider._clean_env()
    assert "CLAUDECODE" not in env
    assert "PATH" in env
