"""Tests for codex provider — command building, event parsing."""

import sys
import tempfile
import textwrap
from pathlib import Path

from app.progress import render as render_progress
from app.providers.base import RunContext, RunResult
from app.providers.codex import CodexProvider
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProgress


# -- new_provider_state --

def test_new_provider_state():
    p = CodexProvider(make_config())
    state = p.new_provider_state()
    assert state["thread_id"] is None


# -- command building --

def test_command_building_new():
    p = CodexProvider(make_config())
    cmd = p._build_new_cmd("hello world", [])
    assert "codex" in cmd
    assert "exec" in cmd
    assert "--json" in cmd
    assert "--sandbox" in cmd
    assert "workspace-write" in cmd
    assert cmd[-1] == "hello world"
    assert "-C" in cmd
    assert "/home/test" in cmd
    assert "--skip-git-repo-check" in cmd


def test_command_building_with_model():
    p2 = CodexProvider(make_config(model="o3"))
    cmd2 = p2._build_new_cmd("test", [])
    assert "--model" in cmd2
    assert "o3" in cmd2


def test_command_building_with_images():
    p = CodexProvider(make_config())
    cmd3 = p._build_new_cmd("test", ["/tmp/img.png", "/tmp/img2.jpg"])
    assert "-i" in cmd3
    assert "/tmp/img.png" in cmd3


def test_command_building_resume():
    p = CodexProvider(make_config())
    cmd4 = p._build_resume_cmd("thread-123", "continue", [])
    assert "codex" in cmd4
    assert "exec" in cmd4
    assert "resume" in cmd4
    assert "--json" in cmd4
    assert "thread-123" in cmd4
    assert cmd4[-1] == "continue"


def test_command_building_full_auto():
    p3 = CodexProvider(make_config(codex_full_auto=True))
    cmd5 = p3._build_new_cmd("test", [])
    assert "--full-auto" in cmd5


def test_command_building_dangerous():
    p4 = CodexProvider(make_config(codex_dangerous=True))
    cmd6 = p4._build_new_cmd("test", [])
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd6
    assert "--full-auto" not in cmd6


def test_command_building_profile():
    p5 = CodexProvider(make_config(codex_profile="myprofile"))
    cmd7 = p5._build_new_cmd("test", [])
    assert "--profile" in cmd7
    assert "myprofile" in cmd7


def test_effective_model_overrides_config_model():
    """effective_model should override config.model in codex commands."""
    p = CodexProvider(make_config(model="o3"))
    cmd = p._build_new_cmd("test", [], effective_model="o4-mini")
    assert "--model" in cmd
    assert "o4-mini" in cmd
    assert "o3" not in cmd


def test_effective_model_empty_falls_back_to_config():
    """When effective_model is empty, codex should use config.model."""
    p = CodexProvider(make_config(model="o3"))
    cmd = p._build_new_cmd("test", [])
    assert "--model" in cmd
    assert "o3" in cmd


def test_effective_model_in_resume_cmd():
    """effective_model should flow through _build_resume_cmd."""
    p = CodexProvider(make_config(model="o3"))
    cmd = p._build_resume_cmd("thread-123", "continue", [], effective_model="o4-mini")
    assert "--model" in cmd
    assert "o4-mini" in cmd
    assert "o3" not in cmd


def test_command_building_ephemeral():
    p = CodexProvider(make_config())
    cmd8 = p._build_new_cmd("test", [], sandbox="read-only", ephemeral=True)
    assert "--ephemeral" in cmd8
    assert "--sandbox" in cmd8
    assert "read-only" in cmd8


# -- file_policy behaviour --

async def test_file_policy_inspect_sets_sandbox_readonly():
    """file_policy=inspect should override sandbox to read-only on new exec."""
    provider = CodexProvider(make_config())
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append((cmd, is_resume))
        return RunResult(text="ok", provider_state_updates={"thread_id": "thread-123"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]
    progress = FakeProgress()
    context = RunContext(extra_dirs=[], system_prompt="", capability_summary="",
                         provider_config={}, credential_env={}, file_policy="inspect")

    await provider.run({"thread_id": None}, "analyze code", [], progress, context=context)
    cmd, _ = calls[-1]
    # Should have read-only sandbox
    sandbox_idx = cmd.index("--sandbox")
    assert cmd[sandbox_idx + 1] == "read-only"


async def test_file_policy_edit_uses_default_sandbox():
    """file_policy=edit (or empty) should use default sandbox from config."""
    provider = CodexProvider(make_config(codex_sandbox="workspace-write"))
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append((cmd, is_resume))
        return RunResult(text="ok", provider_state_updates={"thread_id": "thread-123"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]
    progress = FakeProgress()
    context = RunContext(extra_dirs=[], system_prompt="", capability_summary="",
                         provider_config={}, credential_env={}, file_policy="edit")

    await provider.run({"thread_id": None}, "write code", [], progress, context=context)
    cmd, _ = calls[-1]
    sandbox_idx = cmd.index("--sandbox")
    assert cmd[sandbox_idx + 1] == "workspace-write"


async def test_file_policy_inspect_overrides_provider_config_sandbox():
    """file_policy=inspect must be authoritative — provider_config sandbox cannot weaken it."""
    provider = CodexProvider(make_config())
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append((cmd, is_resume))
        return RunResult(text="ok", provider_state_updates={"thread_id": "thread-123"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]
    progress = FakeProgress()
    # Skill config says workspace-write, but inspect mode must win
    context = RunContext(extra_dirs=[], system_prompt="", capability_summary="",
                         provider_config={"sandbox": "workspace-write"},
                         credential_env={}, file_policy="inspect")

    await provider.run({"thread_id": None}, "analyze code", [], progress, context=context)
    cmd, _ = calls[-1]
    sandbox_idx = cmd.index("--sandbox")
    assert cmd[sandbox_idx + 1] == "read-only", (
        f"inspect mode must force read-only, got {cmd[sandbox_idx + 1]}"
    )


async def test_provider_config_sandbox_applies_without_inspect():
    """When file_policy is not inspect, provider_config sandbox should apply."""
    provider = CodexProvider(make_config(codex_sandbox="workspace-write"))
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append((cmd, is_resume))
        return RunResult(text="ok", provider_state_updates={"thread_id": "thread-123"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]
    progress = FakeProgress()
    context = RunContext(extra_dirs=[], system_prompt="", capability_summary="",
                         provider_config={"sandbox": "read-only"},
                         credential_env={}, file_policy="edit")

    await provider.run({"thread_id": None}, "write code", [], progress, context=context)
    cmd, _ = calls[-1]
    sandbox_idx = cmd.index("--sandbox")
    assert cmd[sandbox_idx + 1] == "read-only", (
        f"provider_config sandbox should apply when not in inspect mode, got {cmd[sandbox_idx + 1]}"
    )


# -- skip_permissions behaviour --

async def test_skip_permissions_fresh_exec_preserves_full_auto():
    provider = CodexProvider(make_config(codex_full_auto=True))
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append((cmd, is_resume))
        return RunResult(text="ok", provider_state_updates={"thread_id": "thread-123"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]
    progress = FakeProgress()
    context = RunContext(extra_dirs=[], system_prompt="", capability_summary="",
                         provider_config={}, credential_env={}, skip_permissions=True)

    await provider.run({"thread_id": None}, "start", [], progress, context=context)
    cmd_new, is_resume_new = calls[-1]
    assert is_resume_new is False
    assert "--full-auto" in cmd_new
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd_new


async def test_skip_permissions_fresh_exec_adds_dangerous_when_needed():
    provider = CodexProvider(make_config(codex_full_auto=False))
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append((cmd, is_resume))
        return RunResult(text="ok", provider_state_updates={"thread_id": "thread-123"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]
    progress = FakeProgress()
    context = RunContext(extra_dirs=[], system_prompt="", capability_summary="",
                         provider_config={}, credential_env={}, skip_permissions=True)

    await provider.run({"thread_id": None}, "start", [], progress, context=context)
    cmd_new, is_resume_new = calls[-1]
    assert is_resume_new is False
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd_new


async def test_skip_permissions_resume():
    provider = CodexProvider(make_config(codex_full_auto=True))
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append((cmd, is_resume))
        return RunResult(text="ok", provider_state_updates={"thread_id": "thread-123"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]
    progress = FakeProgress()
    context = RunContext(extra_dirs=[], system_prompt="", capability_summary="",
                         provider_config={}, credential_env={}, skip_permissions=True)

    await provider.run({"thread_id": "thread-123"}, "continue", [], progress, context=context)
    cmd_resume, is_resume_resume = calls[-1]
    assert is_resume_resume is True
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd_resume
    assert "resume" in cmd_resume
    assert "thread-123" in cmd_resume


# -- _map_event + render_progress --

def _render_event(raw_event, is_resume=False, tool_calls=None):
    """Helper: map raw event → ProgressEvent → rendered HTML (or None)."""
    evt = CodexProvider._map_event(raw_event, is_resume, tool_calls)
    if evt is None:
        return None
    return render_progress(evt)


def test_progress_thread_started_suppressed():
    """Thread-started events should not produce user-visible progress (thread IDs are internal)."""
    assert _render_event({"type": "thread.started", "thread_id": "abc"}) is None


def test_progress_thread_resumed_suppressed():
    """Thread-resumed events should not produce user-visible progress."""
    assert _render_event({"type": "thread.started", "thread_id": "abc"}, is_resume=True) is None


def test_progress_turn_started():
    html = _render_event({"type": "turn.started"})
    assert "Thinking" in html


def test_progress_command_started():
    html = _render_event(
        {"type": "item.started", "item": {"type": "command_execution", "command": "ls -la"}},
    )
    assert "Running a command" in html or "Running command" in html
    assert "ls -la" in html


def test_progress_agent_message():
    html = _render_event(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Done!"}},
    )
    assert "Draft reply" in html
    assert "Done!" in html


def test_progress_session_meta_suppressed():
    """Session-meta events should not produce user-visible progress (session IDs are internal)."""
    assert _render_event(
        {"type": "session_meta", "payload": {"id": "sess-modern"}},
    ) is None


def test_progress_event_msg_agent_message():
    html = _render_event(
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "modern draft"}},
    )
    assert "Draft reply" in html
    assert "modern draft" in html


def test_progress_response_item_function_call():
    html = _render_event(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "call-1",
                "arguments": "{\"cmd\":\"git status\"}",
            },
        },
        tool_calls={},
    )
    assert "Running a command" in html or "Running command" in html
    assert "git status" in html


def test_progress_response_item_function_call_output():
    tool_calls = {"call-1": {"name": "exec_command", "command": "git status"}}
    html = _render_event(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "M app/providers/codex.py",
            },
        },
        tool_calls=tool_calls,
    )
    assert "Command finished" in html
    assert "git status" in html
    assert "M app/providers/codex.py" in html
    assert tool_calls == {}


def test_progress_response_item_assistant_message():
    html = _render_event(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "modern response item draft"}],
                "phase": "commentary",
            },
        },
    )
    assert "Draft reply" in html
    assert "modern response item draft" in html


def test_progress_session_configured_suppressed():
    """session_configured events should not produce user-visible progress."""
    assert _render_event(
        {
            "type": "event_msg",
            "payload": {"type": "session_configured", "thread_id": "resume-modern"},
        },
        is_resume=True,
    ) is None


def test_progress_unknown_event():
    assert _render_event({"type": "unknown"}) is None


# -- helper scripts for _run_cmd tests --

def _slow_codex_script(delay_seconds: float) -> str:
    """Return python source that mimics codex JSON output with a delay."""
    return textwrap.dedent(f"""\
        import json, sys, time
        sys.stdout.write(json.dumps({{"type": "thread.started", "thread_id": "t-123"}}) + "\\n")
        sys.stdout.flush()
        time.sleep({delay_seconds})
        sys.stdout.write(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": "done"}}}}) + "\\n")
        sys.stdout.flush()
    """)


def _modern_codex_script() -> str:
    """Return python source that emits the modern codex JSON event schema."""
    return textwrap.dedent("""\
        import json, sys
        events = [
            {"type": "session_meta", "payload": {"id": "sess-modern"}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": "{\\"cmd\\":\\"git status\\"}",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "M app/providers/codex.py",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "message": "draft from event message",
                    "phase": "commentary",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "draft from response item"}],
                    "phase": "commentary",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "final from response item"}],
                    "phase": "final_answer",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "last_agent_message": "final modern reply",
                },
            },
        ]
        for event in events:
            sys.stdout.write(json.dumps(event) + "\\n")
            sys.stdout.flush()
    """)


def _modern_resume_script() -> str:
    """Return python source that emits resume-time modern codex events."""
    return textwrap.dedent("""\
        import json, sys
        events = [
            {
                "type": "event_msg",
                "payload": {"type": "session_configured", "new_thread_id": "resume-modern"},
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "message": "resume final reply",
                    "phase": "final_answer",
                },
            },
        ]
        for event in events:
            sys.stdout.write(json.dumps(event) + "\\n")
            sys.stdout.flush()
    """)


# -- _run_cmd timeout behaviour --

async def test_timeout_non_resume():
    """Non-resume: 1.5s process, 1s timeout -> killed on first deadline."""
    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    def slow_cmd(delay: float) -> list[str]:
        return [sys.executable, "-c", _slow_codex_script(delay)]

    progress1 = FakeProgress()
    result1 = await provider._run_cmd(slow_cmd(1.5), progress1, is_resume=False)
    assert result1.timed_out is True
    assert result1.returncode == 124
    extended_msgs = [u for u in progress1.updates if "this may take a moment" in u]
    assert len(extended_msgs) == 0


async def test_timeout_resume_compaction_succeeds():
    """Resume: 1.5s process, 1s timeout -> extends, finishes within 2s -> success."""
    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    def slow_cmd(delay: float) -> list[str]:
        return [sys.executable, "-c", _slow_codex_script(delay)]

    progress2 = FakeProgress()
    result2 = await provider._run_cmd(slow_cmd(1.5), progress2, is_resume=True)
    assert result2.timed_out is False
    assert "done" in result2.text
    assert result2.provider_state_updates.get("thread_id") == "t-123"
    extended_msgs2 = [u for u in progress2.updates if "this may take a moment" in u]
    assert len(extended_msgs2) == 1


async def test_timeout_resume_double_timeout():
    """Resume: 3s process, 1s timeout -> extends, still not done at 2s -> killed."""
    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    def slow_cmd(delay: float) -> list[str]:
        return [sys.executable, "-c", _slow_codex_script(delay)]

    progress3 = FakeProgress()
    result3 = await provider._run_cmd(slow_cmd(3), progress3, is_resume=True)
    assert result3.timed_out is True
    assert result3.returncode == 124
    extended_msgs3 = [u for u in progress3.updates if "this may take a moment" in u]
    assert len(extended_msgs3) == 1


async def test_timeout_fast_non_resume():
    """Fast process: finishes before any timeout -> success."""
    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    def slow_cmd(delay: float) -> list[str]:
        return [sys.executable, "-c", _slow_codex_script(delay)]

    progress4 = FakeProgress()
    result4 = await provider._run_cmd(slow_cmd(0.1), progress4, is_resume=False)
    assert result4.timed_out is False
    assert "done" in result4.text


# -- _run_cmd modern schema --

async def test_modern_schema_new():
    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    progress1 = FakeProgress()
    result1 = await provider._run_cmd([sys.executable, "-c", _modern_codex_script()], progress1)
    assert result1.text == "final modern reply"
    assert result1.provider_state_updates.get("thread_id") == "sess-modern"
    # Thread/session IDs should NOT appear in user-facing progress
    assert not any("Codex thread" in u for u in progress1.updates)
    assert not any("sess-modern" in u for u in progress1.updates)
    assert any("Thinking" in u for u in progress1.updates)
    assert any(("Running command" in u or "Running a command" in u) and "git status" in u for u in progress1.updates)
    assert any("Command finished" in u and "M app/providers/codex.py" in u for u in progress1.updates)
    assert any("draft from response item" in u for u in progress1.updates)


async def test_modern_schema_resume():
    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    progress2 = FakeProgress()
    result2 = await provider._run_cmd(
        [sys.executable, "-c", _modern_resume_script()],
        progress2,
        is_resume=True,
    )
    assert result2.text == "resume final reply"
    assert result2.provider_state_updates.get("thread_id") == "resume-modern"
    # Thread/session IDs should NOT appear in user-facing progress
    assert not any("Codex thread" in u for u in progress2.updates)
    assert not any("resume-modern" in u for u in progress2.updates)
    assert any("resume final reply" in u for u in progress2.updates)


# -- Codex preflight safety (from test_high_risk.py) --


def test_codex_preflight_no_full_auto():
    """Preflight mode (safe_mode=True) must strip --full-auto."""
    p = CodexProvider(make_config(
        provider_name="codex", model="test-model", codex_profile="myprofile",
        codex_full_auto=True,
    ))
    normal_cmd = p._build_new_cmd("test", [])
    assert "--full-auto" in normal_cmd

    preflight_cmd = p._build_new_cmd("test", [], sandbox="read-only", ephemeral=True, safe_mode=True)
    assert "--full-auto" not in preflight_cmd
    assert "read-only" in preflight_cmd
    assert "--ephemeral" in preflight_cmd
    assert "--model" in preflight_cmd
    assert "test-model" in preflight_cmd


def test_codex_preflight_no_dangerous():
    """Preflight mode must strip --dangerously-bypass-approvals-and-sandbox."""
    p = CodexProvider(make_config(
        provider_name="codex", model="test-model", codex_profile="myprofile",
        codex_dangerous=True,
    ))
    normal_cmd = p._build_new_cmd("test", [])
    assert "--dangerously-bypass-approvals-and-sandbox" in normal_cmd

    preflight_cmd = p._build_new_cmd("test", [], sandbox="read-only", ephemeral=True, safe_mode=True)
    assert "--dangerously-bypass-approvals-and-sandbox" not in preflight_cmd


def test_codex_extra_dirs_no_uploads():
    """Provider new-command includes extra_dirs but not a shared uploads dir."""
    p = CodexProvider(make_config(
        provider_name="codex", model="test-model", codex_profile="myprofile",
        extra_dirs=(Path("/opt/myrepo"),),
    ))
    cmd = p._build_new_cmd("test", [])
    assert "--add-dir" in cmd
    assert "/opt/myrepo" in cmd
    assert not any("uploads" in a for a in cmd)


def test_codex_resume_no_add_dir():
    """Resume command must not include --add-dir (codex exec resume doesn't support it)."""
    p = CodexProvider(make_config(
        provider_name="codex", model="test-model", codex_profile="myprofile",
        extra_dirs=(Path("/opt/myrepo"),),
    ))
    resume_cmd = p._build_resume_cmd("thread-123", "test", [])
    assert resume_cmd.count("--add-dir") == 0


def test_codex_new_with_runtime_extra_dirs():
    """Runtime extra_dirs parameter must be merged into new command."""
    p = CodexProvider(make_config(
        provider_name="codex", model="test-model", codex_profile="myprofile",
    ))
    cmd = p._build_new_cmd("test", [], extra_dirs=["/tmp/uploads/123"])
    assert "/tmp/uploads/123" in cmd
