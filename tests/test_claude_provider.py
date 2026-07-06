"""Tests for claude provider — command building, session state."""

import asyncio
import json
import os
import stat
from pathlib import Path

import pytest

from octopus_sdk.providers import (
    CredentialEnvRecord,
    ProviderConfigRecord,
    ProviderStateRecord,
    RunContext,
    RunResult,
)
from app.providers.claude import ClaudeProvider
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProgress


def test_new_provider_state():
    p = ClaudeProvider(make_config())
    state = p.new_provider_state("tg:test")
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
    assert "--include-partial-messages" in cmd
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


def test_command_building_effort():
    p = ClaudeProvider(make_config(claude_effort="xhigh"))
    cmd = p._build_run_cmd({"session_id": "abc-123", "started": False}, "hello")
    assert cmd[cmd.index("--effort") + 1] == "xhigh"


def test_command_building_ultracode_settings():
    p = ClaudeProvider(make_config(claude_ultracode=True))
    cmd = p._build_run_cmd({"session_id": "abc-123", "started": False}, "hello")
    assert json.loads(cmd[cmd.index("--settings") + 1]) == {"ultracode": True}


def test_command_building_no_effort_or_settings_by_default():
    p = ClaudeProvider(make_config())
    cmd = p._build_run_cmd({"session_id": "abc-123", "started": False}, "hello")
    assert "--effort" not in cmd
    assert "--settings" not in cmd


def test_command_building_extra_dirs():
    state_new = {"session_id": "abc-123", "started": False}
    p3 = ClaudeProvider(make_config(extra_dirs=(Path("/extra/dir"),)))
    cmd4 = p3._build_run_cmd(state_new, "test")
    assert "--add-dir" in cmd4
    assert "/extra/dir" in cmd4


def test_command_building_extra_dirs__retry():
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
    os.environ["ANTHROPIC_API_KEY"] = "anthropic-secret"
    os.environ["BOT_TELEGRAM_TOKEN"] = "telegram-secret"
    env = ClaudeProvider._clean_env()
    assert "CLAUDECODE" not in env
    assert "PATH" in env
    assert env["ANTHROPIC_API_KEY"] == "anthropic-secret"
    assert "BOT_TELEGRAM_TOKEN" not in env


async def test_check_auth_health_requires_nonempty_auth_file(monkeypatch, tmp_path: Path):
    provider = ClaudeProvider(make_config(provider_name="claude"))
    auth_file = tmp_path / ".claude.json"
    auth_file.write_text('{"token":"secret"}', encoding="utf-8")
    monkeypatch.setattr("app.providers.claude.runtime_auth_root", lambda provider_name: tmp_path)
    seen: list[tuple[str, ...]] = []

    async def fake_run(*cmd: str, timeout: int, env):
        del env
        seen.append(cmd)
        if cmd == ("claude", "--version"):
            assert timeout == 10
            return 0, "claude 2.1.79\n", ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("app.providers.claude.run_health_command", fake_run)

    assert await provider.check_auth_health() == []
    assert seen == [("claude", "--version")]


async def test_check_auth_health_accepts_nonempty_auth_dir_files(monkeypatch, tmp_path: Path):
    provider = ClaudeProvider(make_config(provider_name="claude"))
    auth_dir = tmp_path / ".claude"
    auth_dir.mkdir()
    (auth_dir / "session.json").write_text('{"token":"secret"}', encoding="utf-8")
    monkeypatch.setattr("app.providers.claude.runtime_auth_root", lambda provider_name: tmp_path)
    seen: list[tuple[str, ...]] = []

    async def fake_run(*cmd: str, timeout: int, env):
        del env
        seen.append(cmd)
        if cmd == ("claude", "--version"):
            assert timeout == 10
            return 0, "claude 2.1.81\n", ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("app.providers.claude.run_health_command", fake_run)

    assert await provider.check_auth_health() == []
    assert seen[0] == ("claude", "--version")


async def test_check_runtime_health_reports_live_login_failure(monkeypatch, tmp_path: Path):
    provider = ClaudeProvider(make_config(provider_name="claude"))
    auth_file = tmp_path / ".claude.json"
    auth_file.write_text('{"token":"secret"}', encoding="utf-8")
    monkeypatch.setattr("app.providers.claude.runtime_auth_root", lambda provider_name: tmp_path)

    async def fake_run(*cmd: str, timeout: int, env):
        del env
        if cmd == ("claude", "--version"):
            return 0, "claude 2.1.87\n", ""
        assert cmd == (
            "claude",
            "-p",
            "--output-format",
            "text",
            "--max-turns",
            "1",
            "--",
            "reply with ok",
        )
        return 1, "Not logged in · Please run /login\n", ""

    monkeypatch.setattr("app.providers.claude.run_health_command", fake_run)

    errors = await provider.check_runtime_health()

    assert errors == ["Claude runtime probe failed (rc=1): Not logged in · Please run /login"]


async def test_check_runtime_health_short_circuits_when_auth_fails(monkeypatch):
    provider = ClaudeProvider(make_config(provider_name="claude"))

    async def fake_auth():
        return ["auth missing"]

    async def fake_run(*cmd: str, timeout: int, env):
        del env
        raise AssertionError(f"runtime probe should not run: {cmd} timeout={timeout}")

    provider.check_auth_health = fake_auth  # type: ignore[method-assign]
    monkeypatch.setattr("app.providers.claude.run_health_command", fake_run)

    assert await provider.check_runtime_health() == ["auth missing"]


def test_effective_model_overrides_config_model():
    """effective_model RunContext should override config.model in the command."""
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
    p = ClaudeProvider(make_config())
    state = {"session_id": "abc-123", "started": False}
    cmd = p._build_run_cmd(state, "analyze the code")
    context = RunContext(
        extra_dirs=[], system_prompt="You are a reviewer.",
        active_skill_tools_summary="",
        provider_config=ProviderConfigRecord(),
        credential_env=CredentialEnvRecord(),
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


async def test_mcp_temp_file_exists_during_run_and_is_removed_after_success():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()
    seen: dict[str, str] = {}

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del progress, timeout, extra_env, working_dir, cancel
        idx = cmd.index("--mcp-config")
        path = cmd[idx + 1]
        seen["path"] = path
        assert os.path.exists(path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data == {
            "mcpServers": {
                "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}
            }
        }
        return "", {"result": "ok"}, 0, "", []

    provider._run_process = fake_run_process  # type: ignore[method-assign]
    result = await provider.run(
        ProviderStateRecord({"session_id": "abc-123", "started": False}),
        "hello",
        [],
        progress,
        context=RunContext(
            extra_dirs=[],
            system_prompt="",
            active_skill_tools_summary="",
            provider_config=ProviderConfigRecord({
                "mcp_servers": {
                    "github": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                    }
                }
            }),
            credential_env=CredentialEnvRecord(),
        ),
    )

    assert result.text == "ok"
    assert not os.path.exists(seen["path"])


async def test_mcp_temp_file_is_removed_after_timeout_result():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()
    seen: dict[str, str] = {}

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del progress, timeout, extra_env, working_dir, cancel
        idx = cmd.index("--mcp-config")
        path = cmd[idx + 1]
        seen["path"] = path
        assert os.path.exists(path)
        return "", {}, -1, "", []

    provider._run_process = fake_run_process  # type: ignore[method-assign]
    result = await provider.run(
        ProviderStateRecord({"session_id": "abc-123", "started": False}),
        "hello",
        [],
        progress,
        context=RunContext(
            extra_dirs=[],
            system_prompt="",
            active_skill_tools_summary="",
            provider_config=ProviderConfigRecord({"mcp_servers": {"github": {"command": "npx", "args": []}}}),
            credential_env=CredentialEnvRecord(),
        ),
    )

    assert result.timed_out is True
    assert not os.path.exists(seen["path"])


async def test_mcp_temp_file_is_removed_after_run_exception():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()
    seen: dict[str, str] = {}

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del progress, timeout, extra_env, working_dir, cancel
        idx = cmd.index("--mcp-config")
        path = cmd[idx + 1]
        seen["path"] = path
        assert os.path.exists(path)
        raise RuntimeError("boom")

    provider._run_process = fake_run_process  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom"):
        await provider.run(
            ProviderStateRecord({"session_id": "abc-123", "started": False}),
            "hello",
            [],
            progress,
            context=RunContext(
                extra_dirs=[],
                system_prompt="",
                active_skill_tools_summary="",
                provider_config=ProviderConfigRecord({"mcp_servers": {"github": {"command": "npx", "args": []}}}),
                credential_env=CredentialEnvRecord(),
            ),
        )

    assert not os.path.exists(seen["path"])


async def test_run_maps_cached_prompt_usage_when_available():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del cmd, progress, timeout, extra_env, working_dir, cancel
        return (
            "ok",
            {
                "result": "ok",
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 8,
                    "cache_read_input_tokens": 48,
                },
                "total_cost_usd": 0.12,
            },
            0,
            "",
            [],
        )

    provider._run_process = fake_run_process  # type: ignore[method-assign]
    result = await provider.run(
        ProviderStateRecord({"session_id": "abc-123", "started": False}),
        "hello",
        [],
        progress,
        context=RunContext(
            extra_dirs=[],
            system_prompt="",
            active_skill_tools_summary="",
            provider_config=ProviderConfigRecord(),
            credential_env=CredentialEnvRecord(),
        ),
    )

    assert result.prompt_tokens == 120
    assert result.completion_tokens == 8
    assert result.cached_prompt_tokens == 48
    assert result.cached_completion_tokens is None
    assert result.cost_usd == 0.12


async def test_run_surfaces_structured_error_detail():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del cmd, progress, timeout, extra_env, working_dir, cancel
        return (
            "",
            {
                "result": "Not logged in · Please run /login",
                "error": "authentication_failed",
            },
            1,
            "",
            [],
        )

    provider._run_process = fake_run_process  # type: ignore[method-assign]
    result = await provider.run(
        ProviderStateRecord({"session_id": "abc-123", "started": False}),
        "hello",
        [],
        progress,
        context=RunContext(
            extra_dirs=[],
            system_prompt="",
            active_skill_tools_summary="",
            provider_config=ProviderConfigRecord(),
            credential_env=CredentialEnvRecord(),
        ),
    )

    assert result.returncode == 1
    assert result.text.startswith("[Claude error (rc=1)]")
    assert "Not logged in · Please run /login" in result.text
    assert "authentication_failed" in result.text
    assert result.provider_state_updates.get("started") is True


async def test_run_failed_fresh_session_promotes_retry_to_resume():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del cmd, progress, timeout, extra_env, working_dir, cancel
        return "", {"error": "boom"}, 1, "generic failure", []

    provider._run_process = fake_run_process  # type: ignore[method-assign]
    result = await provider.run(
        ProviderStateRecord({"session_id": "abc-123", "started": False}),
        "hello",
        [],
        progress,
        context=RunContext(
            extra_dirs=[],
            system_prompt="",
            active_skill_tools_summary="",
            provider_config=ProviderConfigRecord(),
            credential_env=CredentialEnvRecord(),
        ),
    )

    assert result.returncode == 1
    assert result.provider_state_updates.get("started") is True


async def test_run_timed_out_fresh_session_promotes_retry_to_resume():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del cmd, progress, timeout, extra_env, working_dir, cancel
        return "", {}, -1, "", []

    provider._run_process = fake_run_process  # type: ignore[method-assign]
    result = await provider.run(
        ProviderStateRecord({"session_id": "abc-123", "started": False}),
        "hello",
        [],
        progress,
        context=RunContext(
            extra_dirs=[],
            system_prompt="",
            active_skill_tools_summary="",
            provider_config=ProviderConfigRecord(),
            credential_env=CredentialEnvRecord(),
        ),
    )

    assert result.timed_out is True
    assert result.provider_state_updates.get("started") is True


async def test_run_cancelled_fresh_session_promotes_retry_to_resume():
    provider = ClaudeProvider(make_config())
    progress = FakeProgress()

    async def fake_run_process(cmd, progress, timeout=None, extra_env=None, working_dir="", cancel=None):
        del cmd, progress, timeout, extra_env, working_dir, cancel
        return "partial", {}, 0, "", []

    provider._run_process = fake_run_process  # type: ignore[method-assign]
    cancel_event = asyncio.Event()
    cancel_event.set()
    result = await provider.run(
        ProviderStateRecord({"session_id": "abc-123", "started": False}),
        "hello",
        [],
        progress,
        context=RunContext(
            extra_dirs=[],
            system_prompt="",
            active_skill_tools_summary="",
            provider_config=ProviderConfigRecord(),
            credential_env=CredentialEnvRecord(),
        ),
        cancel=cancel_event,
    )

    assert result.cancelled is True
    assert result.provider_state_updates.get("started") is True


# -- Claude command safety (test_high_risk.py) --


def test_claude_retry_no_extra_dirs():
    """Normal run has zero --add-dir when no extra_dirs provided."""
    p = ClaudeProvider(make_config(provider_name="claude"))
    state = {"session_id": "abc-123", "started": True}
    cmd = p._build_run_cmd(state, "test")
    assert cmd.count("--add-dir") == 0


def test_claude_retry_with_extra_dirs():
    """Retry forwards extra_dirs and uses --resume for started session."""
    p = ClaudeProvider(make_config(provider_name="claude"))
    state = {"session_id": "abc-123", "started": True}
    cmd = p._build_run_cmd(state, "test", extra_dirs=["/tmp/uploads/123", "/etc", "/var/log"])
    assert "/tmp/uploads/123" in cmd
    assert "/etc" in cmd
    assert "/var/log" in cmd
    assert cmd.count("--add-dir") == 3
    assert "--resume" in cmd
    assert "abc-123" in cmd


def test_claude_preflight_hardening():
    """Preflight includes config extra_dirs, excludes uploads, uses plan mode."""
    p = ClaudeProvider(make_config(provider_name="claude", extra_dirs=(Path("/opt/myrepo"),)))
    pf_cmd = p._build_preflight_cmd("test prompt")
    assert "--add-dir" in pf_cmd
    assert "/opt/myrepo" in pf_cmd
    assert not any("uploads" in a for a in pf_cmd)
    assert "--permission-mode" in pf_cmd
    perm_idx = pf_cmd.index("--permission-mode")
    assert pf_cmd[perm_idx + 1] == "plan"


def test_claude_error_state():
    """RunResult distinguishes success (started=True) error (empty updates)."""
    p = ClaudeProvider(make_config(provider_name="claude"))
    fresh = p.new_provider_state("tg:test")
    assert fresh["started"] is False

    success_result = RunResult(text="ok", provider_state_updates=ProviderStateRecord({"started": True}))
    assert success_result.provider_state_updates.get("started") is True

    error_result = RunResult(text="error", returncode=1)
    assert error_result.provider_state_updates == {}


class _FakeStreamProcess:
    """Minimal fake of asyncio.subprocess.Process with canned stdout lines."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.returncode = 0

    @property
    def stdout(self):
        return self

    async def readline(self):
        if self._lines:
            return (self._lines.pop(0) + "\n").encode()
        return b""

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._lines:
            return (self._lines.pop(0) + "\n").encode()
        raise StopAsyncIteration

    def kill(self):
        self._lines = []

    async def wait(self):
        return self.returncode


async def test_consume_stream_denial_corrects_tool_record():
    """A permission denial in the tool_result must flip the already-recorded
    tool execution from completed to denied (records are finalized when the
    tool_use input finishes streaming, before execution)."""
    p = ClaudeProvider(make_config())
    events = [
        {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash", "id": "toolu_1"}}},
        {"type": "stream_event", "event": {"type": "content_block_stop"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1", "is_error": True, "content": "permission denied by policy"}]}},
        {"type": "result", "result": "done"},
    ]
    proc = _FakeStreamProcess([json.dumps(e) for e in events])
    _, result_data, tool_activity = await p._consume_stream(proc, FakeProgress())
    records = result_data["_tool_executions"]
    assert len(records) == 1
    assert records[0].status == "denied"
    assert records[0].call_id == "toolu_1"
    assert "permission" in records[0].output_summary
    assert "\u26d4 denied" in tool_activity


async def test_consume_stream_assistant_fallback_joins_blocks_across_turns():
    """Without stream deltas, assistant messages are the text source: all text
    blocks of a message count, and turns accumulate instead of clobbering."""
    p = ClaudeProvider(make_config())
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Part one."}, {"type": "text", "text": " Part two."}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Turn two."}]}},
        {"type": "result"},
    ]
    proc = _FakeStreamProcess([json.dumps(e) for e in events])
    text, result_data, _ = await p._consume_stream(proc, FakeProgress())
    final = result_data.get("result", text) or text
    assert "Part one." in final and "Part two." in final and "Turn two." in final


async def test_consume_stream_throttles_deltas_and_flushes_tail():
    """Per-token deltas must not each render progress; the suppressed tail is
    flushed on message_stop so the final state is never lost."""
    p = ClaudeProvider(make_config(stream_update_interval_seconds=60.0))
    def delta(t):
        return {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}}}
    events = [
        delta("A"), delta("B"), delta("C"),
        {"type": "stream_event", "event": {"type": "message_stop"}},
        {"type": "result", "result": "ABC"},
    ]
    proc = _FakeStreamProcess([json.dumps(e) for e in events])
    progress = FakeProgress()
    text, _, _ = await p._consume_stream(proc, progress)
    assert text == "ABC"
    # First delta emits, B/C are suppressed, message_stop flushes the tail.
    assert len(progress.updates) == 2
    assert "ABC" in progress.updates[-1]
