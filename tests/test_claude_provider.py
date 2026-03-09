"""Tests for claude provider — command building, session state."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.config import BotConfig
from app.providers.claude import ClaudeProvider

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
        provider_name="claude", model="", working_dir=Path("/home/test"),
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
p = ClaudeProvider(make_config())
state = p.new_provider_state()
check("has session_id", bool(state.get("session_id")), True)
check("not started", state["started"], False)

# -- command building: new session --
print("\n=== command building ===")
state_new = {"session_id": "abc-123", "started": False}
cmd = p._build_run_cmd(state_new, "hello world")
check_contains("new session cmd", cmd, "claude", "-p", "--output-format", "stream-json", "--verbose")
check_contains("session-id flag", cmd, "--session-id", "abc-123")
check("prompt after --", cmd[-1], "hello world")
check("-- separator", cmd[-2], "--")

# -- command building: resume --
state_resume = {"session_id": "abc-123", "started": True}
cmd2 = p._build_run_cmd(state_resume, "continue")
check_contains("resume flag", cmd2, "--resume", "abc-123")
check("no --session-id on resume", "--session-id" not in cmd2, True)

# -- command building: with model --
p2 = ClaudeProvider(make_config(model="claude-sonnet-4-6"))
cmd3 = p2._build_run_cmd(state_new, "test")
check_contains("model flag", cmd3, "--model", "claude-sonnet-4-6")

# -- command building: extra dirs --
p3 = ClaudeProvider(make_config(extra_dirs=(Path("/extra/dir"),)))
cmd4 = p3._build_run_cmd(state_new, "test")
check_contains("extra dir", cmd4, "--add-dir", "/extra/dir")

# -- command building: extra dirs from retry --
cmd5 = p._build_run_cmd(state_new, "test", extra_dirs=["/etc"])
check_contains("retry extra dir", cmd5, "--add-dir", "/etc")

# -- preflight command --
cmd6 = p._build_preflight_cmd("test preflight")
check_contains("preflight basics", cmd6, "claude", "-p", "--output-format", "stream-json")
check("no session-id in preflight", "--session-id" not in cmd6, True)
check("no resume in preflight", "--resume" not in cmd6, True)

# -- clean env --
import os
os.environ["CLAUDECODE"] = "1"
env = ClaudeProvider._clean_env()
check("CLAUDECODE removed", "CLAUDECODE" not in env, True)
check("PATH preserved", "PATH" in env, True)

# -- Summary --
print(f"\n{'='*40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*40}")
sys.exit(1 if failed else 0)
