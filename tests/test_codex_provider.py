"""Tests for codex provider — command building, event parsing."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.config import BotConfig
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

html6 = CodexProvider._progress_html({"type": "unknown"}, False)
check("unknown event", html6, None)

# -- Summary --
print(f"\n{'='*40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*40}")
sys.exit(1 if failed else 0)
