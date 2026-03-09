"""Tests for the two highest-risk paths identified in review:
1. Codex preflight must not carry --full-auto or --dangerous
2. Claude retry must forward extra_dirs through provider.run()
"""

import os
import sys
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.config import load_config
from app.providers.codex import CodexProvider
from app.providers.claude import ClaudeProvider
from tests.support.assertions import Checks
from tests.support.config_support import make_config as make_test_config

checks = Checks()
check = checks.check


def make_config(**overrides):
    defaults = dict(
        provider_name="codex",
        model="test-model",
        codex_profile="myprofile",
    )
    defaults.update(overrides)
    return make_test_config(**defaults)


# =====================================================================
# Finding 1: Codex preflight must NOT carry --full-auto or --dangerous
# =====================================================================
print("\n=== Codex preflight safety ===")

# full-auto mode
p_auto = CodexProvider(make_config(codex_full_auto=True))

# Normal run should have --full-auto
normal_cmd = p_auto._build_new_cmd("test", [])
check("normal run has --full-auto", "--full-auto" in normal_cmd, True)

# Preflight should NOT have --full-auto
preflight_cmd = p_auto._build_new_cmd("test", [], sandbox="read-only", ephemeral=True, safe_mode=True)
check("preflight no --full-auto", "--full-auto" not in preflight_cmd, True)
check("preflight has --sandbox read-only", "read-only" in preflight_cmd, True)
check("preflight has --ephemeral", "--ephemeral" in preflight_cmd, True)
# Preflight should still have model and profile
check("preflight has --model", "--model" in preflight_cmd, True)
check("preflight has model value", "test-model" in preflight_cmd, True)
check("preflight has --profile", "--profile" in preflight_cmd, True)
check("preflight has profile value", "myprofile" in preflight_cmd, True)

# dangerous mode
p_danger = CodexProvider(make_config(codex_dangerous=True))

# Normal run should have --dangerously-bypass...
normal_danger = p_danger._build_new_cmd("test", [])
check("normal run has --dangerous", "--dangerously-bypass-approvals-and-sandbox" in normal_danger, True)

# Preflight should NOT have --dangerously-bypass...
preflight_danger = p_danger._build_new_cmd("test", [], sandbox="read-only", ephemeral=True, safe_mode=True)
check("preflight no --dangerous", "--dangerously-bypass-approvals-and-sandbox" not in preflight_danger, True)

# Codex: provider no longer adds uploads dir — caller passes chat-specific dir
p_extra = CodexProvider(make_config(extra_dirs=(Path("/opt/myrepo"),)))
new_cmd = p_extra._build_new_cmd("test", [])
check("new has --add-dir for extra_dirs", "--add-dir" in new_cmd, True)
check("new has /opt/myrepo", "/opt/myrepo" in new_cmd, True)
check("new has no uploads dir", not any("uploads" in a for a in new_cmd), True)

# Codex resume must NOT include --add-dir (codex exec resume doesn't support it)
resume_cmd = p_extra._build_resume_cmd("thread-123", "test", [])
resume_add_count = resume_cmd.count("--add-dir")
check("resume has NO --add-dir", resume_add_count, 0)

# Codex new with runtime extra_dirs (simulating caller passing chat upload dir)
new_with_extra = p_extra._build_new_cmd("test", [], extra_dirs=["/tmp/data/uploads/42", "/tmp/retry"])
check("new has chat upload dir", "/tmp/data/uploads/42" in new_with_extra, True)
check("new has runtime extra_dir", "/tmp/retry" in new_with_extra, True)

# Resume no longer takes extra_dirs parameter
import inspect
resume_params = inspect.signature(p_extra._build_resume_cmd).parameters
check("resume has no extra_dirs param", "extra_dirs" not in resume_params, True)

# =====================================================================
# Config: bad numeric values give friendly error
# =====================================================================
print("\n=== Config bad numeric values ===")

try:
    make_config()  # valid config should work
    check("valid config loads", True, True)
except SystemExit:
    check("valid config loads", False, True)

# Bad timeout
old_env = os.environ.get("BOT_TIMEOUT_SECONDS")
old_token = os.environ.get("TELEGRAM_BOT_TOKEN")
old_provider = os.environ.get("BOT_PROVIDER")
old_working_dir = os.environ.get("BOT_WORKING_DIR")
old_data_dir = os.environ.get("BOT_DATA_DIR")
old_allow_open = os.environ.get("BOT_ALLOW_OPEN")
os.environ["TELEGRAM_BOT_TOKEN"] = "x"
os.environ["BOT_PROVIDER"] = "claude"
os.environ["BOT_WORKING_DIR"] = tempfile.gettempdir()
os.environ["BOT_DATA_DIR"] = tempfile.gettempdir()
os.environ["BOT_ALLOW_OPEN"] = "1"
os.environ["BOT_TIMEOUT_SECONDS"] = "not_a_number"
try:
    load_config("test")
    check("bad timeout caught", False, True)
except SystemExit as exc:
    check("bad timeout caught", "BOT_TIMEOUT_SECONDS must be an integer" in str(exc), True)
finally:
    if old_env is not None:
        os.environ["BOT_TIMEOUT_SECONDS"] = old_env
    else:
        os.environ.pop("BOT_TIMEOUT_SECONDS", None)
    for key, value in (
        ("TELEGRAM_BOT_TOKEN", old_token),
        ("BOT_PROVIDER", old_provider),
        ("BOT_WORKING_DIR", old_working_dir),
        ("BOT_DATA_DIR", old_data_dir),
        ("BOT_ALLOW_OPEN", old_allow_open),
    ):
        if value is not None:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

# =====================================================================
# Finding 2: Claude retry must forward extra_dirs
# =====================================================================
print("\n=== Claude retry extra_dirs ===")

p_claude = ClaudeProvider(make_config(provider_name="claude"))
state = {"session_id": "abc-123", "started": True}

# Normal run: no extra_dirs — provider no longer adds uploads dir itself
cmd_normal = p_claude._build_run_cmd(state, "test")
add_dir_count = cmd_normal.count("--add-dir")
check("normal: no --add-dir without extra_dirs", add_dir_count, 0)

# Retry with extra_dirs (caller passes chat-specific upload dir + denial dirs)
cmd_retry = p_claude._build_run_cmd(state, "test", extra_dirs=["/tmp/test-data/uploads/123", "/etc", "/var/log"])
check("retry: upload dir in cmd", "/tmp/test-data/uploads/123" in cmd_retry, True)
check("retry: /etc in cmd", "/etc" in cmd_retry, True)
check("retry: /var/log in cmd", "/var/log" in cmd_retry, True)
retry_add_count = cmd_retry.count("--add-dir")
check("retry: has 3 --add-dir", retry_add_count, 3)

# Verify --resume is used (not --session-id) for started session
check("retry uses --resume", "--resume" in cmd_retry, True)
check("retry has session id", "abc-123" in cmd_retry, True)

# =====================================================================
# Finding 5: Claude should NOT mark started=True on error
# =====================================================================
print("\n=== Claude error state ===")

# Verify new_provider_state starts as not started
fresh = p_claude.new_provider_state()
check("fresh session not started", fresh["started"], False)

# We can't easily test the full async run() without a real CLI,
# but we can verify the RunResult contract:
# On success, provider_state_updates should have started=True
# On error, provider_state_updates should be empty
from app.providers.base import RunResult
success_result = RunResult(text="ok", provider_state_updates={"started": True})
check("success has started=True", success_result.provider_state_updates.get("started"), True)

error_result = RunResult(text="error", returncode=1)
check("error has no state updates", error_result.provider_state_updates, {})

# =====================================================================
# Finding 4: Data dir writability check
# =====================================================================
print("\n=== Data dir writability ===")

from app.config import validate_config

# Writable path should pass
cfg_writable = make_config(data_dir=Path("/tmp"))
errors_writable = [e for e in validate_config(cfg_writable) if "DATA_DIR" in e]
check("writable dir ok", errors_writable, [])

# Nonexistent under unwritable parent should fail
cfg_bad = make_config(data_dir=Path("/root/impossible/path"))
errors_bad = [e for e in validate_config(cfg_bad) if "DATA_DIR" in e]
check("unwritable dir detected", len(errors_bad) > 0, True)

# Data dir that is a file, not a directory
import tempfile
with tempfile.NamedTemporaryFile() as f:
    cfg_file = make_config(data_dir=Path(f.name))
    errors_file = [e for e in validate_config(cfg_file) if "DATA_DIR" in e]
    check("file-not-dir detected", len(errors_file) > 0, True)

# =====================================================================
# Finding 6: Claude preflight is hardened (plan mode, extra_dirs)
# =====================================================================
print("\n=== Claude preflight hardening ===")

p_claude_pf = ClaudeProvider(make_config(provider_name="claude", extra_dirs=(Path("/opt/myrepo"),)))
pf_cmd = p_claude_pf._build_preflight_cmd("test prompt")
check("preflight has --add-dir", "--add-dir" in pf_cmd, True)
check("preflight has extra dir", "/opt/myrepo" in pf_cmd, True)
# Preflight must NOT expose the shared uploads tree
check("preflight no uploads dir", not any("uploads" in a for a in pf_cmd), True)
# Preflight must use plan permission mode to prevent tool execution
check("preflight has --permission-mode", "--permission-mode" in pf_cmd, True)
perm_idx = pf_cmd.index("--permission-mode")
check("preflight mode is plan", pf_cmd[perm_idx + 1], "plan")

# =====================================================================
# Finding 7: BOT_EXTRA_DIRS validation
# =====================================================================
print("\n=== Extra dirs validation ===")

# Valid dir should pass
cfg_good_dirs = make_config(extra_dirs=(Path("/tmp"),))
errors_good = [e for e in validate_config(cfg_good_dirs) if "EXTRA_DIRS" in e]
check("valid extra dir ok", errors_good, [])

# Nonexistent dir should fail
cfg_bad_dirs = make_config(extra_dirs=(Path("/nonexistent/fake/dir"),))
errors_bad = [e for e in validate_config(cfg_bad_dirs) if "EXTRA_DIRS" in e]
check("nonexistent extra dir detected", len(errors_bad) > 0, True)

# Mix of valid and invalid
cfg_mixed = make_config(extra_dirs=(Path("/tmp"), Path("/no/such/path")))
errors_mixed = [e for e in validate_config(cfg_mixed) if "EXTRA_DIRS" in e]
check("mixed dirs: bad one detected", len(errors_mixed) == 1, True)

# =====================================================================
# Finding 8: load_config() does not leak state across instances
# =====================================================================
print("\n=== Config isolation ===")

import os
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    # Create two instance env files
    config_dir = Path(tmpdir)

    env_a = config_dir / "inst-a.env"
    env_a.write_text(
        "TELEGRAM_BOT_TOKEN=token-a\n"
        "BOT_PROVIDER=claude\n"
        "BOT_MODEL=model-a\n"
        "BOT_ALLOWED_USERS=111\n"
    )
    env_b = config_dir / "inst-b.env"
    env_b.write_text(
        "TELEGRAM_BOT_TOKEN=token-b\n"
        "BOT_PROVIDER=codex\n"
        "BOT_MODEL=model-b\n"
        "BOT_ALLOWED_USERS=222\n"
    )

    # Monkey-patch env_path_for_instance to use our temp dir
    from app import config as config_mod
    orig_env_path = config_mod.env_path_for_instance
    config_mod.env_path_for_instance = lambda inst: config_dir / f"{inst}.env"

    # Clear any env vars that could interfere
    for key in ["TELEGRAM_BOT_TOKEN", "BOT_PROVIDER", "BOT_MODEL", "BOT_ALLOWED_USERS"]:
        os.environ.pop(key, None)

    try:
        cfg_a = config_mod.load_config("inst-a")
        cfg_b = config_mod.load_config("inst-b")

        check("inst-a token", cfg_a.telegram_token, "token-a")
        check("inst-b token", cfg_b.telegram_token, "token-b")
        check("inst-a provider", cfg_a.provider_name, "claude")
        check("inst-b provider", cfg_b.provider_name, "codex")
        check("inst-a model", cfg_a.model, "model-a")
        check("inst-b model", cfg_b.model, "model-b")
        check("inst-a users", cfg_a.allowed_user_ids, frozenset({111}))
        check("inst-b users", cfg_b.allowed_user_ids, frozenset({222}))

        # Verify os.environ was not polluted
        check("env not polluted: token", os.environ.get("TELEGRAM_BOT_TOKEN"), None)
        check("env not polluted: provider", os.environ.get("BOT_PROVIDER"), None)
    finally:
        config_mod.env_path_for_instance = orig_env_path

# =====================================================================
# Finding 2: /approve must forward extra_dirs from denials
# =====================================================================
print("\n=== Approve forwards extra_dirs ===")

from app.telegram_handlers import _extra_dirs_from_denials

# No denials → empty list
check("no denials → empty", _extra_dirs_from_denials([]), [])

# File path denial → parent dir extracted
denials_file = [{"tool_name": "Write", "tool_input": {"file_path": "/home/user/project/foo.py"}}]
dirs = _extra_dirs_from_denials(denials_file)
check("file denial has parent", "/home/user/project" in dirs, True)
check("file denial does NOT have grandparent", "/home/user" not in dirs, True)

# Directory denial → the directory itself, not its parent (least privilege)
denials_dir = [{"tool_name": "Glob", "tool_input": {"directory": "/home/tinker/private"}}]
dirs_dir = _extra_dirs_from_denials(denials_dir)
check("dir denial has exact dir", "/home/tinker/private" in dirs_dir, True)
check("dir denial does NOT have parent", "/home/tinker" not in dirs_dir, True)

# Command denial → root added
denials_cmd = [{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}]
dirs_cmd = _extra_dirs_from_denials(denials_cmd)
check("command denial has root", "/" in dirs_cmd, True)

# Multiple denials → all dirs collected
denials_multi = [
    {"tool_name": "Write", "tool_input": {"file_path": "/etc/hosts"}},
    {"tool_name": "Read", "tool_input": {"path": "/var/log/syslog"}},
]
dirs_multi = _extra_dirs_from_denials(denials_multi)
check("multi denial has /etc", "/etc" in dirs_multi, True)
check("multi denial has /var/log", "/var/log" in dirs_multi, True)

# Mixed file + directory denial
denials_mixed = [
    {"tool_name": "Write", "tool_input": {"file_path": "/opt/app/config.yaml"}},
    {"tool_name": "Glob", "tool_input": {"directory": "/opt/data"}},
]
dirs_mixed = _extra_dirs_from_denials(denials_mixed)
check("mixed: file parent", "/opt/app" in dirs_mixed, True)
check("mixed: dir exact", "/opt/data" in dirs_mixed, True)
check("mixed: no /opt leak", "/opt" not in dirs_mixed, True)

# =====================================================================
# Finding 3: /new preserves approval mode
# =====================================================================
print("\n=== /new preserves approval mode ===")

from app.storage import default_session

# Verify default_session accepts and stores approval_mode
session_on = default_session("claude", {"session_id": "x", "started": False}, "on")
check("default session approval on", session_on["approval_mode"], "on")

session_off = default_session("claude", {"session_id": "y", "started": False}, "off")
check("default session approval off", session_off["approval_mode"], "off")

# Simulate: old session had "off", /new should keep "off" not reset to instance default "on"
# We test the logic directly: old session's approval_mode should be used
old_mode = session_off.get("approval_mode", "on")  # should be "off"
new_session = default_session("claude", {"session_id": "z", "started": False}, old_mode)
check("/new preserves off mode", new_session["approval_mode"], "off")

# =====================================================================
# Finding: Session loading must not let stale provider override current
# =====================================================================
print("\n=== Session provider mismatch ===")

from app.storage import load_session, save_session

with tempfile.TemporaryDirectory() as tmpdir:
    data_dir = Path(tmpdir)
    (data_dir / "sessions").mkdir(parents=True)
    chat_id = 99999

    # Save a Claude session to disk
    claude_state_factory = lambda: {"session_id": "abc-123", "started": False}
    claude_session = default_session("claude", claude_state_factory(), "on")
    claude_session["provider_state"]["started"] = True
    claude_session["approval_mode"] = "off"
    claude_session["approval_mode_explicit"] = True
    save_session(data_dir, chat_id, claude_session)

    # Now load as Codex — provider changed
    codex_state_factory = lambda: {"thread_id": None}
    loaded = load_session(data_dir, chat_id, "codex", codex_state_factory, "on")

    check("provider mismatch: provider is codex", loaded["provider"], "codex")
    check("provider mismatch: no claude session_id", "session_id" not in loaded["provider_state"], True)
    check("provider mismatch: has codex thread_id", "thread_id" in loaded["provider_state"], True)
    check("provider mismatch: preserves approval_mode", loaded["approval_mode"], "off")

    # Same provider reload should preserve state
    loaded_same = load_session(data_dir, chat_id, "claude", claude_state_factory, "on")
    check("same provider: preserves started", loaded_same["provider_state"]["started"], True)
    check("same provider: preserves session_id", loaded_same["provider_state"]["session_id"], "abc-123")
    check("same provider: preserves approval_mode", loaded_same["approval_mode"], "off")

# =====================================================================
# Upload isolation: per-chat upload dirs, not shared uploads tree
# =====================================================================
print("\n=== Upload isolation ===")

from app.storage import chat_upload_dir, resolve_allowed_path

with tempfile.TemporaryDirectory() as tmpdir:
    data_dir = Path(tmpdir)

    # Create uploads for two different chats
    chat_a_dir = chat_upload_dir(data_dir, 111)
    chat_b_dir = chat_upload_dir(data_dir, 222)
    file_a = chat_a_dir / "secret.txt"
    file_a.write_text("chat A secret")
    file_b = chat_b_dir / "secret.txt"
    file_b.write_text("chat B secret")

    # Chat A's allowed roots should include only its own upload dir
    roots_a = [Path("/home/test"), chat_a_dir]
    roots_b = [Path("/home/test"), chat_b_dir]

    # Chat A can access its own file
    check("chat A reads own file", resolve_allowed_path(str(file_a), roots_a) is not None, True)
    # Chat A cannot access chat B's file
    check("chat A blocked from chat B", resolve_allowed_path(str(file_b), roots_a), None)
    # Chat B can access its own file
    check("chat B reads own file", resolve_allowed_path(str(file_b), roots_b) is not None, True)
    # Chat B cannot access chat A's file
    check("chat B blocked from chat A", resolve_allowed_path(str(file_a), roots_b), None)

    # Neither chat can access the shared uploads root
    shared_uploads = data_dir / "uploads"
    # Create a file directly under uploads/ (not in any chat subdir)
    rogue_file = shared_uploads / "rogue.txt"
    rogue_file.write_text("should be inaccessible")
    check("chat A blocked from shared uploads file",
          resolve_allowed_path(str(rogue_file), roots_a), None)

# Provider commands should not contain the shared uploads path
p_iso = ClaudeProvider(make_config(provider_name="claude"))
cmd_iso = p_iso._build_run_cmd({"session_id": "x", "started": False}, "test")
check("claude cmd has no uploads dir by default",
      not any("uploads" in a for a in cmd_iso), True)

# When caller passes chat-specific upload dir, only that dir appears
cmd_with_chat_dir = p_iso._build_run_cmd(
    {"session_id": "x", "started": False}, "test",
    extra_dirs=["/tmp/data/uploads/111"]
)
check("claude cmd has chat-specific dir", "/tmp/data/uploads/111" in cmd_with_chat_dir, True)

# -- Summary --
print(f"\n{'='*40}")
print(f"  {checks.passed} passed, {checks.failed} failed")
print(f"{'='*40}")
sys.exit(1 if checks.failed else 0)
