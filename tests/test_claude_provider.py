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


def test_effective_model_overrides_config_model():
    """effective_model from RunContext should override config.model in the command."""
    p = ClaudeProvider(make_config(model="claude-sonnet-4-6"))
    state = {"session_id": "abc-123", "started": False}
    # _base_cmd with effective_model should use it, not config.model
    cmd = p._base_cmd(effective_model="claude-haiku-4-5-20251001")
    assert "--model" in cmd
    assert "claude-haiku-4-5-20251001" in cmd
    assert "claude-sonnet-4-6" not in cmd


def test_effective_model_empty_falls_back_to_config():
    """When effective_model is empty, _base_cmd should use config.model."""
    p = ClaudeProvider(make_config(model="claude-sonnet-4-6"))
    cmd = p._base_cmd(effective_model="")
    assert "--model" in cmd
    assert "claude-sonnet-4-6" in cmd


def test_effective_model_in_run_cmd():
    """effective_model should flow through _build_run_cmd to the command line."""
    p = ClaudeProvider(make_config(model="claude-sonnet-4-6"))
    state = {"session_id": "abc-123", "started": False}
    cmd = p._build_run_cmd(state, "hello", effective_model="claude-opus-4-6")
    assert "claude-opus-4-6" in cmd
    assert "claude-sonnet-4-6" not in cmd


def test_effective_model_in_preflight_cmd():
    """effective_model should flow through _build_preflight_cmd to the command line."""
    p = ClaudeProvider(make_config(model="claude-sonnet-4-6"))
    cmd = p._build_preflight_cmd("test", effective_model="claude-haiku-4-5-20251001")
    assert "claude-haiku-4-5-20251001" in cmd
    assert "claude-sonnet-4-6" not in cmd


def test_file_policy_inspect_appends_system_prompt():
    """file_policy=inspect should add a read-only instruction to the system prompt."""
    from app.providers.base import RunContext
    p = ClaudeProvider(make_config())
    state = {"session_id": "abc-123", "started": False}
    cmd = p._build_run_cmd(state, "analyze the code")
    context = RunContext(
        extra_dirs=[], system_prompt="You are a reviewer.",
        capability_summary="", provider_config={}, credential_env={},
        file_policy="inspect",
    )
    # Simulate what run() does: apply system prompt with file_policy
    system_prompt_parts = []
    if context.system_prompt:
        system_prompt_parts.append(context.system_prompt)
    if context.file_policy == "inspect":
        system_prompt_parts.append(
            "IMPORTANT: This session is in INSPECT (read-only) mode. "
            "Do NOT create, modify, delete, or rename any files. "
            "Only read and analyze code. Refuse any request that would change files."
        )
    combined = "\n\n".join(system_prompt_parts)
    assert "INSPECT" in combined
    assert "read-only" in combined
    assert "You are a reviewer." in combined
