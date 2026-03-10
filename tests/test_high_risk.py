"""Tests for the two highest-risk paths identified in review:
1. Codex preflight must not carry --full-auto or --dangerous
2. Claude retry must forward extra_dirs through provider.run()
"""

import inspect
import os
import tempfile
from pathlib import Path

from app.config import load_config, validate_config
from app.providers.base import RunResult
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from app.storage import (
    chat_upload_dir,
    default_session,
    load_session,
    resolve_allowed_path,
    save_session,
)
from app.request_flow import extra_dirs_from_denials as _extra_dirs_from_denials
from tests.support.config_support import make_config as make_test_config


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

def test_codex_preflight_no_full_auto():
    # full-auto mode
    p_auto = CodexProvider(make_config(codex_full_auto=True))

    # Normal run should have --full-auto
    normal_cmd = p_auto._build_new_cmd("test", [])
    assert "--full-auto" in normal_cmd

    # Preflight should NOT have --full-auto
    preflight_cmd = p_auto._build_new_cmd("test", [], sandbox="read-only", ephemeral=True, safe_mode=True)
    assert "--full-auto" not in preflight_cmd
    assert "read-only" in preflight_cmd
    assert "--ephemeral" in preflight_cmd
    # Preflight should still have model and profile
    assert "--model" in preflight_cmd
    assert "test-model" in preflight_cmd
    assert "--profile" in preflight_cmd
    assert "myprofile" in preflight_cmd


def test_codex_preflight_no_dangerous():
    # dangerous mode
    p_danger = CodexProvider(make_config(codex_dangerous=True))

    # Normal run should have --dangerously-bypass...
    normal_danger = p_danger._build_new_cmd("test", [])
    assert "--dangerously-bypass-approvals-and-sandbox" in normal_danger

    # Preflight should NOT have --dangerously-bypass...
    preflight_danger = p_danger._build_new_cmd("test", [], sandbox="read-only", ephemeral=True, safe_mode=True)
    assert "--dangerously-bypass-approvals-and-sandbox" not in preflight_danger


def test_codex_extra_dirs_no_uploads():
    # Codex: provider no longer adds uploads dir — caller passes chat-specific dir
    p_extra = CodexProvider(make_config(extra_dirs=(Path("/opt/myrepo"),)))
    new_cmd = p_extra._build_new_cmd("test", [])
    assert "--add-dir" in new_cmd
    assert "/opt/myrepo" in new_cmd
    assert not any("uploads" in a for a in new_cmd)


def test_codex_resume_no_add_dir():
    # Codex resume must NOT include --add-dir (codex exec resume doesn't support it)
    p_extra = CodexProvider(make_config(extra_dirs=(Path("/opt/myrepo"),)))
    resume_cmd = p_extra._build_resume_cmd("thread-123", "test", [])
    resume_add_count = resume_cmd.count("--add-dir")
    assert resume_add_count == 0


def test_codex_new_with_runtime_extra_dirs():
    # Codex new with runtime extra_dirs (simulating caller passing chat upload dir)
    p_extra = CodexProvider(make_config(extra_dirs=(Path("/opt/myrepo"),)))
    new_with_extra = p_extra._build_new_cmd("test", [], extra_dirs=["/tmp/data/uploads/42", "/tmp/retry"])
    assert "/tmp/data/uploads/42" in new_with_extra
    assert "/tmp/retry" in new_with_extra


def test_codex_resume_no_extra_dirs_param():
    # Resume no longer takes extra_dirs parameter
    p_extra = CodexProvider(make_config(extra_dirs=(Path("/opt/myrepo"),)))
    resume_params = inspect.signature(p_extra._build_resume_cmd).parameters
    assert "extra_dirs" not in resume_params


# =====================================================================
# Config: bad numeric values give friendly error
# =====================================================================

def test_config_valid_loads():
    try:
        make_config()  # valid config should work
        assert True
    except SystemExit:
        assert False, "valid config should not raise SystemExit"


def test_config_bad_timeout():
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
        assert False, "bad timeout should raise SystemExit"
    except SystemExit as exc:
        assert "BOT_TIMEOUT_SECONDS must be an integer" in str(exc)
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

def test_claude_retry_no_extra_dirs():
    p_claude = ClaudeProvider(make_config(provider_name="claude"))
    state = {"session_id": "abc-123", "started": True}

    # Normal run: no extra_dirs — provider no longer adds uploads dir itself
    cmd_normal = p_claude._build_run_cmd(state, "test")
    add_dir_count = cmd_normal.count("--add-dir")
    assert add_dir_count == 0


def test_claude_retry_with_extra_dirs():
    p_claude = ClaudeProvider(make_config(provider_name="claude"))
    state = {"session_id": "abc-123", "started": True}

    # Retry with extra_dirs (caller passes chat-specific upload dir + denial dirs)
    cmd_retry = p_claude._build_run_cmd(state, "test", extra_dirs=["/tmp/test-data/uploads/123", "/etc", "/var/log"])
    assert "/tmp/test-data/uploads/123" in cmd_retry
    assert "/etc" in cmd_retry
    assert "/var/log" in cmd_retry
    retry_add_count = cmd_retry.count("--add-dir")
    assert retry_add_count == 3

    # Verify --resume is used (not --session-id) for started session
    assert "--resume" in cmd_retry
    assert "abc-123" in cmd_retry


# =====================================================================
# Finding 5: Claude should NOT mark started=True on error
# =====================================================================

def test_claude_error_state():
    p_claude = ClaudeProvider(make_config(provider_name="claude"))

    # Verify new_provider_state starts as not started
    fresh = p_claude.new_provider_state()
    assert fresh["started"] is False

    # On success, provider_state_updates should have started=True
    # On error, provider_state_updates should be empty
    success_result = RunResult(text="ok", provider_state_updates={"started": True})
    assert success_result.provider_state_updates.get("started") is True

    error_result = RunResult(text="error", returncode=1)
    assert error_result.provider_state_updates == {}


# =====================================================================
# Finding 4: Data dir writability check
# =====================================================================

def test_data_dir_writable():
    cfg_writable = make_config(data_dir=Path("/tmp"))
    errors_writable = [e for e in validate_config(cfg_writable) if "DATA_DIR" in e]
    assert errors_writable == []


def test_data_dir_unwritable():
    cfg_bad = make_config(data_dir=Path("/root/impossible/path"))
    errors_bad = [e for e in validate_config(cfg_bad) if "DATA_DIR" in e]
    assert len(errors_bad) > 0


def test_data_dir_is_file():
    with tempfile.NamedTemporaryFile() as f:
        cfg_file = make_config(data_dir=Path(f.name))
        errors_file = [e for e in validate_config(cfg_file) if "DATA_DIR" in e]
        assert len(errors_file) > 0


# =====================================================================
# Finding 6: Claude preflight is hardened (plan mode, extra_dirs)
# =====================================================================

def test_claude_preflight_hardening():
    p_claude_pf = ClaudeProvider(make_config(provider_name="claude", extra_dirs=(Path("/opt/myrepo"),)))
    pf_cmd = p_claude_pf._build_preflight_cmd("test prompt")
    assert "--add-dir" in pf_cmd
    assert "/opt/myrepo" in pf_cmd
    # Preflight must NOT expose the shared uploads tree
    assert not any("uploads" in a for a in pf_cmd)
    # Preflight must use plan permission mode to prevent tool execution
    assert "--permission-mode" in pf_cmd
    perm_idx = pf_cmd.index("--permission-mode")
    assert pf_cmd[perm_idx + 1] == "plan"


# =====================================================================
# Finding 7: BOT_EXTRA_DIRS validation
# =====================================================================

def test_extra_dirs_valid():
    cfg_good_dirs = make_config(extra_dirs=(Path("/tmp"),))
    errors_good = [e for e in validate_config(cfg_good_dirs) if "EXTRA_DIRS" in e]
    assert errors_good == []


def test_extra_dirs_nonexistent():
    cfg_bad_dirs = make_config(extra_dirs=(Path("/nonexistent/fake/dir"),))
    errors_bad = [e for e in validate_config(cfg_bad_dirs) if "EXTRA_DIRS" in e]
    assert len(errors_bad) > 0


def test_extra_dirs_mixed():
    cfg_mixed = make_config(extra_dirs=(Path("/tmp"), Path("/no/such/path")))
    errors_mixed = [e for e in validate_config(cfg_mixed) if "EXTRA_DIRS" in e]
    assert len(errors_mixed) == 1


# =====================================================================
# Finding 8: load_config() does not leak state across instances
# =====================================================================

def test_config_isolation():
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

            assert cfg_a.telegram_token == "token-a"
            assert cfg_b.telegram_token == "token-b"
            assert cfg_a.provider_name == "claude"
            assert cfg_b.provider_name == "codex"
            assert cfg_a.model == "model-a"
            assert cfg_b.model == "model-b"
            assert cfg_a.allowed_user_ids == frozenset({111})
            assert cfg_b.allowed_user_ids == frozenset({222})

            # Verify os.environ was not polluted
            assert os.environ.get("TELEGRAM_BOT_TOKEN") is None
            assert os.environ.get("BOT_PROVIDER") is None
        finally:
            config_mod.env_path_for_instance = orig_env_path


# =====================================================================
# Finding 2: /approve must forward extra_dirs from denials
# =====================================================================

def test_extra_dirs_from_denials_empty():
    assert _extra_dirs_from_denials([]) == []


def test_extra_dirs_from_denials_file_path():
    denials_file = [{"tool_name": "Write", "tool_input": {"file_path": "/home/user/project/foo.py"}}]
    dirs = _extra_dirs_from_denials(denials_file)
    assert "/home/user/project" in dirs
    assert "/home/user" not in dirs


def test_extra_dirs_from_denials_directory():
    denials_dir = [{"tool_name": "Glob", "tool_input": {"directory": "/home/tinker/private"}}]
    dirs_dir = _extra_dirs_from_denials(denials_dir)
    assert "/home/tinker/private" in dirs_dir
    assert "/home/tinker" not in dirs_dir


def test_extra_dirs_from_denials_command():
    denials_cmd = [{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}]
    dirs_cmd = _extra_dirs_from_denials(denials_cmd)
    assert "/" in dirs_cmd


def test_extra_dirs_from_denials_multiple():
    denials_multi = [
        {"tool_name": "Write", "tool_input": {"file_path": "/etc/hosts"}},
        {"tool_name": "Read", "tool_input": {"path": "/var/log/syslog"}},
    ]
    dirs_multi = _extra_dirs_from_denials(denials_multi)
    assert "/etc" in dirs_multi
    assert "/var/log" in dirs_multi


def test_extra_dirs_from_denials_mixed():
    denials_mixed = [
        {"tool_name": "Write", "tool_input": {"file_path": "/opt/app/config.yaml"}},
        {"tool_name": "Glob", "tool_input": {"directory": "/opt/data"}},
    ]
    dirs_mixed = _extra_dirs_from_denials(denials_mixed)
    assert "/opt/app" in dirs_mixed
    assert "/opt/data" in dirs_mixed
    assert "/opt" not in dirs_mixed


# =====================================================================
# Finding 3: /new preserves approval mode
# =====================================================================

def test_new_preserves_approval_mode():
    # Verify default_session accepts and stores approval_mode
    session_on = default_session("claude", {"session_id": "x", "started": False}, "on")
    assert session_on["approval_mode"] == "on"

    session_off = default_session("claude", {"session_id": "y", "started": False}, "off")
    assert session_off["approval_mode"] == "off"

    # Simulate: old session had "off", /new should keep "off" not reset to instance default "on"
    old_mode = session_off.get("approval_mode", "on")  # should be "off"
    new_session = default_session("claude", {"session_id": "z", "started": False}, old_mode)
    assert new_session["approval_mode"] == "off"


# =====================================================================
# Finding: Session loading must not let stale provider override current
# =====================================================================

def test_session_provider_mismatch():
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

        assert loaded["provider"] == "codex"
        assert "session_id" not in loaded["provider_state"]
        assert "thread_id" in loaded["provider_state"]
        assert loaded["approval_mode"] == "off"

        # Same provider reload should preserve state
        loaded_same = load_session(data_dir, chat_id, "claude", claude_state_factory, "on")
        assert loaded_same["provider_state"]["started"] is True
        assert loaded_same["provider_state"]["session_id"] == "abc-123"
        assert loaded_same["approval_mode"] == "off"


# =====================================================================
# Upload isolation: per-chat upload dirs, not shared uploads tree
# =====================================================================

def test_upload_isolation():
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
        assert resolve_allowed_path(str(file_a), roots_a) is not None
        # Chat A cannot access chat B's file
        assert resolve_allowed_path(str(file_b), roots_a) is None
        # Chat B can access its own file
        assert resolve_allowed_path(str(file_b), roots_b) is not None
        # Chat B cannot access chat A's file
        assert resolve_allowed_path(str(file_a), roots_b) is None

        # Neither chat can access the shared uploads root
        shared_uploads = data_dir / "uploads"
        # Create a file directly under uploads/ (not in any chat subdir)
        rogue_file = shared_uploads / "rogue.txt"
        rogue_file.write_text("should be inaccessible")
        assert resolve_allowed_path(str(rogue_file), roots_a) is None


def test_upload_isolation_provider_commands():
    # Provider commands should not contain the shared uploads path
    p_iso = ClaudeProvider(make_config(provider_name="claude"))
    cmd_iso = p_iso._build_run_cmd({"session_id": "x", "started": False}, "test")
    assert not any("uploads" in a for a in cmd_iso)

    # When caller passes chat-specific upload dir, only that dir appears
    cmd_with_chat_dir = p_iso._build_run_cmd(
        {"session_id": "x", "started": False}, "test",
        extra_dirs=["/tmp/data/uploads/111"]
    )
    assert "/tmp/data/uploads/111" in cmd_with_chat_dir
