"""Tests for codex provider — command building, event parsing."""

import asyncio
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.config import BotConfig
from app.providers.base import RunContext, RunResult
from app.providers.codex import CodexProvider

passed = 0
failed = 0


def check(name, got, expected):
    global passed, failed
    if got == expected:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected: {expected!r}")
        print(f"    got:      {got!r}")
        failed += 1


def check_contains(name, haystack, *needles):
    global passed, failed
    ok = all(n in haystack for n in needles)
    if ok:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    missing: {[n for n in needles if n not in haystack]}")
        print(f"    in: {haystack}")
        failed += 1


def make_config(**overrides):
    defaults = dict(
        instance="test", telegram_token="x", allow_open=True,
        allowed_user_ids=frozenset(), allowed_usernames=frozenset(),
        provider_name="codex", model="", working_dir=Path("/home/test"),
        extra_dirs=(), data_dir=Path("/tmp/test-data"),
        timeout_seconds=300, approval_mode="on", role="", role_from_file=False, default_skills=(),
        stream_update_interval_seconds=1.0, typing_interval_seconds=4.0,
        codex_sandbox="workspace-write", codex_skip_git_repo_check=True,
        codex_full_auto=False, codex_dangerous=False, codex_profile="",
        admin_user_ids=frozenset(), admin_usernames=frozenset(),
        compact_mode=False, summary_model="claude-haiku-4-5-20251001",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# -- new_provider_state --
print("\n=== new_provider_state ===")
p = CodexProvider(make_config())
state = p.new_provider_state()
check("thread_id null", state["thread_id"], None)

# -- command building --
print("\n=== command building ===")
cmd = p._build_new_cmd("hello world", [])
check_contains("new cmd basics", cmd, "codex", "exec", "--json", "--sandbox", "workspace-write")
check("prompt is last", cmd[-1], "hello world")
check_contains("working dir", cmd, "-C", "/home/test")
check_contains("skip git check", cmd, "--skip-git-repo-check")

# with model
p2 = CodexProvider(make_config(model="o3"))
cmd2 = p2._build_new_cmd("test", [])
check_contains("model flag", cmd2, "--model", "o3")

# with images
cmd3 = p._build_new_cmd("test", ["/tmp/img.png", "/tmp/img2.jpg"])
check_contains("image flags", cmd3, "-i", "/tmp/img.png")

# resume
cmd4 = p._build_resume_cmd("thread-123", "continue", [])
check_contains("resume cmd", cmd4, "codex", "exec", "resume", "--json", "thread-123")
check("resume prompt last", cmd4[-1], "continue")

# full-auto
p3 = CodexProvider(make_config(codex_full_auto=True))
cmd5 = p3._build_new_cmd("test", [])
check_contains("full-auto flag", cmd5, "--full-auto")

# dangerous
p4 = CodexProvider(make_config(codex_dangerous=True))
cmd6 = p4._build_new_cmd("test", [])
check_contains("dangerous flag", cmd6, "--dangerously-bypass-approvals-and-sandbox")
check("no full-auto with dangerous", "--full-auto" not in cmd6, True)

# profile
p5 = CodexProvider(make_config(codex_profile="myprofile"))
cmd7 = p5._build_new_cmd("test", [])
check_contains("profile flag", cmd7, "--profile", "myprofile")

# ephemeral preflight
cmd8 = p._build_new_cmd("test", [], sandbox="read-only", ephemeral=True)
check_contains("ephemeral", cmd8, "--ephemeral", "--sandbox", "read-only")


class FakeProgress:
    """Minimal ProgressSink that records update calls."""
    def __init__(self):
        self.updates: list[str] = []

    async def update(self, html_text: str, *, force: bool = False) -> None:
        self.updates.append(html_text)


async def _run_skip_permissions_tests():
    global passed, failed

    print("\n=== skip_permissions behaviour ===")

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
    check("approved fresh exec is not resume", is_resume_new, False)
    check("approved fresh exec has --dangerous",
          "--dangerously-bypass-approvals-and-sandbox" in cmd_new, True)

    await provider.run({"thread_id": "thread-123"}, "continue", [], progress, context=context)
    cmd_resume, is_resume_resume = calls[-1]
    check("approved resume stays resume", is_resume_resume, True)
    check("approved resume has no --dangerous",
          "--dangerously-bypass-approvals-and-sandbox" in cmd_resume, False)
    check_contains("approved resume uses thread id", cmd_resume, "resume", "thread-123")


asyncio.run(_run_skip_permissions_tests())

# -- progress_html --
print("\n=== progress_html ===")
html1 = CodexProvider._progress_html({"type": "thread.started", "thread_id": "abc"}, False)
check_contains("thread started", html1, "Started", "abc")

html2 = CodexProvider._progress_html({"type": "thread.started", "thread_id": "abc"}, True)
check_contains("thread resumed", html2, "Resumed", "abc")

html3 = CodexProvider._progress_html({"type": "turn.started"}, False)
check_contains("turn started", html3, "Thinking")

html4 = CodexProvider._progress_html(
    {"type": "item.started", "item": {"type": "command_execution", "command": "ls -la"}}, False
)
check_contains("command started", html4, "Running command", "ls -la")

html5 = CodexProvider._progress_html(
    {"type": "item.completed", "item": {"type": "agent_message", "text": "Done!"}}, False
)
check_contains("agent message", html5, "Draft reply", "Done!")

html7 = CodexProvider._progress_html(
    {"type": "session_meta", "payload": {"id": "sess-modern"}}, False
)
check_contains("session_meta started", html7, "Started", "sess-modern")

html8 = CodexProvider._progress_html(
    {"type": "event_msg", "payload": {"type": "agent_message", "message": "modern draft"}},
    False,
)
check_contains("event_msg agent message", html8, "Draft reply", "modern draft")

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
check_contains("response_item function_call", html9, "Running command", "git status")

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
check_contains("response_item function_call_output", html9b, "Command finished", "git status", "M app/providers/codex.py")
check("function_call_output consumes call state", tool_calls, {})

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
check_contains("response_item assistant message", html10, "Draft reply", "modern response item draft")

html11 = CodexProvider._progress_html(
    {
        "type": "event_msg",
        "payload": {"type": "session_configured", "thread_id": "resume-modern"},
    },
    True,
)
check_contains("session configured resumed", html11, "Resumed", "resume-modern")

html6 = CodexProvider._progress_html({"type": "unknown"}, False)
check("unknown event", html6, None)

# -- async timeout tests for _run_cmd ------------------------------------
import tempfile
import textwrap


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


async def _run_timeout_tests():
    global passed, failed

    print("\n=== _run_cmd timeout behaviour ===")

    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    def slow_cmd(delay: float) -> list[str]:
        return [sys.executable, "-c", _slow_codex_script(delay)]

    # 1) Non-resume: 1.5s process, 1s timeout → killed on first deadline
    progress1 = FakeProgress()
    result1 = await provider._run_cmd(slow_cmd(1.5), progress1, is_resume=False)
    check("non-resume times out", result1.timed_out, True)
    check("non-resume rc=124", result1.returncode, 124)
    compaction_msgs = [u for u in progress1.updates if "compaction" in u]
    check("non-resume no compaction msg", len(compaction_msgs), 0)

    # 2) Resume: 1.5s process, 1s timeout → extends, finishes within 2s → success
    progress2 = FakeProgress()
    result2 = await provider._run_cmd(slow_cmd(1.5), progress2, is_resume=True)
    check("resume-compaction succeeds", result2.timed_out, False)
    check("resume-compaction has text", "done" in result2.text, True)
    check("resume-compaction thread_id", result2.provider_state_updates.get("thread_id"), "t-123")
    compaction_msgs2 = [u for u in progress2.updates if "compaction" in u]
    check("resume shows compaction msg", len(compaction_msgs2), 1)

    # 3) Resume: 3s process, 1s timeout → extends, still not done at 2s → killed
    progress3 = FakeProgress()
    result3 = await provider._run_cmd(slow_cmd(3), progress3, is_resume=True)
    check("resume-double-timeout times out", result3.timed_out, True)
    check("resume-double-timeout rc=124", result3.returncode, 124)
    compaction_msgs3 = [u for u in progress3.updates if "compaction" in u]
    check("resume-double-timeout shows compaction msg", len(compaction_msgs3), 1)

    # 4) Fast process: finishes before any timeout → success
    progress4 = FakeProgress()
    result4 = await provider._run_cmd(slow_cmd(0.1), progress4, is_resume=False)
    check("fast non-resume succeeds", result4.timed_out, False)
    check("fast non-resume text", "done" in result4.text, True)


asyncio.run(_run_timeout_tests())


async def _run_modern_schema_tests():
    global passed, failed

    print("\n=== _run_cmd modern schema ===")

    cfg = make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    progress1 = FakeProgress()
    result1 = await provider._run_cmd([sys.executable, "-c", _modern_codex_script()], progress1)
    check("modern schema result text", result1.text, "final modern reply")
    check("modern schema thread_id", result1.provider_state_updates.get("thread_id"), "sess-modern")
    check("modern schema started progress", any("Started Codex thread" in u for u in progress1.updates), True)
    check("modern schema thinking progress", any("Thinking" in u for u in progress1.updates), True)
    check("modern schema command progress", any("Running command" in u and "git status" in u for u in progress1.updates), True)
    check("modern schema command finish progress", any("Command finished" in u and "M app/providers/codex.py" in u for u in progress1.updates), True)
    check("modern schema draft progress", any("draft from response item" in u for u in progress1.updates), True)

    progress2 = FakeProgress()
    result2 = await provider._run_cmd(
        [sys.executable, "-c", _modern_resume_script()],
        progress2,
        is_resume=True,
    )
    check("modern resume text", result2.text, "resume final reply")
    check("modern resume thread_id", result2.provider_state_updates.get("thread_id"), "resume-modern")
    check("modern resume configured progress", any("Resumed Codex thread" in u and "resume-modern" in u for u in progress2.updates), True)
    check("modern resume draft progress", any("resume final reply" in u for u in progress2.updates), True)


asyncio.run(_run_modern_schema_tests())

# -- Summary --
print(f"\n{'='*40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*40}")
sys.exit(1 if failed else 0)
