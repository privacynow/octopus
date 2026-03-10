"""Tests for codex provider — command building, event parsing."""

import sys
import tempfile
import textwrap
from pathlib import Path

from app.providers.base import RunContext, RunResult
from app.providers.codex import CodexProvider
from tests.support.config_support import make_config


class FakeProgress:
    """Minimal ProgressSink that records update calls."""
    def __init__(self):
        self.updates: list[str] = []

    async def update(self, html_text: str, *, force: bool = False) -> None:
        self.updates.append(html_text)


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


def test_command_building_ephemeral():
    p = CodexProvider(make_config())
    cmd8 = p._build_new_cmd("test", [], sandbox="read-only", ephemeral=True)
    assert "--ephemeral" in cmd8
    assert "--sandbox" in cmd8
    assert "read-only" in cmd8


# -- skip_permissions behaviour --

async def test_skip_permissions_fresh_exec():
    provider = CodexProvider(make_config(codex_full_auto=True))
    calls: list[tuple[list[str], bool]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None):
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

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None):
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


# -- progress_html --

def test_progress_html_thread_started():
    html1 = CodexProvider._progress_html({"type": "thread.started", "thread_id": "abc"}, False)
    assert "Started" in html1
    assert "abc" in html1


def test_progress_html_thread_resumed():
    html2 = CodexProvider._progress_html({"type": "thread.started", "thread_id": "abc"}, True)
    assert "Resumed" in html2
    assert "abc" in html2


def test_progress_html_turn_started():
    html3 = CodexProvider._progress_html({"type": "turn.started"}, False)
    assert "Thinking" in html3


def test_progress_html_command_started():
    html4 = CodexProvider._progress_html(
        {"type": "item.started", "item": {"type": "command_execution", "command": "ls -la"}}, False
    )
    assert "Running command" in html4
    assert "ls -la" in html4


def test_progress_html_agent_message():
    html5 = CodexProvider._progress_html(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Done!"}}, False
    )
    assert "Draft reply" in html5
    assert "Done!" in html5


def test_progress_html_session_meta():
    html7 = CodexProvider._progress_html(
        {"type": "session_meta", "payload": {"id": "sess-modern"}}, False
    )
    assert "Started" in html7
    assert "sess-modern" in html7


def test_progress_html_event_msg_agent_message():
    html8 = CodexProvider._progress_html(
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "modern draft"}},
        False,
    )
    assert "Draft reply" in html8
    assert "modern draft" in html8


def test_progress_html_response_item_function_call():
    html9 = CodexProvider._progress_html(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "call-1",
                "arguments": "{\"cmd\":\"git status\"}",
            },
        },
        False,
        {},
    )
    assert "Running command" in html9
    assert "git status" in html9


def test_progress_html_response_item_function_call_output():
    tool_calls = {"call-1": {"name": "exec_command", "command": "git status"}}
    html9b = CodexProvider._progress_html(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "M app/providers/codex.py",
            },
        },
        False,
        tool_calls,
    )
    assert "Command finished" in html9b
    assert "git status" in html9b
    assert "M app/providers/codex.py" in html9b
    assert tool_calls == {}


def test_progress_html_response_item_assistant_message():
    html10 = CodexProvider._progress_html(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "modern response item draft"}],
                "phase": "commentary",
            },
        },
        False,
    )
    assert "Draft reply" in html10
    assert "modern response item draft" in html10


def test_progress_html_session_configured_resumed():
    html11 = CodexProvider._progress_html(
        {
            "type": "event_msg",
            "payload": {"type": "session_configured", "thread_id": "resume-modern"},
        },
        True,
    )
    assert "Resumed" in html11
    assert "resume-modern" in html11


def test_progress_html_unknown_event():
    html6 = CodexProvider._progress_html({"type": "unknown"}, False)
    assert html6 is None


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
    compaction_msgs = [u for u in progress1.updates if "compaction" in u]
    assert len(compaction_msgs) == 0


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
    compaction_msgs2 = [u for u in progress2.updates if "compaction" in u]
    assert len(compaction_msgs2) == 1


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
    compaction_msgs3 = [u for u in progress3.updates if "compaction" in u]
    assert len(compaction_msgs3) == 1


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
    assert any("Started Codex thread" in u for u in progress1.updates)
    assert any("Thinking" in u for u in progress1.updates)
    assert any("Running command" in u and "git status" in u for u in progress1.updates)
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
    assert any("Resumed Codex thread" in u and "resume-modern" in u for u in progress2.updates)
    assert any("resume final reply" in u for u in progress2.updates)
