"""Tests for claude provider — command building, session state."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.providers.claude import ClaudeProvider
from tests.support.assertions import Checks
from tests.support.config_support import make_config

checks = Checks()
check = checks.check
check_contains = checks.check_contains


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

checks.run_and_exit()
